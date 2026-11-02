"""jh: Ireland job-search pipeline v3. Run `python -I jh.py help`.

Daily (5 min run + 20 min of your time):  collect -> today -> decide -> pack -> apply -> applied
Weekly (Sunday, 15 min):                    week
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from jobhunt import packs, pipeline, report  # noqa: E402
from jobhunt.sources import hosts, linkedin_repost_info  # noqa: E402
from jobhunt.util import OUT, load_json, parse_date, save_json, today  # noqa: E402

STAGES = ["screen", "interview", "test", "offer", "accepted", "rejected", "ghosted", "withdrawn", "closed"]


def pick(ctx, query):
    hits = ctx.store.find(query)
    hits = [h for h in hits if not (h.get("knockout") or "").startswith("duplicate")] or hits
    if not hits:
        sys.exit(f"No job matches '{query}'. Try part of the key, the job ID, or 'company words'.")
    if len(hits) > 1:
        print(f"{len(hits)} matches; be more specific:")
        for h in hits[:15]:
            print(f"  {h['key']:45} {h['company']} | {h['title']} | {h['status']}")
        sys.exit(1)
    return hits[0]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="jh", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("collect", help="fetch all sources, store new roles, score them, write today page")
    c.add_argument("--only", help="regex on source labels, e.g. 'greenhouse|ashby'")
    c.add_argument("--no-linkedin", action="store_true")
    i = sub.add_parser("ingest", help="add roles from a JSON list (job-alert emails, manual finds)")
    i.add_argument("file")
    i.add_argument("--source", default="email")
    sw = sub.add_parser("import-sweep", help="import a LinkedIn sweep file (28 Oct cand_full.json format)")
    sw.add_argument("file")
    a = sub.add_parser("add", help="add one role by hand")
    for f in ("company", "title", "url"):
        a.add_argument(f"--{f}", required=True)
    a.add_argument("--location", default="Ireland")
    a.add_argument("--description", default="")
    a.add_argument("--id")
    sub.add_parser("rescore", help="re-score every stored role (after editing profile.json)")
    aj = sub.add_parser("adjust", help="record a judged score after reading the ad")
    aj.add_argument("query")
    aj.add_argument("score", type=int)
    aj.add_argument("--why", default="")
    aj.add_argument("--gaps", default="")
    aj.add_argument("--knockout")
    ajf = sub.add_parser("adjust-file", help="batch adjust: JSON [{key|id, score, why, gaps, knockout}] or a 28 Oct shortlist.json")
    ajf.add_argument("file")
    sub.add_parser("today", help="action list for today (Markdown + HTML in out/)")
    s = sub.add_parser("show", help="show one role")
    s.add_argument("query")
    d = sub.add_parser("decide", help="approve or skip a role")
    d.add_argument("query")
    d.add_argument("decision", choices=["approve", "skip"])
    d.add_argument("--reason", default="")
    p = sub.add_parser("pack", help="build the application pack for a role")
    p.add_argument("query")
    ad = sub.add_parser("applied", help="log an application")
    ad.add_argument("query")
    ad.add_argument("--date")
    ad.add_argument("--via", default="portal", choices=["portal", "referral", "agency", "easyapply", "email", "recruiter"])
    ad.add_argument("--cv")
    r = sub.add_parser("referral", help="log a referral ask or a referral given")
    r.add_argument("query")
    r.add_argument("what", choices=["asked", "given"])
    r.add_argument("--who", required=True)
    r.add_argument("--date")
    fu = sub.add_parser("followup", help="log a follow-up you sent")
    fu.add_argument("query")
    fu.add_argument("--date")
    fu.add_argument("--to", default="recruiter")
    st = sub.add_parser("stage", help="log a reply / interview / outcome")
    st.add_argument("query")
    st.add_argument("stage", choices=STAGES)
    st.add_argument("--date")
    st.add_argument("--note", default="")
    ct = sub.add_parser("contact", help="log networking: conversation, coffee, call, agency, message")
    ct.add_argument("who")
    ct.add_argument("--kind", default="conversation", choices=["conversation", "coffee", "call", "agency", "message"])
    ct.add_argument("--company", default="")
    ct.add_argument("--date")
    lb = sub.add_parser("lab", help="log hands-on lab hours (e.g. KubeVirt on kind, Terraform)")
    lb.add_argument("hours", type=float)
    lb.add_argument("--topic", required=True)
    lb.add_argument("--date")
    n = sub.add_parser("note", help="add a note to a role")
    n.add_argument("query")
    n.add_argument("text")
    w = sub.add_parser("week", help="weekly review: targets, funnel, what to change")
    w.add_argument("--days", type=int, default=7)
    se = sub.add_parser("sheet-export", help="rows for the Google Sheet tracker (Pipeline!B:AD), new A/B roles")
    se.add_argument("--since", help="YYYY-MM-DD first_seen cut-off (default: today)")
    se.add_argument("--all", action="store_true", help="include rows already exported or already in the sheet (re-try a failed append)")
    si = sub.add_parser("sheet-import", help="import your own columns from Pipeline!A1:AD values JSON")
    si.add_argument("file")
    sub.add_parser("hosts", help="hosts a full run contacts (for a cloud allowed-domains list)")
    sub.add_parser("help")
    args = ap.parse_args(argv)
    if args.cmd in (None, "help"):
        ap.print_help()
        return

    if args.cmd == "hosts":
        from jobhunt.sources import load_sources_config
        print("\n".join(hosts(load_sources_config())))
        return

    ctx = pipeline.Context()

    if args.cmd == "collect":
        summary, scored, health = pipeline.collect(ctx, only=args.only, linkedin=not args.no_linkedin)
        acts = pipeline.actions(ctx)
        report.write("today.md", report.today_md(ctx, acts, summary))
        report.write("today.html", report.today_html(ctx, acts, pipeline.week_review(ctx)))
        save_json(os.path.join(OUT, "latest_run.json"), {"summary": summary, "health": health,
                                                        "new": [{"key": r["key"], "score": s["score"], "tier": s["tier"]} for r, s in scored]})
        print(f"{summary['matching']} matching, {summary['new']} new: A {summary['tier_a']}, B {summary['tier_b']}, "
              f"screened {summary['screened']}. Sources OK {summary['sources_ok']}." + (f" Failed: {summary['failed']}" if summary["failed"] else ""))
        for r, s in sorted(scored, key=lambda x: -x[1]["score"])[:15]:
            if s["tier"] in ("A", "B"):
                print(f"  {s['tier']} {s['score']:3d} {r['company']} | {r['title']} | {r['location'][:30]}")
        print(f"Today page: {os.path.join(OUT, 'today.md')}")
    elif args.cmd in ("ingest", "import-sweep", "add"):
        if args.cmd == "add":
            jid = args.id or str(abs(hash((args.company, args.title))) % 10 ** 8)
            jobs = [{"key": f"manual:{jid}", "source": "manual", "company": args.company, "title": args.title,
                     "location": args.location, "url": args.url, "posted": today().isoformat(), "description": args.description}]
        elif args.cmd == "ingest":
            raw = load_json(args.file)
            jobs = []
            for x in raw:
                jid = x.get("id") or f"{x['company']}|{x['title']}".lower()
                jobs.append({"key": f"{args.source}:{jid}", "source": x.get("source", args.source), "company": x["company"],
                             "title": x["title"], "location": x.get("location", "Ireland"), "url": x.get("url", ""),
                             "posted": x.get("posted"), "description": x.get("description", "")})
        else:
            raw = load_json(args.file)
            jobs = []
            for x in raw.get("kept", raw if isinstance(raw, list) else []):
                lid = int(x["id"])
                jobs.append({"key": f"linkedin:{x['id']}", "source": "linkedin", "company": x["company"], "title": x["title"],
                             "location": "; ".join(x.get("locations") or [x.get("location", "")]),
                             "url": f"https://ie.linkedin.com/jobs/view/{x['id']}", "posted": x.get("listdate"),
                             "description": x.get("description", ""), "li_id": lid})
        summary, scored = pipeline.ingest(ctx, jobs, args.cmd)
        print(f"{summary['new']} new of {summary['matching']}: A {summary['tier_a']}, B {summary['tier_b']}, screened {summary['screened']}")
    elif args.cmd == "adjust":
        j = pick(ctx, args.query)
        print(f"{j['company']} | {j['title']}: {j['score']} -> {args.score}, tier {pipeline.adjust(ctx, j['key'], args.score, args.why, args.gaps, args.knockout, 'manual')}")
    elif args.cmd == "adjust-file":
        raw = load_json(args.file)
        if isinstance(raw, dict) and "categories" in raw:  # 28 Oct sweep shortlist: agent-read fits
            items, seen = [], set()
            for group in raw["categories"] + raw.get("must", []) + [{"jobs": raw.get("screened", [])}]:
                for x in group["jobs"]:
                    if x.get("fit") is not None and x["id"] not in seen:
                        seen.add(x["id"])
                        items.append({"key": f"linkedin:{x['id']}", "score": x["fit"], "why": x.get("why", ""),
                                      "gaps": x.get("gaps", ""), "knockout": x.get("knockout") or None, "by": "agents-28oct"})
        else:
            items = raw
        print(f"adjusted {pipeline.adjust_many(ctx, items)} roles")
    elif args.cmd == "rescore":
        print(f"re-scored {pipeline.rescore_all(ctx)} roles")
    elif args.cmd == "today":
        acts = pipeline.actions(ctx)
        wk = pipeline.week_review(ctx)
        md = report.today_md(ctx, acts)
        report.write("today.md", md)
        hp = report.write("today.html", report.today_html(ctx, acts, wk))
        print(md)
        print(f"HTML: {hp}")
    elif args.cmd == "show":
        j = pick(ctx, args.query)
        print(json.dumps({k: j[k] for k in ("key", "company", "title", "location", "url", "score", "tier", "status", "knockout")},
                         ensure_ascii=False, indent=1))
        print(json.dumps(j["data"], ensure_ascii=False, indent=1)[:3000])
        for e in ctx.store.events(j["key"]):
            print(f"  {e['ts']} {e['type']} {json.dumps(e['data'], ensure_ascii=False)}")
    elif args.cmd == "decide":
        j = pick(ctx, args.query)
        st = pipeline.record(ctx, j["key"], "decision", decision=args.decision, reason=args.reason)
        print(f"{j['company']} | {j['title']}: {st}")
        if args.decision == "approve":
            row = ctx.store.job(j["key"])
            path = packs.build({**row, **row["extra"]}, {**row["data"], "score": row["score"], "tier": row["tier"]}, ctx.profile, ctx.store)
            print(f"Pack: {path}")
    elif args.cmd == "pack":
        j = pick(ctx, args.query)
        row = ctx.store.job(j["key"])
        print(packs.build({**row, **row["extra"]}, {**row["data"], "score": row["score"], "tier": row["tier"]}, ctx.profile, ctx.store))
    elif args.cmd == "applied":
        j = pick(ctx, args.query)
        rule = (j["data"] or {}).get("referral_rule") or ""
        if "not apply" in rule.lower() or "do not apply" in rule.lower():
            print(f"STOP: {rule}\nNot logged. If the referrer submitted for you, use: jh referral '{j['key']}' given --who NAME")
            return
        print(pipeline.record(ctx, j["key"], "applied", via=args.via, cv=args.cv or (j["data"].get("cv") or {}).get("id"), date=args.date))
    elif args.cmd == "referral":
        j = pick(ctx, args.query)
        print(pipeline.record(ctx, j["key"], "referral_asked" if args.what == "asked" else "referral_given", who=args.who, date=args.date))
    elif args.cmd == "followup":
        j = pick(ctx, args.query)
        print(pipeline.record(ctx, j["key"], "followup", to=args.to, date=args.date))
    elif args.cmd == "stage":
        j = pick(ctx, args.query)
        print(pipeline.record(ctx, j["key"], "stage", stage=args.stage, note=args.note, date=args.date))
    elif args.cmd == "contact":
        ctx.store.add_event(f"contact:{args.who}", "contact", {"kind": args.kind, "company": args.company, "who": args.who},
                            ts=args.date or today().isoformat())
        print("logged")
    elif args.cmd == "lab":
        ctx.store.add_event(f"lab:{args.topic}", "contact", {"kind": "lab", "hours": args.hours, "topic": args.topic},
                            ts=args.date or today().isoformat())
        print(f"logged {args.hours:g} h: {args.topic}")
    elif args.cmd == "note":
        j = pick(ctx, args.query)
        print(pipeline.record(ctx, j["key"], "note", text=args.text))
    elif args.cmd == "week":
        wk = pipeline.week_review(ctx, days=args.days)
        md = report.week_md(wk)
        report.write(f"week_{wk['end']}.md", md)
        print(md)
    elif args.cmd == "sheet-export":
        since = args.since or today().isoformat()
        fresh = lambda r: args.all or not pipeline.in_sheet(ctx, r["key"])
        keys = [r["key"] for r in ctx.store.jobs("tier IN ('A','B','Manual') AND knockout IS NULL AND first_seen >= ?", (since,)) if fresh(r)]
        rows = pipeline.sheet_rows(ctx, keys)
        scr = [r for r in ctx.store.jobs("tier='C' AND (knockout IS NULL OR knockout NOT LIKE 'duplicate%') AND first_seen >= ?", (since,))
               if fresh(r) and ((r.get("data") or {}).get("parts") or {}).get("family", 0) >= 16]  # technical roles only
        screened = [[r["first_seen"][:10], r["company"], r["title"], r["location"], ((r.get("extra") or {}).get("sponsor") or {}).get("total", 0),
                     r["score"], r["knockout"] or "fit below 60", r["url"], r["key"]] for r in scr]
        p = os.path.join(OUT, "sheet_append.json")
        save_json(p, {"pipeline_B_AD": rows, "screened_A_I": screened})
        for k in keys + [r["key"] for r in scr]:
            ctx.store.add_event(k, "note", {"exported": today().isoformat()})
        print(f"{len(rows)} Pipeline rows, {len(screened)} Screened-out rows -> {p}")
    elif args.cmd == "sheet-import":
        vals = load_json(args.file)
        vals = vals.get("values", vals) if isinstance(vals, dict) else vals
        print(f"{pipeline.import_sheet(ctx, vals)} new events from the sheet")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
