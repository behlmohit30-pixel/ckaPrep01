"""Fit score v3 (0-100) plus knock-outs, flags, category, permit route and CV choice.

Rubric (kept from v2, 9 Oct 2026, so old and new scores compare):
  role family 30 + CV evidence 20 + level 10 + permit-sponsor history 20 + referral path 10 + freshness 10.
v3 changes: evidence is weighted by the profile's own strong/medium/weak levels and drops when the ad's
requirements hit a weak skill; knock-outs (EU-only, Stamp 4, clearance, language) and flags (years asked,
salary below floor, caps, office days) are explicit. Tier A >= 75 needs permit history; B 60-74; C below 60.
This is a first pass. Claude reads the ad for every role >= 55 and adjusts with judgement.
"""
import re

from .util import parse_date, days_between, norm_company

FAM = [
    (30, r"technical support engineer|support engineer|technical services engineer|technical solutions engineer|"
         r"customer experience engineer|escalation engineer|designated (services|support) engineer|enterprise support|"
         r"customer success engineer|customer reliability engineer"),
    (25, r"cloud support|systems engineer|technical account manager|\bTAM\b|enterprise operations|production support|"
         r"application (it )?support|support specialist|support analyst|network operations engineer|escalations? manager|"
         r"incident (and escalation )?manager|major incident|service reliability|operations engineer|virtuali[sz]ation engineer|"
         r"support account manager|systems administrator|infrastructure (engineer|consultant)"),
    (16, r"site reliability|\bSRE\b|devops|platform engineer|cloud engineer|reliability|kubernetes"),
    (10, r"it support|desktop support|helpdesk|service desk|service engineer"),
    (6, r"."),
]
SYSOPS = re.compile(r"systems? (engineer|administrator)|sysadmin|infrastructure|virtuali[sz]|platform|site reliability|\bSRE\b|"
                    r"data ?cent(er|re)|cloud (engineer|operations)|operations engineer|devops|production (systems|operations)", re.I)
SUPPORT = re.compile(r"support|technical (services|solutions)|escalation|incident|customer (experience|success|reliability) engineer|"
                     r"designated|technical account manager", re.I)

KNOCKOUTS = [
    (r"\b(eu|eea) (citizen|national)s? only|must (be|hold) (an? )?(eu|eea|irish|uk) (citizen|passport)|irish citizenship required", "Requires EU/Irish citizenship"),
    (r"stamp 4 (required|only)|must (hold|have) (a )?stamp 4|no (visa|work permit|sponsorship) (sponsorship )?(is )?(available|offered|provided)|"
     r"(unable|not able) to (offer|provide) (visa )?sponsorship|without (the need for )?(visa |permit )?sponsorship", "No sponsorship / Stamp 4 only"),
    (r"security clearance|\bsc clearance\b|\bdv clearance\b|nato clearance|sovereign cloud|government vetting required", "Needs security clearance / sovereign residency"),
    (r"(fluent|native|business[- ]level|professional working proficiency)( level)?( in)? (german|french|spanish|italian|dutch|portuguese|polish|"
     r"japanese|korean|mandarin|arabic|turkish|hebrew|nordic|swedish|danish|norwegian|finnish)", "Needs a language besides English"),
]
GRADUATE = re.compile(r"\bgraduate\b|new grad|recent (graduate|bachelor)|0-2 years", re.I)
YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d+\s*)?years?(?:'|’)?\s+(?:of\s+)?(?:relevant\s+|professional\s+|hands-on\s+|industry\s+)?"
                   r"(?:experience|exp\b|in\b|working)", re.I)
AMOUNT = r"(\d{1,3}(?:[,.]\d{3})+(?:\.\d{2})?|\d{4,6}(?:\.\d{2})?|\d{2,3}(?:\.\d)?\s*k\b)"
SALARY = re.compile(rf"(?:€|\beur\s?)\s?{AMOUNT}(?:\s*(?:-|–|to)\s*(?:€|eur\s?)?\s?{AMOUNT})?", re.I)
SHIFT = re.compile(r"weekend|night shift|shift (work|pattern|rota)|24/7|on-?call|tuesday ?(-|to) ?saturday|sun(day)? ?(-|to) ?thu", re.I)
OFFICE = re.compile(r"(\d) days? (a|per) week in (the )?office|in-office|on-?site|hybrid", re.I)
CODING = re.compile(r"coding interview|software engineering foundation|production (code|coding)|\d\+? years? (of )?(software development|programming)", re.I)
SUPPORT_CODED = re.compile(r"support (engineer|specialist|analyst|representative)|service desk|help ?desk|it support|technical support", re.I)


def family_points(title):
    return next(p for p, rx in FAM if re.search(rx, title or "", re.I))


def level_points(t):
    if re.search(r"\b(staff|principal|lead|manager|director|head)\b", t, re.I) and not re.search(
            r"escalations? manager|incident (and escalation )?manager|technical account manager|support account manager", t, re.I):
        return 4
    if re.search(r"\b(associate|junior|graduate|entry)\b|\bI\b|\b1\b", t, re.I) and not re.search(r"engineer i\b.*(kubernetes|infrastructure)", t, re.I):
        return 5
    return 10


def sponsor_points(sp):
    if not sp:
        return 0
    n = sp["total"]
    return 20 if n >= 100 else 16 if n >= 30 else 12 if n >= 10 else 8 if n >= 3 else 5


def stated_salary(text):
    """Return (low, high) in EUR if the ad states pay, else None. Handles '€77,400.00 - €130,000.00',
    '€84000 - €86000' and 'EUR 86k-129k'."""
    def val(a):
        a = a.lower().replace(" ", "")
        if a.endswith("k"):
            return int(float(a[:-1]) * 1000)
        a = re.sub(r"\.\d{2}$", "", a)
        return int(re.sub(r"[,.]", "", a))
    for m in SALARY.finditer(text or ""):
        lo = val(m.group(1))
        hi = val(m.group(2)) if m.group(2) else lo
        if 20000 <= lo <= 400000:
            return lo, max(lo, hi)
    return None


def evidence(text, profile):
    """Match ad text against profile skills. Returns (points 0-20, have, partly, gaps)."""
    have, partly, gaps = [], [], []
    for s in profile.get("skills", []):
        if re.search(s["rx"], text, re.I):
            (have if s["level"] == "strong" else partly if s["level"] == "medium" else gaps).append(s["name"])
    if not text.strip():
        return 10, have, partly, gaps
    pts = 4 + 3 * len(have) + 2 * len(partly) - 2 * len(gaps)
    return max(0, min(20, pts)), have, partly, gaps


def knockout(text):
    for rx, why in KNOCKOUTS:
        if re.search(rx, text, re.I):
            return why
    return None


def permit_route(title, sponsor, pay, cfg):
    p = cfg.get("permit", {"csep_min_eur": 40904, "csep_graduate_eur": 36848, "csep_any_role_eur": 68911})
    any_role = p["csep_any_role_eur"]
    if pay and pay[0] >= any_role:
        return f"Pay EUR {pay[0]:,}+ is above EUR {any_role:,}: Critical Skills permit whatever the job code"
    if not sponsor:
        return "No DETE permit history found: ask the recruiter about sponsorship early"
    if SUPPORT_CODED.search(title) and not re.search(r"engineer", title, re.I):
        return f"Support-coded (likely 3132): Critical Skills needs EUR {any_role:,}+, else General permit"
    if SUPPORT_CODED.search(title):
        return (f"Support engineering: if coded 2139, Critical Skills from EUR {p['csep_min_eur']:,}; "
                f"if coded 3132, needs EUR {any_role:,}+ or General permit")
    return f"Engineering/ICT duties (likely 2133-2139): Critical Skills from EUR {p['csep_min_eur']:,} (graduate EUR {p['csep_graduate_eur']:,})"


def choose_cv(company, title, profile):
    for v in profile.get("cv_variants", []):
        if v.get("default"):
            continue
        if re.search(v.get("company_rx", "$^"), company or "", re.I) and re.search(v.get("title_rx", "."), title or "", re.I):
            return v
    return next((v for v in profile.get("cv_variants", []) if v.get("default")), {"id": "v4", "file": "(default CV)"})


def caps_hit(company, profile, applied_dates, today):
    """applied_dates: list of (company, date). Returns note if the next application would break a cap."""
    for c in profile.get("caps", []):
        if re.search(c["company_rx"], company or "", re.I):
            used = sum(1 for co, d in applied_dates if re.search(c["company_rx"], co, re.I) and (today - d).days <= c["days"])
            if used >= c["max"]:
                return f"CAP REACHED: {used}/{c['max']} applications in {c['days']} days at {company}"
            return f"Cap: {used}/{c['max']} used in last {c['days']} days ({c['note']})"
    return None


def referral_rule(company, title, profile):
    for r in profile.get("referral_rules", []):
        if re.search(r["company_rx"], company or "", re.I) and re.search(r["title_rx"], title or "", re.I):
            return r["rule"]
    return None


def referrers_for(company, referrers, connections=()):
    k = norm_company(company)
    out = []
    for co, people in referrers.items():
        ck = norm_company(co.split("(")[0])
        if ck and (ck == k or k.startswith(ck + " ") or ck.startswith(k + " ")):
            out += people
    out += [f"LinkedIn: {c['name']} ({c.get('position', '')})" for c in connections if norm_company(c.get("company")) == k and k]
    return out


def score(j, profile, cfg, referrers=None, connections=(), applied_dates=(), today=None):
    """Score one job dict (needs title, company, location, description, posted, sponsor, agency)."""
    import datetime as dt
    today = today or dt.date.today()
    t = re.sub(r"\benginer\b", "Engineer", j["title"], flags=re.I)  # real ad typo (Cohesity, 28 Oct 2026)
    text = f"{t} {j.get('description') or ''}"
    fam = family_points(t)
    ev, have, partly, gaps = evidence(text, profile)
    lvl = level_points(t)
    sp = sponsor_points(j.get("sponsor"))
    refs = referrers_for(j["company"], referrers or {}, connections)
    ref = 10 if refs else 0
    posted = parse_date(j.get("posted"))
    age = days_between(posted, today)
    fresh = 6 if age is None else 10 if age <= 3 else 7 if age <= 14 else 3
    if j.get("reposted"):
        fresh = min(10, fresh + 2)  # employer is still looking
    if j.get("agency"):
        fresh -= 3
    parts = {"family": fam, "evidence": ev, "level": lvl, "sponsor": sp, "referral": ref, "fresh": fresh}
    total = sum(parts.values())

    ko = knockout(text)
    flags = []
    yrs = [int(m.group(1)) for m in YEARS.finditer(j.get("description") or "") if 1 <= int(m.group(1)) <= 20]
    my = profile.get("years", {}).get("tech_support", 6)
    if yrs and max(yrs) > my:
        flags.append(f"Asks {max(yrs)}+ years (you have about {my:g} in technical support)")
    if GRADUATE.search(t) or re.search(r"recent (graduate|bachelor)", j.get("description") or "", re.I):
        flags.append("Graduate/early-career requisition: check eligibility")
    pay = stated_salary(j.get("description") or "")
    floor = profile.get("salary", {}).get("floor_eur")
    if pay:
        flags.append(f"Stated pay EUR {pay[0]:,}-{pay[1]:,}" + (f" (below your EUR {floor:,} floor)" if floor and pay[1] < floor else ""))
    if SHIFT.search(j.get("description") or ""):
        flags.append("Shift / weekend / on-call work mentioned")
    home = profile.get("home", "")
    if re.search(r"dublin", j.get("location") or "", re.I) and OFFICE.search(j.get("description") or "") and "dublin" not in home.lower():
        flags.append(f"Dublin office days: decide commute vs relocation (you live in {home or 'outside Dublin'})")
    if CODING.search(j.get("description") or ""):
        flags.append("Expect coding interviews / software-engineering bar")
    if j.get("location_needs_check"):
        flags.append("Multi-location ad: confirm an Irish office")
    if j.get("agency"):
        flags.append("Agency ad: ask the recruiter for the employer name and sponsorship")
    cap = caps_hit(j["company"], profile, applied_dates, today)
    if cap:
        flags.append(cap)
    rule = referral_rule(j["company"], t, profile)

    if ko:
        tier = "C"
    elif total >= 75 and sp > 0:
        tier = "A"
    elif total >= 60:
        tier = "B"
    elif not (j.get("description") or "").strip() and fam >= 25 and total >= 45:
        tier = "R"  # title-only pre-score for a core-family role: read the ad before screening it out
        flags.append("Title-only pre-score: read the ad, then `jh adjust`")
    else:
        tier = "C"
    if rule and tier in ("C", "R") and not ko:
        tier = "Manual"  # a live referral path is always shown to the candidate
    consult = re.compile(cfg.get("consultancies_rx", "$^"), re.I)
    sysops = bool(SYSOPS.search(t))
    support = bool(SUPPORT.search(t))
    category = "cat1-sysops" if sysops and not support else "cat3-product-support" if support and not consult.search(j["company"]) and not j.get("agency") else "cat2-other"
    must = bool(re.search(profile.get("scope", {}).get("must_include_rx", "$^"), j["company"] or "", re.I))
    return {
        "score": total, "parts": parts, "tier": tier, "knockout": ko, "flags": flags, "category": category, "must": must,
        "have": have, "partly": partly, "gaps": gaps, "referrers": refs, "referral_rule": rule,
        "permit_route": permit_route(t, j.get("sponsor"), pay, cfg), "cv": choose_cv(j["company"], t, profile),
        "pay": pay, "age_days": age,
    }
