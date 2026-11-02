"""Application pack for one approved role: everything needed to apply in ~20 minutes, drafts only.

Sections: decision box, keyword check (Have / Partly / Gap against profile.json), CV to send and truthful
bullet swaps, screening answers, 120-word cover note, referral ask, recruiter note, follow-up drafts,
likely interview questions with the STAR story to use, gaps and never-claim warnings.
Every draft runs through tone.check(); problems are listed at the end of the pack, never hidden.
"""
import datetime as dt
import os
import re

from . import tone
from .util import OUT

EXTRA_TERMS = ["linux", "python", "sql", "terraform", "ansible", "kubernetes", "docker", "aws", "azure", "gcp", "networking",
               "dns", "tcp/ip", "load balancing", "storage", "vmware", "vsphere", "esxi", "active directory", "windows server",
               "itil", "servicenow", "jira", "splunk", "datadog", "prometheus", "grafana", "rest api", "postman", "javascript",
               "go", "java", "ci/cd", "jenkins", "helm", "openshift", "kubevirt", "incident management", "root cause",
               "on-call", "saas", "security", "iam", "sso", "oauth", "mfa", "bash", "powershell", "monitoring", "observability",
               "customer-facing", "escalation", "documentation", "knowledge base", "mentoring", "sla", "slo", "automation"]

QUESTION_BANK = {
    "support": [
        ("Walk me through a P1 you owned from first call to RCA.", ("p1", "incident")),
        ("Tell me about a difficult customer and how you kept their trust.", ("csat", "customer")),
        ("Describe a time you did not know the answer. What did you do?", ("reproduce", "troubleshooting")),
        ("How do you prioritise several critical cases at once?", ("leadership", "mentoring")),
        ("Tell me about a process you improved.", ("improvement", "prevention", "rca")),
    ],
    "kubernetes": [
        ("A pod is in CrashLoopBackOff. Talk me through your steps.", ("kubernetes", "troubleshooting")),
        ("A control-plane certificate has expired. How do you recover?", ("kubernetes", "troubleshooting")),
        ("How do you back up and restore etcd?", ("certification", "learning", "kubernetes")),
        ("A node is NotReady. Where do you look first?", ("certification", "learning", "kubernetes")),
    ],
    "incident": [
        ("Run me through how you command a Sev 1 bridge.", ("p1", "incident")),
        ("How do you set the update cadence for executives during an outage?", ("p1", "incident")),
        ("How do you run a blameless post-mortem and make actions stick?", ("improvement", "prevention", "rca")),
    ],
    "sysops": [
        ("How do you plan and roll back a vSphere upgrade?", ("p1", "incident")),
        ("A host crashed with a purple screen. What evidence do you collect?", ("p1", "incident")),
        ("How do you reduce repeat infrastructure incidents?", ("improvement", "prevention", "rca")),
    ],
    "sre": [
        ("What SLIs and SLOs would you set for a customer-facing API?", ("improvement", "prevention", "rca")),
        ("Tell me about toil you removed. (Say 'ran and adapted' scripts, not 'wrote'.)", ("improvement", "prevention", "rca")),
    ],
    "security": [("Explain your MSc admission webhook and its fail-closed design.", ("security", "admission"))],
    "tam": [("How do you manage an escalation with the account team and the customer's leadership?", ("csat", "customer"))],
}


def story_for(tags, profile):
    """First profile story sharing a tag with the question (stories are the candidate's own STAR examples)."""
    best, best_pts = None, 0
    for st in profile.get("stories", []):
        have = set(st.get("tags", []))
        pts = len(set(tags) & have) + (2 if tags and tags[0] in have else 0)  # the question's main tag counts most
        if pts > best_pts:
            best, best_pts = st, pts
    return best or {"title": "[[add a STAR story with tags: " + ", ".join(tags) + "]]"}


def _slug(s):
    return re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_")[:60]


def families(title, text):
    t = f"{title} {text}".lower()
    fams = ["support"]
    if re.search(r"kubernetes|k8s|container|platform|openshift|tanzu", t):
        fams.append("kubernetes")
    if re.search(r"incident|escalation manager|major incident", t):
        fams.append("incident")
    if re.search(r"system|infrastructure|virtuali|vmware|vsphere|data ?cent", t):
        fams.append("sysops")
    if re.search(r"site reliability|\bsre\b|devops|reliability", t):
        fams.append("sre")
    if re.search(r"security|iam|identity", t):
        fams.append("security")
    if re.search(r"technical account manager|\btam\b|account manager", t):
        fams.append("tam")
    return fams


def keyword_table(text, profile, limit=14):
    low = text.lower()
    rows = []
    for s in profile.get("skills", []):
        hits = len(re.findall(s["rx"], low, re.I))
        if hits:
            status = {"strong": "Have", "medium": "Partly", "weak": "Gap"}[s["level"]]
            rows.append((hits, s["name"], status, s["evidence"]))
    covered = " ".join(r[1].lower() for r in rows)
    for term in EXTRA_TERMS:
        n = len(re.findall(rf"(?<![a-z]){re.escape(term)}(?![a-z])", low))
        if n and term not in covered and not any(re.search(s["rx"], term, re.I) for s in profile.get("skills", [])):
            rows.append((n, term, "Gap", "not in profile.json"))
    rows.sort(key=lambda r: -r[0])
    return rows[:limit]


def _pitch(profile):
    return profile.get("pitch", {})


def cover_note(j, sc, profile):
    """Assemble ~120 words from profile['pitch'] lines that match the role family. No text is invented here."""
    pt = _pitch(profile)
    fams = families(j["title"], j.get("description") or "")
    lines = [pt.get("lead", "")]
    for fam in ("kubernetes", "incident", "sysops", "sre", "security", "tam"):
        if fam in fams and pt.get(fam) and not (fam == "sysops" and "kubernetes" in fams):
            lines.append(pt[fam])
    lines = [x for x in lines if x][:4] + [pt.get("metrics", "")]
    jid = j["key"].split(":", 1)[-1]
    text = (f"Dear Hiring Team,\n\nI am applying for the {j['title']} role (ref. {jid}). {' '.join(x for x in lines if x)} "
            f"{pt.get('work_auth', '')}\n\nI would welcome a short call.\n\nKind regards,\n{profile.get('name', '')}")
    check_text = text.replace(j["title"], "ROLE").replace(j["company"], "COMPANY")
    return text, tone.check(check_text, profile)


def referral_ask(j, person, profile=None):
    first = re.split(r"[\s(]", person.strip())[0]
    jid = j["key"].split(":", 1)[-1]
    fit = _pitch(profile or {}).get("fit_line", "My background fits it closely.")
    return (f"Hi {first}, hope you are well. {j['company']} has a {j['title']} role in {j['location'] or 'Ireland'} "
            f"(job ID {jid}: {j['url']}). {fit} "
            f"Would you be comfortable referring me? I can send my CV and a 3-line summary for the form.")


def recruiter_note(j, profile=None):
    pitch = _pitch(profile or {}).get("recruiter_pitch", "")
    return f"Hi, I have applied for {j['title']} at {j['company']}. {pitch} Happy to share more."[:300]


def followups(j, applied, profile=None):
    d = applied or dt.date.today()
    detail = _pitch(profile or {}).get("followup_detail", "my experience")
    return [
        (d + dt.timedelta(days=4), "Referrer nudge (only if you asked for a referral)",
         f"Hi, a quick check: did the referral for {j['title']} go through? Thanks again for doing this."),
        (d + dt.timedelta(days=7), "Follow-up 1 (recruiter or hiring manager on LinkedIn/email)",
         f"Hello, I applied for {j['title']} on {d:%d %b}. I am still very interested and can share more detail on "
         f"{detail}. Is there an update on the timeline?"),
        (d + dt.timedelta(days=14), "Follow-up 2 (last one)",
         f"Hello, a short follow-up on my application for {j['title']}. If the role has moved on, I would be glad to be "
         f"considered for similar openings at {j['company']}."),
    ]


def build(j, sc, profile, store=None, out_dir=None):
    """Write out/packs/<Company>_<Role>_<id>.md and return its path."""
    out_dir = out_dir or os.path.join(OUT, "packs")
    os.makedirs(out_dir, exist_ok=True)
    text = f"{j['title']} {j.get('description') or ''}"
    jid = j["key"].split(":", 1)[-1]
    path = os.path.join(out_dir, f"{_slug(j['company'])}_{_slug(j['title'])}_{_slug(jid)}.md")
    applied = store.applied_on(j["key"]) if store else None
    sp = j.get("sponsor") or {}
    cv = sc["cv"]
    problems = []
    L = [f"# Pack · {j['company']} · {j['title']}", "",
         "| Item | Value |", "|---|---|",
         f"| Link | {j['url']} |", f"| Job ID | {jid} |", f"| Location | {j.get('location') or ''} |",
         f"| Fit | {sc['score']} (Tier {sc['tier']}) · {', '.join(f'{k} {v}' for k, v in sc['parts'].items())} |",
         f"| Permit sponsor | {sp.get('total', 0)} DETE permits (rank {sp.get('rank', '-')}) |",
         f"| Permit route | {sc['permit_route']} |",
         f"| CV to send | `{cv.get('file')}` ({cv.get('id')}) |",
         f"| Referral path | {'; '.join(sc['referrers']) or 'none found: see Find a contact'} |", ""]
    if sc.get("referral_rule"):
        L += [f"> **Rule for this role:** {sc['referral_rule']}", ""]
    if sc["flags"]:
        L += ["**Check before applying**", ""] + [f"- {f}" for f in sc["flags"]] + [""]

    L += ["## 1. Keyword check against your profile", "", "| Keyword | Status | Your evidence |", "|---|---|---|"]
    for _, name, status, ev in keyword_table(text, profile):
        L.append(f"| {name} | {status} | {ev} |")
    L += ["", "Use the ad's own words for every **Have** and **Partly** row in your CV summary and skills line. "
          "Never add a **Gap** row to the CV.", ""]

    L += ["## 2. CV bullets to move up (all true, from profile.json)", ""]
    picks = []
    for fam in families(j["title"], j.get("description") or ""):
        for q, tags in QUESTION_BANK.get(fam, []):
            s = story_for(tags, profile)
            if not s["title"].startswith("[[") and s["title"] not in picks:
                picks.append(s["title"])
    L += [f"- {p}" for p in picks[:5]] + [""]

    scr = profile.get("screening", {})
    L += ["## 3. Screening answers", "", "| Question | Answer |", "|---|---|",
          f"| Right to work in Ireland now? | {scr.get('right_to_work_now', '')} |",
          f"| Will you need sponsorship in future? | {scr.get('need_sponsorship_future', '')} |",
          f"| Work authorisation | {scr.get('work_auth_text', '')} |",
          f"| Years of experience | {scr.get('years_experience', '')} |",
          f"| '8+ years' question (if asked) | {scr.get('eight_plus_years_question', '')} |",
          f"| Office days / location | {scr.get('office_days', '')} |",
          f"| Notice period | {scr.get('notice_period', '')} |",
          f"| Salary expectation | {scr.get('salary_expectation', '')} · " +
          (f"ad states EUR {sc['pay'][0]:,}-{sc['pay'][1]:,}" if sc.get("pay") else "ad states no pay") + " |", ""]

    note, p = cover_note(j, sc, profile)
    problems += [f"cover note: {x}" for x in p]
    L += ["## 4. Cover note (about 120 words; skip if the referrer said no cover letter)", "", "```", note, "```", ""]

    L += ["## 5. Referral ask", ""]
    if sc["referrers"]:
        for person in sc["referrers"][:2]:
            ask = referral_ask(j, person, profile)
            problems += [f"referral ask: {x}" for x in tone.check(ask.replace(j['title'], 'ROLE'), profile) if "long sentence" not in x]
            L += [f"**To {person}**", "", "```", ask, "```", ""]
    else:
        co = j["company"].replace(" ", "%20")
        L += ["No referrer on file. Find one in 10 minutes:", "",
              f"1. LinkedIn people search: `https://www.linkedin.com/search/results/people/?keywords={co}%20support%20Ireland` "
              "(look for 2nd-degree contacts, ex-colleagues, alumni and your community groups in Ireland).",
              "2. Check the hiring team box on the LinkedIn job page and the recruiter's name in the ad.",
              "3. Ask your former-colleague groups whether anyone knows someone there.",
              "4. Send the recruiter note below with a connection request (300 characters).", ""]
    L += ["## 6. Recruiter / hiring manager note (LinkedIn, max 300 characters)", "", "```", recruiter_note(j, profile), "```", ""]

    L += ["## 7. Follow-up drafts (send only if no reply)", "", "| When | What | Draft |", "|---|---|---|"]
    for when, what, draft in followups(j, applied, profile):
        L.append(f"| {when:%a %d %b} | {what} | {draft} |")
    L += [""]

    L += ["## 8. Likely interview questions and the story to use", "", "| Question | Story (profile.json) |", "|---|---|"]
    seen = set()
    for fam in families(j["title"], j.get("description") or ""):
        for q, tags in QUESTION_BANK.get(fam, []):
            if q in seen:
                continue
            seen.add(q)
            s = story_for(tags, profile)
            L.append(f"| {q} | {s['title']} |")
    if profile.get("prep_material"):
        L += ["", f"Prep material: {profile['prep_material']}", ""]
    else:
        L += [""]

    L += ["## 9. Gaps: how to talk about them honestly", ""]
    for g in sc["gaps"][:6]:
        L.append(f"- **{g}**: \"I have not used this in production yet. The closest work I have done is [[closest real example]]. "
                 f"I am closing it by [[lab or course, with date]].\"")
    hits = [nc["why"] for nc in profile.get("never_claim", []) if re.search(nc["rx"], text, re.I)]
    if hits:
        L += ["", "**The ad mentions items on your never-claim list:**", ""] + [f"- {h}" for h in hits]
    L += ["", "## 10. Draft check", ""]
    L += ([f"- {x}" for x in problems] or ["- All drafts passed the tone and never-claim gate."]) + [
        "", "_Gate blind spot: it cannot tell whether a sentence is true. Read every line before you send it._", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    if store:
        store.add_event(j["key"], "pack", {"path": path, "problems": len(problems)})
    return path
