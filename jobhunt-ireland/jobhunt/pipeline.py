"""Orchestration: collect -> enrich (sponsor, agency, repost) -> store -> score, and the action queue.

The action queue is the part v2 lacked. Every run answers one question: what should the candidate do today?
  decide  : Tier A/B roles waiting (oldest first, max 5 a day so it stays doable)
  apply   : approved roles (pack ready) not yet applied
  nudge   : referral asked 4+ days ago, no answer
  follow  : applied 7 / 14 days ago with no reply and no follow-up yet
  close   : applied 21+ days ago, two follow-ups sent, still silent -> mark ghosted
  thank   : interview logged today or yesterday -> thank-you note
"""
import csv
import datetime as dt
import os
import re

from . import score as scoring
from .sources import Collector, linkedin_repost_info, load_sources_config
from .sponsors import Sponsors
from .store import ACTIVE, Store
from .util import PRIVATE, load_json, parse_date, private_or_example, today


class Context:
    """Everything a command needs: config, profile, referrers, sponsors, store."""

    def __init__(self, store=None, cfg=None, profile=None, referrers=None, sponsors=None):
        self.cfg = cfg or load_sources_config()
        self.profile = profile or load_json(private_or_example("profile.json"))
        self.referrers = referrers if referrers is not None else load_json(private_or_example("referrers.json")).get("referrers", {})
        self.sponsors = sponsors or Sponsors()
        self.store = store or Store()
        self.connections = load_connections()

    def applied_dates(self):
        out = []
        for e in self.store.events(type_="applied"):
            j = self.store.job(e["key"])
            if j:
                out.append((j["company"], dt.date.fromisoformat(e["ts"][:10])))
        return out


def load_connections(path=None):
    """LinkedIn data export Connections.csv (a few note lines, then the header). Optional."""
    path = path or os.path.join(PRIVATE, "Connections.csv")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        lines = f.read().splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("First Name")), None)
    if start is None:
        return []
    out = []
    for r in csv.DictReader(lines[start:]):
        out.append({"name": f"{r.get('First Name', '')} {r.get('Last Name', '')}".strip(), "company": r.get("Company", ""),
                    "position": r.get("Position", "")})
    return out


def enrich(ctx, jobs):
    for j in jobs:
        j["agency"] = ctx.sponsors.is_agency(j["company"]) and j["source"] in ("jobs.ie", "linkedin", "email", "jobspy-indeed")
        j["sponsor"] = None if j["agency"] else ctx.sponsors.lookup(j["company"])
        if j.get("li_id"):
            info = linkedin_repost_info(j["li_id"], parse_date(j.get("posted")))
            if info:
                j.update(info)
    return jobs


def score_job(ctx, row):
    j = dict(row)
    j.update(row.get("extra") or {})
    sc = scoring.score(j, ctx.profile, ctx.cfg, ctx.referrers, ctx.connections, ctx.applied_dates(), today())
    ctx.store.set_score(row["key"], sc["score"], sc["tier"], sc["category"], sc["knockout"] or row.get("knockout"),
                        {k: v for k, v in sc.items() if k not in ("score", "tier", "category", "knockout")})
    return sc


def ingest(ctx, jobs, run_label=None, health=None):
    """Enrich, store and score a batch. Returns summary dict."""
    enrich(ctx, jobs)
    new = ctx.store.upsert_jobs(jobs)
    scored = []
    for j in new:
        row = ctx.store.job(j["key"])
        scored.append((row, score_job(ctx, row)))
    health = health or {}
    failed = [k for k, v in health.items() if not v["ok"]]
    summary = {"run_at": dt.datetime.now().isoformat(timespec="minutes"), "matching": len(jobs), "new": len(new),
               "tier_a": sum(1 for _, s in scored if s["tier"] == "A"), "tier_b": sum(1 for _, s in scored if s["tier"] == "B"),
               "screened": sum(1 for _, s in scored if s["tier"] == "C"),
               "sources_ok": f"{len(health) - len(failed)}/{len(health)}" if health else "n/a",
               "failed": ", ".join(failed), "notes": run_label or ""}
    ctx.store.add_run(**summary)
    return summary, scored


def collect(ctx, only=None, linkedin=True):
    cfg = dict(ctx.cfg)
    if not linkedin:
        cfg["linkedin"] = {**cfg.get("linkedin", {}), "enabled": False}
    jobs, health = Collector(cfg).run(only=only)
    return ingest(ctx, jobs, "collect", health) + (health,)


def adjust(ctx, key, new_score, why="", gaps="", knockout=None, by="claude"):
    """Record a judged score after reading the ad (RUNBOOK step 4). Keeps the pre-score for comparison."""
    row = ctx.store.job(key)
    d = dict(row["data"])
    d["adjusted"] = {"prescore": d.get("adjusted", {}).get("prescore", row["score"]), "by": by, "why": why, "gaps": gaps}
    if why:
        d["why"] = why
    if gaps:
        d["gap_note"] = gaps
    sp = ((row.get("extra") or {}).get("sponsor") or {}).get("total", 0)
    tier = "C" if knockout else "A" if new_score >= 75 and sp else "B" if new_score >= 60 else "C"
    if tier == "C" and d.get("referral_rule") and not knockout:
        tier = "Manual"
    d["flags"] = [f for f in d.get("flags", []) if not f.startswith("Title-only")]
    ctx.store.set_score(key, int(new_score), tier, row["category"], knockout, d)
    return tier


def adjust_many(ctx, items):
    """items: [{key or id, score, why, gaps, knockout}] - Claude writes this after reading ads in a batch."""
    n = 0
    for it in items:
        key = it.get("key")
        if not key and it.get("id"):
            hits = ctx.store.find(str(it["id"]))
            key = hits[0]["key"] if len(hits) == 1 else None
        if key and ctx.store.job(key) and it.get("score") is not None:
            adjust(ctx, key, it["score"], it.get("why", ""), it.get("gaps", ""), it.get("knockout"), it.get("by", "claude"))
            n += 1
    return n


def rescore_all(ctx):
    n = 0
    for row in ctx.store.jobs("knockout IS NULL OR knockout NOT LIKE 'duplicate%'"):
        adj = (row.get("data") or {}).get("adjusted")
        score_job(ctx, row)
        if adj:  # keep the judged score; refresh only flags, caps and referrers
            adjust(ctx, row["key"], row["score"], adj.get("why", ""), adj.get("gaps", ""), row.get("knockout"), adj.get("by", "claude"))
        n += 1
    return n


# ---------- recording actions ----------
def record(ctx, key, kind, **data):
    """kind: decision|applied|referral_asked|referral_given|followup|stage|note|contact"""
    ts = data.pop("date", None) or today().isoformat()
    ctx.store.add_event(key, kind, data, ts=ts)
    return ctx.store.status(key, ctx.store.job(key))


# ---------- action queue ----------
def actions(ctx, max_decide=5):
    st = ctx.store
    t = today()
    out = {"decide": [], "apply": [], "nudge": [], "follow": [], "close": [], "thank": [], "caps": [], "read": [], "watch": []}
    for row in st.jobs("knockout IS NULL AND tier='R'"):
        out["read"].append(row)
    for row in st.jobs("knockout IS NULL AND tier='C' AND first_seen >= ?", ((t - dt.timedelta(days=7)).isoformat(),)):
        d = row.get("data") or {}
        if d.get("must") and (d.get("parts") or {}).get("family", 0) >= 16 and (row["score"] or 0) >= 30:
            out["watch"].append(row)
    out["read"].sort(key=lambda r: -(r["score"] or 0))
    for row in st.jobs("(knockout IS NULL) AND tier IN ('A','B','Manual')"):
        status = row["status"]
        evs = st.events(row["key"])
        if status == "validate":
            out["decide"].append(row)
        elif status in ("approved", "pack_ready"):
            out["apply"].append(row)
        if status in ACTIVE:
            applied = st.applied_on(row["key"])
            fus = [e for e in evs if e["type"] == "followup"]
            asked = [e for e in evs if e["type"] == "referral_asked"]
            given = [e for e in evs if e["type"] == "referral_given"]
            if status == "applied" and applied:
                age = (t - applied).days
                if asked and not given and (t - dt.date.fromisoformat(asked[-1]["ts"][:10])).days >= 4:
                    out["nudge"].append((row, asked[-1]["data"].get("who", "referrer")))
                since_fu = (t - dt.date.fromisoformat(fus[-1]["ts"][:10])).days if fus else None
                if age >= 21 and len(fus) >= 2 and since_fu >= 7:
                    out["close"].append((row, age))
                elif age >= 14 and len(fus) == 1 and since_fu >= 7:
                    out["follow"].append((row, "Follow-up 2", age))
                elif age >= 7 and not fus:
                    out["follow"].append((row, "Follow-up 1", age))
            for e in evs:
                if e["type"] == "stage" and e["data"].get("stage") == "interview":
                    d = dt.date.fromisoformat(e["ts"][:10])
                    if 0 <= (t - d).days <= 1:
                        out["thank"].append((row, d))
    out["decide"].sort(key=lambda r: (-(r["score"] or 0), r["first_seen"]))
    out["decide_total"] = len(out["decide"])
    out["decide"] = out["decide"][:max_decide]
    out["apply"].sort(key=lambda r: -(r["score"] or 0))
    seen = set()
    for co, _ in ctx.applied_dates():
        note = scoring.caps_hit(co, ctx.profile, ctx.applied_dates(), t)
        if note and co not in seen:
            seen.add(co)
            out["caps"].append(note)
    return out


# ---------- weekly review ----------
def week_review(ctx, end=None, days=7):
    st = ctx.store
    end = end or today()
    start = end - dt.timedelta(days=days - 1)

    def in_week(ts):
        d = dt.date.fromisoformat(ts[:10])
        return start <= d <= end

    evs = [e for e in st.events() if in_week(e["ts"])]
    count = lambda pred: sum(1 for e in evs if pred(e))
    found = sum(1 for r in st.jobs("knockout IS NULL OR knockout NOT LIKE 'duplicate%'") if in_week(r["first_seen"]))
    wk = {
        "start": start.isoformat(), "end": end.isoformat(), "found": found,
        "approved": count(lambda e: e["type"] == "decision" and e["data"].get("decision") == "approve"),
        "skipped": count(lambda e: e["type"] == "decision" and e["data"].get("decision") == "skip"),
        "applications": count(lambda e: e["type"] == "applied"),
        "referral_asks": count(lambda e: e["type"] == "referral_asked"),
        "followups_sent": count(lambda e: e["type"] == "followup"),
        "networking_conversations": count(lambda e: e["type"] == "contact" and e["data"].get("kind") in ("conversation", "coffee", "call")),
        "agency_contacts": count(lambda e: e["type"] == "contact" and e["data"].get("kind") == "agency"),
        "lab_hours": sum(float(e["data"].get("hours", 0)) for e in evs if e["type"] == "contact" and e["data"].get("kind") == "lab"),
        "replies": count(lambda e: e["type"] == "stage" and e["data"].get("stage") in ("screen", "interview", "test", "offer", "rejected")),
        "interviews": count(lambda e: e["type"] == "stage" and e["data"].get("stage") in ("interview", "test")),
        "offers": count(lambda e: e["type"] == "stage" and e["data"].get("stage") == "offer"),
    }
    targets = ctx.profile.get("weekly_targets", {})
    wk["targets"] = {k: (wk.get(k, 0), v) for k, v in targets.items() if k in wk}

    # all-time funnel by channel and CV
    funnel = {}
    for e in st.events(type_="applied"):
        ch = e["data"].get("via", "portal")
        f = funnel.setdefault(ch, {"applied": 0, "replied": 0, "interview": 0, "offer": 0})
        f["applied"] += 1
        stages = [x["data"].get("stage") for x in st.events(e["key"], "stage")]
        if any(s in ("screen", "interview", "test", "offer", "rejected") for s in stages):
            f["replied"] += 1
        if any(s in ("interview", "test", "offer") for s in stages):
            f["interview"] += 1
        if "offer" in stages:
            f["offer"] += 1
    wk["funnel_by_channel"] = funnel
    tot = {k: sum(f[k] for f in funnel.values()) for k in ("applied", "replied", "interview", "offer")}
    wk["funnel_total"] = tot
    wk["diagnosis"] = diagnose(tot, wk)
    return wk


def diagnose(tot, wk):
    """Which step is failing. Thresholds are rules of thumb, not proven: revisit once there is real data."""
    out = []
    if wk["applications"] < wk["targets"].get("applications", (0, 8))[1]:
        out.append("Volume: fewer applications than your weekly target. Decide on the 'decide' list first, in one 20-minute sitting.")
    if tot["applied"] >= 10 and tot["replied"] / tot["applied"] < 0.10:
        out.append("Reply rate under 10% after 10+ applications: CV or targeting problem. Use referrals first, tailor the "
                   "summary to the ad's words, and drop roles scoring under 65.")
    if tot["replied"] >= 4 and tot["interview"] / max(1, tot["replied"]) < 0.4:
        out.append("Replies but few interviews: screening calls are the weak step. Practise the 90-second 'about me', "
                   "the Stamp 1G answer and the salary answer.")
    if tot["interview"] >= 3 and tot["offer"] == 0:
        out.append("Interviews without offers: rehearse STAR stories with numbers and do a mock interview.")
    if wk["referral_asks"] < 2:
        out.append("Few referral asks this week. A referred application is far more likely to be read than a cold one.")
    return out or ["On track. Keep the same routine next week."]


# ---------- Google Sheet sync (Claude does the actual Sheets calls via its connector) ----------
PIPE_COLS = ["Next step", "Tier", "Fit score", "Company", "Role", "Location", "Sponsor permits", "Sponsor rank", "Permit route",
             "Date found", "Job source", "Job ID", "Job posting", "Referral path", "CV version", "Why it fits", "Gaps and risks",
             "Your decision", "Skip reason", "Date applied", "Referral asked on", "Follow-up due", "Shortlisted",
             "Interview 1 date", "Interview 2 date", "Interview 3 date", "Test date", "Outcome", "Notes", "Key"]


def sheet_rows(ctx, keys):
    """Rows for Pipeline!B:AD (29 values, R..AB empty) in the v2 tracker layout."""
    rows = []
    for k in keys:
        r = ctx.store.job(k)
        d = r["data"]
        sp = (r.get("extra") or {}).get("sponsor") or {}
        why = "Have: " + ", ".join(d.get("have", [])[:5]) if d.get("have") else ""
        gaps = "; ".join((d.get("gaps", [])[:4]) + d.get("flags", [])[:3])
        cv = (d.get("cv") or {}).get("id", "v4")
        rows.append([r["tier"], r["score"], r["company"], r["title"], r["location"], sp.get("total", 0), sp.get("rank", ""),
                     d.get("permit_route", ""), r["first_seen"][:10], r["source"], "'" + k.split(":", 1)[-1], r["url"],
                     "; ".join(d.get("referrers", [])), cv, why, gaps] + [""] * 11 + [
                     ("Pay EUR {:,}-{:,}".format(*d["pay"]) if d.get("pay") else ""), k])
    return rows


def in_sheet(ctx, key):
    return any(e["type"] == "note" and (e["data"].get("in_sheet") or e["data"].get("exported")) for e in ctx.store.events(key))


def import_sheet(ctx, values):
    """values = Pipeline!A1:AD<n> as returned by the Sheets connector. Records the candidate's own columns as events.
    Idempotent: an event is only added when the sheet shows something the store does not have yet."""
    if not values:
        return 0
    head = values[0]
    idx = {h: i for i, h in enumerate(head)}
    n = 0

    def cell(row, name):
        i = idx.get(name)
        return row[i].strip() if i is not None and i < len(row) and row[i] else ""

    for row in values[1:]:
        key = cell(row, "Key")
        if not key:
            continue
        existing = ctx.store.job(key)
        if existing and (existing.get("knockout") or "").startswith("duplicate of "):
            key = existing["knockout"][len("duplicate of "):]  # the same role is stored under another source's key
        elif not existing:  # sheet rows (including manual ones) become jobs too
            new = ctx.store.upsert_jobs([{"key": key, "source": cell(row, "Job source") or "sheet", "company": cell(row, "Company"),
                                          "title": cell(row, "Role"), "location": cell(row, "Location"), "url": cell(row, "Job posting"),
                                          "posted": None, "description": ""}])
            dup = ctx.store.job(key)
            if not new and dup and (dup.get("knockout") or "").startswith("duplicate of "):
                key = dup["knockout"][len("duplicate of "):]
                existing = ctx.store.job(key)
        if not existing:
            tier = cell(row, "Tier") or "Manual"
            fit = cell(row, "Fit score")
            ctx.store.set_score(key, int(fit) if fit.isdigit() else None, tier if tier in ("A", "B", "C") else "Manual",
                                "cat2-other", None, {"why": cell(row, "Why it fits"), "gaps": [cell(row, "Gaps and risks")],
                                                     "permit_route": cell(row, "Permit route"), "flags": [], "have": [], "referrers": []})
        if not any(e["type"] == "note" and e["data"].get("in_sheet") for e in ctx.store.events(key)):
            ctx.store.add_event(key, "note", {"in_sheet": cell(row, "Key")})
        have = {(e["type"], e["data"].get("decision") or e["data"].get("stage") or e["ts"][:10]) for e in ctx.store.events(key)}
        dec = cell(row, "Your decision").lower()
        if dec in ("approve", "skip") and ("decision", dec) not in have:
            ctx.store.add_event(key, "decision", {"decision": dec, "reason": cell(row, "Skip reason"), "from": "sheet"})
            n += 1
        for col, typ in (("Date applied", "applied"), ("Referral asked on", "referral_asked")):
            d = parse_date(cell(row, col))
            if d and not any(e["type"] == typ for e in ctx.store.events(key)):
                ctx.store.add_event(key, typ, {"from": "sheet"}, ts=d.isoformat())
                n += 1
        for col in ("Interview 1 date", "Interview 2 date", "Interview 3 date", "Test date"):
            d = parse_date(cell(row, col))
            stage = "test" if col == "Test date" else "interview"
            if d and not any(e["type"] == "stage" and e["ts"][:10] == d.isoformat() for e in ctx.store.events(key)):
                ctx.store.add_event(key, "stage", {"stage": stage, "from": "sheet", "col": col}, ts=d.isoformat())
                n += 1
        out = cell(row, "Outcome").lower()
        m = re.search(r"offer|accept|reject|ghost|withdr|closed", out)
        if m:
            stage = {"offer": "offer", "accept": "accepted", "reject": "rejected", "ghost": "ghosted",
                     "withdr": "withdrawn", "closed": "closed"}[m.group(0)]
            if ("stage", stage) not in have:
                ctx.store.add_event(key, "stage", {"stage": stage, "from": "sheet", "text": out})
                n += 1
    return n
