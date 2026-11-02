"""SQLite store: jobs seen, plus an append-only event log of everything the candidate does with each role.

Status is derived from events, so history is never lost:
new -> (screened | validate) -> approved / skipped -> pack_ready -> applied -> screen -> interview -> offer
and the end states rejected / ghosted / withdrawn / closed.
"""
import datetime as dt
import json
import os
import sqlite3

from .util import STATE, norm_company, norm_title, today

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  key TEXT PRIMARY KEY, source TEXT, company TEXT, title TEXT, location TEXT, url TEXT, posted TEXT,
  description TEXT, first_seen TEXT, last_seen TEXT, dedupe TEXT, li_id INTEGER, extra TEXT,
  score INTEGER, tier TEXT, category TEXT, knockout TEXT, data TEXT
);
CREATE INDEX IF NOT EXISTS jobs_dedupe ON jobs(dedupe);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT, ts TEXT, type TEXT, data TEXT
);
CREATE INDEX IF NOT EXISTS events_key ON events(key);
CREATE TABLE IF NOT EXISTS runs (
  run_at TEXT, matching INTEGER, new INTEGER, tier_a INTEGER, tier_b INTEGER, screened INTEGER,
  sources_ok TEXT, failed TEXT, notes TEXT
);
"""

STAGES = ["new", "screened", "to_read", "validate", "skipped", "approved", "pack_ready", "applied", "screen", "interview",
          "test", "offer", "accepted", "rejected", "ghosted", "withdrawn", "closed"]
ACTIVE = {"applied", "screen", "interview", "test", "offer"}
EVENT_TYPES = {"decision", "pack", "applied", "referral_asked", "referral_given", "followup", "stage", "note", "contact"}


def dedupe_key(company, title):
    return f"{norm_company(company)}|{norm_title(title)}"


class Store:
    def __init__(self, path=None):
        path = path or os.path.join(STATE, "jobhunt.db")
        if path != ":memory:":
            os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # ---------- jobs ----------
    def upsert_jobs(self, jobs, when=None):
        """Insert new jobs, refresh last_seen on known ones. Returns the list of new jobs (by key AND by
        company+title, so the same role found on LinkedIn and the careers site counts once)."""
        when = (when or dt.datetime.now()).isoformat(timespec="minutes")
        new = []
        for j in jobs:
            dk = dedupe_key(j["company"], j["title"])
            row = self.db.execute("SELECT key FROM jobs WHERE key=?", (j["key"],)).fetchone()
            if row:
                self.db.execute("UPDATE jobs SET last_seen=? WHERE key=?", (when, j["key"]))
                continue
            twin = self.db.execute("SELECT key FROM jobs WHERE dedupe=?", (dk,)).fetchone()
            extra = {k: v for k, v in j.items() if k not in ("key", "source", "company", "title", "location", "url",
                                                             "posted", "description", "li_id")}
            if twin:  # same role, another source: remember the alternate link, do not count as new
                self.add_event(twin["key"], "note", {"alt_source": j["source"], "alt_url": j["url"], "alt_key": j["key"]})
                self.db.execute("INSERT OR IGNORE INTO jobs (key, source, company, title, location, url, posted, description,"
                                " first_seen, last_seen, dedupe, li_id, extra, knockout) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (j["key"], j["source"], j["company"], j["title"], j["location"], j["url"], j.get("posted"),
                                 j.get("description", ""), when, when, dk, j.get("li_id"), json.dumps(extra), f"duplicate of {twin['key']}"))
                continue
            self.db.execute("INSERT INTO jobs (key, source, company, title, location, url, posted, description,"
                            " first_seen, last_seen, dedupe, li_id, extra) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (j["key"], j["source"], j["company"], j["title"], j["location"], j["url"], j.get("posted"),
                             j.get("description", ""), when, when, dk, j.get("li_id"), json.dumps(extra)))
            new.append(j)
        self.db.commit()
        return new

    def set_score(self, key, score, tier, category, knockout, data):
        self.db.execute("UPDATE jobs SET score=?, tier=?, category=?, knockout=?, data=? WHERE key=?",
                        (score, tier, category, knockout, json.dumps(data, ensure_ascii=False), key))
        self.db.commit()

    def job(self, key):
        r = self.db.execute("SELECT * FROM jobs WHERE key=?", (key,)).fetchone()
        return self._row(r) if r else None

    def find(self, text):
        """Find jobs by key, job id fragment, or 'company role' words."""
        r = self.db.execute("SELECT * FROM jobs WHERE key=? OR key LIKE ?", (text, f"%{text}")).fetchall()
        if r:
            return [self._row(x) for x in r]
        words = [w.lower() for w in text.split()]
        out = []
        for x in self.db.execute("SELECT * FROM jobs WHERE knockout IS NULL OR knockout NOT LIKE 'duplicate%'"):
            hay = f"{x['company']} {x['title']}".lower()
            if all(w in hay for w in words):
                out.append(self._row(x))
        return out

    def jobs(self, where="1=1", args=()):
        return [self._row(r) for r in self.db.execute(f"SELECT * FROM jobs WHERE {where}", args)]

    def _row(self, r):
        d = dict(r)
        d["extra"] = json.loads(d["extra"] or "{}")
        d["data"] = json.loads(d["data"] or "{}")
        d["status"] = self.status(d["key"], d)
        return d

    # ---------- events ----------
    def add_event(self, key, type_, data=None, ts=None):
        assert type_ in EVENT_TYPES, type_
        ts = ts or today().isoformat()
        self.db.execute("INSERT INTO events (key, ts, type, data) VALUES (?,?,?,?)",
                        (key, ts, type_, json.dumps(data or {}, ensure_ascii=False)))
        self.db.commit()

    def events(self, key=None, type_=None):
        q, a = "SELECT * FROM events WHERE 1=1", []
        if key:
            q += " AND key=?"
            a.append(key)
        if type_:
            q += " AND type=?"
            a.append(type_)
        return [{**dict(r), "data": json.loads(r["data"] or "{}")} for r in self.db.execute(q + " ORDER BY ts, id", a)]

    def status(self, key, row=None):
        st = "new"
        if row is not None and row.get("knockout"):
            st = "screened"
        elif row is not None and row.get("tier") in ("A", "B", "Manual"):
            st = "validate"
        elif row is not None and row.get("tier") == "R":
            st = "to_read"
        elif row is not None and row.get("tier") == "C":
            st = "screened"
        # Replay in the order things were recorded; progress never moves backwards because an older-dated
        # event (e.g. "applied on 20 Oct" logged after today's approval) arrives later.
        rank = {"applied": 4, "screen": 5, "interview": 6, "test": 7, "offer": 8}
        terminal = {"accepted", "rejected", "ghosted", "withdrawn", "closed"}
        evs = sorted(self.events(key), key=lambda e: e["id"])
        for e in evs:
            t, d = e["type"], e["data"]
            if t == "decision" and rank.get(st, 0) < 4 and st not in terminal:
                st = "approved" if d.get("decision") == "approve" else "skipped"
            elif t == "pack" and st in ("approved", "validate", "new", "to_read"):
                st = "pack_ready"
            elif t == "applied" and rank.get(st, 0) < 4 and st not in terminal:
                st = "applied"
            elif t == "stage":
                s = d["stage"]
                if s in terminal or rank.get(s, 0) >= rank.get(st, 0) or st in terminal:
                    st = s
        return st

    def applied_on(self, key):
        a = [e for e in self.events(key, "applied")]
        return dt.date.fromisoformat(a[-1]["ts"][:10]) if a else None

    # ---------- runs ----------
    def add_run(self, **r):
        self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                        (r["run_at"], r["matching"], r["new"], r["tier_a"], r["tier_b"], r["screened"],
                         r["sources_ok"], r["failed"], r.get("notes", "")))
        self.db.commit()

    def runs(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM runs ORDER BY run_at")]
