"""Job sources. Every adapter returns a list of job dicts built by job(); one failing never stops a run.

Ported from v2 collector.py (9 Oct 2026, 127 sources all tested) and the 28 Oct LinkedIn guest sweep.
Adapters: greenhouse, ashby, lever, workday, smartrecruiters, amazon, eightfold (Microsoft and others),
google, jobs.ie, oracle_hcm, generic_json, generic_html, linkedin (guest search, no login), jobspy (optional).
"""
import concurrent.futures as cf
import datetime as dt
import html
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse

from .util import UA, fetch, load_json, norm_company, strip_html, CONFIG, today

KEYWORD_QUERIES = ["support", "engineer", "technical", "operations"]


class Filters:
    def __init__(self, cfg):
        self.t_inc = re.compile(cfg["title_include"], re.I)
        self.t_exc = re.compile(cfg["title_exclude"], re.I)
        self.l_inc = re.compile(cfg["location_include"], re.I)
        self.l_exc = re.compile(cfg["location_exclude"], re.I)

    def keep(self, title, loc, loc_check=False):
        if not self.t_inc.search(title or "") or self.t_exc.search(title or ""):
            return False
        if loc_check:
            return True
        return bool(self.l_inc.search(loc or "")) and not self.l_exc.search(loc or "")


def job(source, company, jid, title, loc, url, posted=None, desc="", loc_check=False, **extra):
    d = {"key": f"{source}:{jid}", "source": source, "company": (company or "").strip(), "title": (title or "").strip(),
         "location": (loc or "").strip(), "url": url, "posted": str(posted) if posted else None,
         "description": desc or "", "location_needs_check": loc_check}
    d.update(extra)
    return d


def dig(obj, path, join=True):
    """Follow a dot path through dicts/lists. join=True turns a final list into one string."""
    if not path:
        return obj
    for part in path.split("."):
        if isinstance(obj, list):
            obj = obj[int(part)] if part.isdigit() and int(part) < len(obj) else [dig(o, part, join) for o in obj]
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    if join and isinstance(obj, list):
        return "; ".join(str(x) for x in obj if x)
    return obj


class Collector:
    def __init__(self, cfg, fetcher=fetch, sleep=time.sleep):
        self.cfg = cfg
        self.f = Filters(cfg)
        self.fetch = fetcher
        self.sleep = sleep

    # ---------- fixed ATS sources ----------
    def greenhouse(self, slug, name):
        out = []
        for j in self.fetch(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")["jobs"]:
            loc = j["location"]["name"]
            if re.fullmatch(r"\s*(remote|hybrid|multiple locations?|emea|europe)?\s*", loc, re.I):
                loc += " " + " ".join(o.get("name", "") for o in j.get("offices", []))
            if self.f.keep(j["title"], loc):
                out.append(job("greenhouse", name, f"{slug}-{j['id']}", j["title"], j["location"]["name"],
                               j["absolute_url"], j.get("updated_at"), strip_html(j.get("content"))))
        return out

    def ashby(self, slug, name):
        out = []
        for j in self.fetch(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")["jobs"]:
            loc = (j.get("location") or "") + " " + " ".join(s.get("location", "") for s in j.get("secondaryLocations") or [])
            if self.f.keep(j["title"], loc):
                out.append(job("ashby", name, f"{slug}-{j['id']}", j["title"], loc.strip(), j["jobUrl"],
                               j.get("publishedAt"), (j.get("descriptionPlain") or "")[:4000]))
        return out

    def lever(self, slug, name, host="api.lever.co"):
        out = []
        for j in self.fetch(f"https://{host}/v0/postings/{slug}?mode=json"):
            cats = j.get("categories") or {}
            loc = cats.get("location", "") + " " + " ".join(cats.get("allLocations") or [])
            if self.f.keep(j["text"], loc):
                out.append(job("lever", name, f"{slug}-{j['id']}", j["text"], cats.get("location", ""), j["hostedUrl"],
                               j.get("createdAt"), (j.get("descriptionPlain") or "")[:4000]))
        return out

    def workday(self, host, tenant, site, name):
        found = {}
        for q in self.cfg["workday_queries"]:
            d = self.fetch(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                           {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": f"{q} Ireland"})
            for j in d.get("jobPostings", []):
                loc = j.get("locationsText", "")
                multi = bool(re.match(r"\d+ Locations", loc))
                if self.f.keep(j["title"], loc, loc_check=multi):
                    path = j["externalPath"]
                    found[path] = job("workday", name, f"{tenant}-{path.rsplit('_', 1)[-1]}", j["title"], loc,
                                      f"https://{host}/en-US/{site}{path}", j.get("postedOn"), "", multi)
        return list(found.values())

    def smartrecruiters(self, cid, name):
        d = self.fetch(f"https://api.smartrecruiters.com/v1/companies/{cid}/postings?country=ie&limit=100")
        out = []
        for j in d.get("content", []):
            loc = ", ".join(filter(None, [j["location"].get("city"), j["location"].get("country")]))
            if self.f.keep(j["name"], loc + " ireland"):
                out.append(job("smartrecruiters", name, f"{cid}-{j['id']}", j["name"], loc,
                               f"https://jobs.smartrecruiters.com/{cid}/{j['id']}", j.get("releasedDate")))
        return out

    def amazon(self):
        found = {}
        for q in self.cfg["amazon_queries"]:
            d = self.fetch("https://www.amazon.jobs/en/search.json?" + urllib.parse.urlencode(
                {"base_query": q, "loc_query": "Ireland", "country": "IRL", "result_limit": 50}))
            for j in d.get("jobs", []):
                loc = j.get("normalized_location", "")
                if self.f.keep(j["title"], loc):
                    found[j["id_icims"]] = job("amazon", "Amazon / AWS", j["id_icims"], j["title"], loc,
                                               "https://www.amazon.jobs" + j["job_path"], j.get("posted_date"),
                                               strip_html(j.get("description", "") + " " + j.get("basic_qualifications", "")))
        return list(found.values())

    def eightfold_pcsx(self, search_url, name, job_url_prefix, queries):
        found = {}
        for q in queries:
            url = search_url.replace("{q}", urllib.parse.quote(q))
            for attempt in range(3):  # Eightfold rate-limits bursts (HTTP 429)
                self.sleep(3 + 5 * attempt)
                try:
                    d = self.fetch(url)
                    break
                except urllib.error.HTTPError as e:
                    if e.code != 429 or attempt == 2:
                        raise
            for j in (d.get("data") or d).get("positions", []):
                loc = "; ".join(j.get("locations") or [j.get("location") or ""])
                if self.f.keep(j.get("name"), loc):
                    posted = dt.datetime.fromtimestamp(j["postedTs"], dt.timezone.utc).date().isoformat() if j.get("postedTs") else None
                    path = j.get("positionUrl") or j.get("canonicalPositionUrl") or f"/careers/job/{j['id']}"
                    link = path if path.startswith("http") else job_url_prefix.rstrip("/") + path
                    found[j["id"]] = job("eightfold", name, j.get("displayJobId") or j["id"], j["name"], loc, link, posted)
        return list(found.values())

    def microsoft(self):
        return self.eightfold_pcsx("https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query={q}&location=Ireland&start=0&num=20",
                                   "Microsoft", "https://apply.careers.microsoft.com", self.cfg["microsoft_queries"])

    def google(self):
        found = {}
        for q in self.cfg["google_queries"]:
            page = self.fetch("https://www.google.com/about/careers/applications/jobs/results/?" + urllib.parse.urlencode(
                {"location": "Ireland", "q": q}), raw=True)
            for jid, slug in re.findall(r"jobs/results/(\d{6,})-([a-z0-9-]+)", page):
                title = slug.replace("-", " ").title()
                if self.f.keep(title, "Ireland"):
                    found[jid] = job("google", "Google", jid, title, "Ireland (check office)",
                                     f"https://www.google.com/about/careers/applications/jobs/results/{jid}-{slug}")
        return list(found.values())

    def jobsie(self):
        found = {}
        for s in self.cfg["jobsie_searches"]:
            page = self.fetch(f"https://www.jobs.ie/jobs/{s}/in-ireland?sort=2", raw=True)
            for tslug, cslug, jid in re.findall(r'href="/job/([a-z0-9-]+)/([a-z0-9-]+)-job(\d+)"', page):
                title = tslug.replace("-", " ").title()
                if self.f.keep(title, "Ireland"):
                    found[jid] = job("jobs.ie", cslug.replace("-", " ").title(), jid, title, "Ireland (see ad)",
                                     f"https://www.jobs.ie/job/{tslug}/{cslug}-job{jid}")
        return list(found.values())

    # ---------- LinkedIn guest search (no login, read-only, slow) ----------
    LI_CARD = re.compile(r'data-entity-urn="urn:li:jobPosting:(?P<id>\d+)".*?base-search-card__title[^>]*>(?P<title>.*?)</h3>'
                         r'.*?base-search-card__subtitle[^>]*>(?P<company>.*?)</h4>.*?job-search-card__location[^>]*>(?P<loc>.*?)</span>'
                         r'(?P<rest>.*?)</li>', re.S)

    def linkedin(self):
        """Search cards from LinkedIn's public guest endpoint. 10 cards a page, 2.5 s a page, backoff on 429.
        LinkedIn job IDs survive reposts, so an ID much older than its listed date means a repost."""
        lc = self.cfg.get("linkedin", {})
        found = {}
        for q in lc.get("queries", []):
            for start in range(0, 10 * lc.get("pages", 2), 10):
                params = {"keywords": q, "location": "Ireland", "geoId": "104738515",
                          "f_TPR": f"r{86400 * lc.get('days', 7)}", "start": start}
                url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" + urllib.parse.urlencode(params)
                page = None
                for attempt in range(4):
                    self.sleep(lc.get("delay_s", 2.5) * (1 + 2 * attempt))
                    try:
                        page = self.fetch(url, raw=True)
                        break
                    except urllib.error.HTTPError as e:
                        if e.code != 429 or attempt == 3:
                            raise
                cards = list(self.LI_CARD.finditer(page or ""))
                for m in cards:
                    title = strip_html(m["title"])
                    company = strip_html(m["company"])
                    loc = strip_html(m["loc"])
                    t = re.search(r'<time[^>]*datetime="([\d-]+)"', m["rest"])
                    if self.f.keep(title, loc):
                        found[m["id"]] = job("linkedin", company, m["id"], title, loc,
                                             f"https://ie.linkedin.com/jobs/view/{m['id']}", t.group(1) if t else None,
                                             "", li_id=int(m["id"]))
                if len(cards) < 10:
                    break
        return list(found.values())

    # ---------- optional JobSpy (Indeed / Glassdoor), only if installed ----------
    def jobspy(self):
        try:
            from jobspy import scrape_jobs  # pip install python-jobspy (in a venv)
        except ImportError:
            return []
        jc = self.cfg.get("jobspy", {})
        out = []
        for q in jc.get("queries", []):
            df = scrape_jobs(site_name=jc.get("sites", ["indeed"]), search_term=q, location="Ireland",
                             country_indeed="Ireland", hours_old=24 * jc.get("days", 7), results_wanted=jc.get("results", 40))
            for r in df.to_dict("records"):
                loc = str(r.get("location") or "")
                if self.f.keep(str(r.get("title")), loc + " ireland"):
                    out.append(job(f"jobspy-{r.get('site')}", r.get("company"), r.get("id"), r.get("title"), loc,
                                   r.get("job_url"), r.get("date_posted"), str(r.get("description") or "")[:4000]))
        return out

    # ---------- generic feeds for permit sponsors (config "feeds") ----------
    def oracle_hcm(self, p, name):
        found = {}
        for q in KEYWORD_QUERIES:
            loc = f",locationId={p['location_id']}" if p.get("location_id") else ""
            url = (f"https://{p['host']}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
                   f"&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={p['site']},facetsList=LOCATIONS,"
                   f"limit=50,keyword=%22{urllib.parse.quote(q)}%22{loc},sortBy=POSTING_DATES_DESC")
            for item in self.fetch(url).get("items", []):
                for j in item.get("requisitionList", []):
                    where = j.get("PrimaryLocation", "") + " " + " ".join(s.get("Name", "") for s in j.get("secondaryLocations") or [])
                    if self.f.keep(j.get("Title"), where):
                        found[j["Id"]] = job("oracle", name, j["Id"], j["Title"], j.get("PrimaryLocation", ""),
                                             f"https://{p['host']}/hcmUI/CandidateExperience/en/sites/{p['site']}/job/{j['Id']}",
                                             j.get("PostedDate"))
        return list(found.values())

    def generic_json(self, p, name):
        found = {}
        templated = "{q}" in p["url"] or "{q}" in (p.get("body") or "")
        for q in (KEYWORD_QUERIES if templated else [None]):
            url = p["url"].replace("{q}", urllib.parse.quote(q or ""))
            body = p.get("body")
            if body:
                body = body.replace("{q}", q or "").encode()
            if p.get("use_curl"):  # some sites block Python's TLS fingerprint but allow curl
                curl = r"C:\Windows\System32\curl.exe" if os.path.exists(r"C:\Windows\System32\curl.exe") else "curl"
                res = subprocess.run([curl, "-s", "-L", "--max-time", "30", "-A", UA["User-Agent"], "-H", "Accept: application/json", url],
                                     capture_output=True, timeout=40)
                import json as _j
                d = _j.loads(res.stdout.decode("utf-8", "replace"))
            else:
                d = self.fetch(url, data=body, method=p.get("method", "GET"), headers=p.get("headers"))
            items = dig(d, p["list_path"], join=False) if p.get("list_path") else d
            if not isinstance(items, list):
                continue
            pre_filtered = p.get("ireland_filtered") or re.search(r"(country|location)=Ireland", p["url"], re.I)
            for it in items:
                title, jid = dig(it, p["title"]), dig(it, p["id"])
                loc = dig(it, p["location"]) if p.get("location") else ""
                loc = loc if isinstance(loc, str) else ""
                if not loc and pre_filtered:
                    loc = "Ireland"
                if jid is None or not self.f.keep(str(title), str(loc), loc_check=bool(pre_filtered)):
                    continue
                link = dig(it, p["url_field"]) if p.get("url_field") else p.get("url_template", "").replace("{id}", str(jid))
                found[str(jid)] = job("feed", name, f"{norm_company(name).replace(' ', '')}-{jid}", str(title), str(loc), link)
        return list(found.values())

    def generic_html(self, p, name):
        found = {}
        templated = "{q}" in p["url"]
        rx = re.compile(p["item_regex"], re.S)
        for q in (KEYWORD_QUERIES if templated else [None]):
            page = self.fetch(p["url"].replace("{q}", urllib.parse.quote(q or "")), raw=True)
            for m in rx.finditer(page):
                g = m.groupdict()
                title = html.unescape(re.sub(r"<[^>]+>", " ", g.get("title") or "")).strip()
                loc = g.get("location") or "Ireland (page is Ireland-filtered)"
                if not self.f.keep(title, loc):
                    continue
                jid = g.get("id") or g.get("path")
                link = p.get("url_template", "").replace("{id}", g.get("id") or "").replace("{path}", g.get("path") or "")
                found[jid] = job("feed", name, f"{norm_company(name).replace(' ', '')}-{jid}", title, loc, link)
        return list(found.values())

    def feed(self, entry):
        a, p, name = entry["adapter"], entry["params"], entry["brand"]
        if a == "greenhouse":
            return self.greenhouse(p["slug"], name)
        if a == "ashby":
            return self.ashby(p["slug"], name)
        if a in ("lever", "lever_eu"):
            return self.lever(p["slug"], name, "api.eu.lever.co" if a == "lever_eu" else "api.lever.co")
        if a == "workday":
            return self.workday(p["host"], p["tenant"], p["site"], name)
        if a == "smartrecruiters":
            return self.smartrecruiters(p["company"], name)
        if a == "eightfold":
            return self.eightfold_pcsx(p["search_url"], name, p.get("job_url_prefix", ""), KEYWORD_QUERIES)
        if a == "oracle_hcm":
            return self.oracle_hcm(p, name)
        if a == "generic_json":
            return self.generic_json(p, name)
        if a == "generic_html":
            return self.generic_html(p, name)
        return []

    def tasks(self, only=None):
        c = self.cfg
        t = [(f"greenhouse:{s}", self.greenhouse, (s, n)) for s, n in c.get("greenhouse", {}).items()]
        t += [(f"ashby:{s}", self.ashby, (s, n)) for s, n in c.get("ashby", {}).items()]
        t += [(f"lever:{s}", self.lever, (s, n)) for s, n in c.get("lever", {}).items()]
        t += [(f"workday:{w[1]}", self.workday, tuple(w)) for w in c.get("workday", [])]
        t += [(f"smartrecruiters:{s}", self.smartrecruiters, (s, n)) for s, n in c.get("smartrecruiters", {}).items()]
        t += [("amazon", self.amazon, ()), ("microsoft", self.microsoft, ()), ("google", self.google, ()), ("jobs.ie", self.jobsie, ())]
        t += [(f"feed:{e['brand']}", self.feed, (e,)) for e in c.get("feeds", []) if e.get("enabled", True) and e["adapter"] != "none"]
        if c.get("linkedin", {}).get("enabled"):
            t.append(("linkedin", self.linkedin, ()))
        if c.get("jobspy", {}).get("enabled"):
            t.append(("jobspy", self.jobspy, ()))
        if only:
            rx = re.compile(only, re.I)
            t = [x for x in t if rx.search(x[0])]
        return t

    def run(self, only=None, workers=10):
        """Returns (jobs, health). LinkedIn runs alone after the pool so its pacing is not disturbed."""
        health, jobs = {}, []

        def one(t):
            label, fn, args = t
            try:
                return label, fn(*args), None
            except Exception as e:  # one source failing must not stop the run
                return label, [], f"{type(e).__name__}: {str(e)[:160]}"

        ts = self.tasks(only)
        pooled = [t for t in ts if t[0] != "linkedin"]
        serial = [t for t in ts if t[0] == "linkedin"]
        with cf.ThreadPoolExecutor(workers) as ex:
            results = list(ex.map(one, pooled))
        results += [one(t) for t in serial]
        for label, res, err in results:
            health[label] = {"ok": err is None, "matches": len(res), "error": err}
            jobs += res
        return jobs, health


def load_sources_config(path=None):
    return load_json(path or os.path.join(CONFIG, "sources.json"))


def hosts(cfg):
    """Every host a full run contacts: paste into a cloud environment's allowed-domains list."""
    hs = {"boards-api.greenhouse.io", "api.ashbyhq.com", "api.lever.co", "api.eu.lever.co", "api.smartrecruiters.com",
          "www.amazon.jobs", "apply.careers.microsoft.com", "www.google.com", "www.jobs.ie", "www.linkedin.com"}
    hs |= {w[0] for w in cfg.get("workday", [])}
    for e in cfg.get("feeds", []):
        p = e.get("params", {})
        for k in ("host", "url", "search_url"):
            if p.get(k):
                v = p[k]
                hs.add(urllib.parse.urlparse(v).netloc if "://" in v else v)
    return sorted(h for h in hs if h)


def linkedin_repost_info(li_id, listed, anchor=(4484210000, dt.date(2026, 10, 27)), per_day=374000):
    """Estimate first-post date from a LinkedIn job ID. Calibrated 28 Oct 2026: IDs rise ~374k/day.
    A role whose ID implies a first post 10+ days before its listed date was reposted (employer still looking)."""
    if not li_id:
        return None
    first = anchor[1] + dt.timedelta(days=round((int(li_id) - anchor[0]) / per_day))
    gap = (listed - first).days if listed else None
    return {"implied_first_post": first.isoformat(), "repost_gap_days": gap, "reposted": bool(gap is not None and gap >= 10)}
