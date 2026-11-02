"""Offline tests (no network). Run: python -I -m unittest discover -s tests -v"""
import datetime as dt
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp()
os.environ.update(JH_PRIVATE=os.path.join(TMP, "none"), JH_STATE=os.path.join(TMP, "state"), JH_OUT=os.path.join(TMP, "out"),
                  JH_TODAY="2026-11-02")
sys.path.insert(0, ROOT)

from jobhunt import packs, pipeline, score, sources, tone  # noqa: E402
from jobhunt.store import Store  # noqa: E402
from jobhunt.util import load_json, parse_date  # noqa: E402

CFG = sources.load_sources_config()
PROFILE = load_json(os.path.join(ROOT, "config", "profile.example.json"))
REFS = load_json(os.path.join(ROOT, "config", "referrers.example.json"))["referrers"]
DESC_TSE = ("We need a Senior Technical Support Engineer to own P1 escalations, do root cause analysis, and write KB articles. "
            "Kubernetes and VMware vSphere experience. 5+ years of experience in enterprise support. Linux and SQL are a plus. "
            "Salary €77,400 - €130,000. Hybrid, 3 days a week in the office in Dublin.")


def ctx():
    return pipeline.Context(store=Store(":memory:"), cfg=CFG, profile=PROFILE, referrers=REFS)


def J(key, company, title, desc="", loc="Dublin, Ireland", posted="2026-11-01", **kw):
    return {"key": key, "source": key.split(":")[0], "company": company, "title": title, "location": loc,
            "url": f"https://example.com/{key}", "posted": posted, "description": desc, **kw}


class FakeFetch:
    """Serves canned API answers so collector adapters run offline."""
    def __call__(self, url, data=None, raw=False, method=None, headers=None):
        if "greenhouse" in url:
            return {"jobs": [
                {"id": 1, "title": "Technical Support Engineer", "location": {"name": "Dublin, Ireland"}, "absolute_url": "u1",
                 "updated_at": "2026-11-01", "content": "&lt;p&gt;P1 escalations&lt;/p&gt;"},
                {"id": 2, "title": "Account Executive", "location": {"name": "Dublin"}, "absolute_url": "u2"},
                {"id": 3, "title": "Support Engineer", "location": {"name": "Belfast, Northern Ireland"}, "absolute_url": "u3"}]}
        if "linkedin" in url:
            card = ('<li><div data-entity-urn="urn:li:jobPosting:4485000000"><h3 class="base-search-card__title">Technical Support Engineer</h3>'
                    '<h4 class="base-search-card__subtitle"><a>Stripe</a></h4><span class="job-search-card__location">Dublin, County Dublin, Ireland</span>'
                    '<time datetime="2026-10-31">2 days ago</time></div></li>')
            return card
        raise ValueError("unexpected " + url)


class T(unittest.TestCase):
    def test_filters(self):
        f = sources.Filters(CFG)
        self.assertTrue(f.keep("Senior Technical Support Engineer", "Cork, Ireland"))
        self.assertFalse(f.keep("Technical Support Engineer (German speaking)", "Dublin"))
        self.assertFalse(f.keep("Support Engineer", "Belfast, Northern Ireland"))
        self.assertFalse(f.keep("Account Executive", "Dublin"))

    def test_collector_offline(self):
        cfg = {**CFG, "greenhouse": {"stripe": "Stripe"}, "ashby": {}, "lever": {}, "workday": [], "smartrecruiters": {}, "feeds": [],
               "linkedin": {"enabled": True, "queries": ["support"], "pages": 1, "delay_s": 0}}
        c = sources.Collector(cfg, fetcher=FakeFetch(), sleep=lambda s: None)
        jobs, health = c.run(only="greenhouse|linkedin")
        titles = sorted(j["title"] for j in jobs)
        self.assertEqual(titles, ["Technical Support Engineer", "Technical Support Engineer"])
        self.assertTrue(health["greenhouse:stripe"]["ok"] and health["linkedin"]["ok"])
        li = next(j for j in jobs if j["source"] == "linkedin")
        self.assertEqual(li["posted"], "2026-10-31")

    def test_salary_and_years_flags(self):
        self.assertEqual(score.stated_salary("Pay: €84000 - €86000 (EUR)"), (84000, 86000))
        self.assertEqual(score.stated_salary("€77,400.00 - €130,000.00 per year"), (77400, 130000))
        self.assertEqual(score.stated_salary("EUR 86k-129k"), (86000, 129000))
        sc = score.score(J("x:1", "Stripe", "Senior Technical Support Engineer", DESC_TSE.replace("5+", "8+")), PROFILE, CFG, today=dt.date(2026, 11, 2))
        self.assertTrue(any("Asks 8+ years" in f for f in sc["flags"]))
        self.assertTrue(any("Stated pay EUR 77,400" in f for f in sc["flags"]))
        self.assertTrue(any("Dublin office days" in f for f in sc["flags"]))
        self.assertIn("Pay EUR 77,400+", sc["permit_route"])

    def test_knockouts(self):
        for txt in ("Applicants must be EU citizens only", "We are unable to offer visa sponsorship for this role",
                    "Requires active security clearance", "Fluent in German is required"):
            sc = score.score(J("x:2", "Stripe", "Technical Support Engineer", txt), PROFILE, CFG)
            self.assertEqual(sc["tier"], "C", txt)
            self.assertIsNotNone(sc["knockout"], txt)

    def test_tiers_and_title_only(self):
        sp = {"brand": "Stripe", "rank": 19, "total": 101, "permits_2025": 1, "permits_2026": 1, "category": "x"}
        a = score.score(J("x:3", "Stripe", "Senior Technical Support Engineer", DESC_TSE, sponsor=sp), PROFILE, CFG, today=dt.date(2026, 11, 2))
        self.assertEqual(a["tier"], "A")
        nosp = score.score(J("x:4", "Tiny Ltd", "Senior Technical Support Engineer", DESC_TSE), PROFILE, CFG, today=dt.date(2026, 11, 2))
        self.assertEqual(nosp["tier"], "B")  # never Tier A without permit history
        r = score.score(J("x:5", "Tiny Ltd", "Designated Services Engineer", "", posted="2026-10-01"), PROFILE, CFG, today=dt.date(2026, 11, 2))
        self.assertEqual(r["tier"], "R")
        ref = score.score(J("x:6", "RefCo", "Platform Engineer", "Go and Terraform", posted="2026-09-01"), PROFILE, CFG, today=dt.date(2026, 11, 2))
        self.assertEqual(ref["tier"], "Manual")
        self.assertIn("do NOT apply", ref["referral_rule"])
        typo = score.score(J("x:7", "Cohesity", "Senior Technical Support Enginer", DESC_TSE), PROFILE, CFG)
        self.assertEqual(typo["parts"]["family"], 30)

    def test_repost(self):
        info = sources.linkedin_repost_info(4463257252, dt.date(2026, 10, 21))
        self.assertTrue(info["reposted"])
        info = sources.linkedin_repost_info(4484451273, dt.date(2026, 10, 28))
        self.assertFalse(info["reposted"])

    def test_dedupe_and_status_precedence(self):
        c = ctx()
        new = c.store.upsert_jobs([J("greenhouse:a-1", "Pure Storage", "Technical Services Engineer (2 openings)", DESC_TSE),
                                   J("linkedin:44", "Everpure", "Technical Services Engineer", "")])
        self.assertEqual(len(new), 1)
        k = "greenhouse:a-1"
        c.store.set_score(k, 80, "B", "cat3", None, {})
        self.assertEqual(c.store.status(k, c.store.job(k)), "validate")
        pipeline.record(c, k, "decision", decision="approve")
        pipeline.record(c, k, "applied", via="portal", date="2026-10-20")  # back-dated, recorded after approval
        self.assertEqual(c.store.job(k)["status"], "applied")
        pipeline.record(c, k, "decision", decision="skip")  # late change of mind must not undo an application
        self.assertEqual(c.store.job(k)["status"], "applied")
        pipeline.record(c, k, "stage", stage="interview")
        pipeline.record(c, k, "stage", stage="screen")  # older stage logged late
        self.assertEqual(c.store.job(k)["status"], "interview")

    def test_followup_queue_spacing(self):
        c = ctx()
        c.store.upsert_jobs([J("greenhouse:b-1", "Stripe", "Technical Support Engineer", DESC_TSE)])
        k = "greenhouse:b-1"
        c.store.set_score(k, 70, "B", "cat3", None, {})
        pipeline.record(c, k, "applied", date="2026-10-19")
        acts = pipeline.actions(c)
        self.assertEqual([x[1] for x in acts["follow"]], ["Follow-up 1"])
        pipeline.record(c, k, "followup", date="2026-11-01")
        self.assertEqual(pipeline.actions(c)["follow"], [])  # FU2 waits 7 days after FU1
        os.environ["JH_TODAY"] = "2026-11-08"
        try:
            self.assertEqual([x[1] for x in pipeline.actions(c)["follow"]], ["Follow-up 2"])
            pipeline.record(c, k, "followup", date="2026-11-08")
            os.environ["JH_TODAY"] = "2026-11-15"
            self.assertEqual(len(pipeline.actions(c)["close"]), 1)
        finally:
            os.environ["JH_TODAY"] = "2026-11-02"

    def test_caps(self):
        note = score.caps_hit("ExampleCorp", PROFILE, [("ExampleCorp", dt.date(2026, 10, 20)), ("ExampleCorp", dt.date(2026, 10, 25))], dt.date(2026, 11, 2))
        self.assertTrue(note.startswith("CAP REACHED"))

    def test_tone_gate(self):
        self.assertTrue(any("banned" in p for p in tone.check("I want to leverage my robust skills.")))
        self.assertTrue(any("US spelling" in p for p in tone.check("I helped optimize the organization.")))
        self.assertTrue(any("never-claim" in p for p in tone.check("I automated the checks.", PROFILE)))
        self.assertEqual(tone.check("I owned P1 incidents. I wrote RCA documents.", PROFILE), [])

    def test_pack(self):
        c = ctx()
        c.store.upsert_jobs([J("greenhouse:c-1", "Stripe", "Senior Technical Support Engineer", DESC_TSE)])
        row = c.store.job("greenhouse:c-1")
        sc = score.score({**row}, PROFILE, CFG, REFS)
        path = packs.build({**row, **row["extra"]}, sc, PROFILE, c.store, out_dir=os.path.join(TMP, "packs"))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for must in ("## 1. Keyword check", "## 3. Screening answers", "## 4. Cover note", "## 7. Follow-up drafts",
                     "## 8. Likely interview questions", "| SQL / databases | Gap |"):
            self.assertIn(must, text)
        self.assertEqual(c.store.status("greenhouse:c-1", c.store.job("greenhouse:c-1")), "pack_ready")

    def test_sheet_roundtrip(self):
        c = ctx()
        c.store.upsert_jobs([J("greenhouse:d-1", "Stripe", "Technical Support Engineer", DESC_TSE)])
        c.store.set_score("greenhouse:d-1", 74, "B", "cat3", None, {"have": ["RCA"], "gaps": ["SQL"], "flags": [], "referrers": [],
                                                                    "permit_route": "x", "cv": {"id": "v4"}})
        row = pipeline.sheet_rows(c, ["greenhouse:d-1"])[0]
        self.assertEqual(len(row), 29)  # Pipeline!B:AD
        self.assertEqual(row[-1], "greenhouse:d-1")
        head = pipeline.PIPE_COLS
        sheet = [head, ["Validate"] + row[:16] + ["Approve", "", "20/10/2026", "15/10/2026", "", "", "28/10/2026", "", "", "", "Rejected", "", "greenhouse:d-1"],
                 ["Ask referral first", "Manual", "", "Dell Technologies", "Graduate Solution Architect", "Limerick"] + [""] * 23 + ["manual:dell-D12097"]]
        n = pipeline.import_sheet(c, sheet)
        self.assertEqual(n, 5)  # decision, applied, referral asked, interview, outcome
        self.assertEqual(pipeline.import_sheet(c, sheet), 0)  # idempotent
        self.assertEqual(c.store.job("greenhouse:d-1")["status"], "rejected")
        self.assertIsNotNone(c.store.job("manual:dell-D12097"))

    def test_sheet_row_maps_to_existing_twin(self):
        c = ctx()
        c.store.upsert_jobs([J("linkedin:4463257252", "Google", "Technical Solutions Engineer I, Infrastructure, Kubernetes, Google Cloud")])
        head = pipeline.PIPE_COLS
        row = ["Validate", "A", "83", "Google", "Technical Solutions Engineer I Infrastructure Kubernetes Google Cloud", "Ireland"] + \
              [""] * 13 + ["09/10/2026"] + [""] * 9 + ["google:113956570412262086"]
        pipeline.import_sheet(c, [head, row])
        self.assertEqual(c.store.status("linkedin:4463257252", c.store.job("linkedin:4463257252")), "applied")
        self.assertTrue(pipeline.in_sheet(c, "linkedin:4463257252"))
        live = [r for r in c.store.jobs("knockout IS NULL")]
        self.assertEqual(len(live), 1)

    def test_week_review(self):
        c = ctx()
        c.store.upsert_jobs([J("greenhouse:e-1", "Stripe", "Technical Support Engineer", DESC_TSE)])
        pipeline.record(c, "greenhouse:e-1", "applied", via="referral", date="2026-10-30")
        pipeline.record(c, "greenhouse:e-1", "stage", stage="screen", date="2026-11-01")
        wk = pipeline.week_review(c, end=dt.date(2026, 11, 2))
        self.assertEqual(wk["applications"], 1)
        self.assertEqual(wk["funnel_by_channel"]["referral"]["replied"], 1)
        self.assertTrue(wk["diagnosis"])

    def test_parse_date(self):
        self.assertEqual(parse_date("09/10/2026"), dt.date(2026, 10, 9))
        self.assertEqual(parse_date("Posted 3 Days Ago"), dt.date(2026, 10, 30))
        self.assertEqual(parse_date("2026-10-28T10:00:00Z"), dt.date(2026, 10, 28))


if __name__ == "__main__":
    unittest.main()
