"""Paths, HTTP fetch, text normalisation and date helpers shared by every module."""
import datetime as dt
import html
import json
import os
import re
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config")
DATA = os.path.join(ROOT, "data")
PRIVATE = os.environ.get("JH_PRIVATE", os.path.join(ROOT, "private"))
STATE = os.environ.get("JH_STATE", os.path.join(ROOT, "state"))
OUT = os.environ.get("JH_OUT", os.path.join(ROOT, "out"))

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36",
      "Accept": "application/json, text/html", "Content-Type": "application/json"}


def load_json(path, default=None):
    if not os.path.exists(path):
        if default is not None:
            return default
        raise FileNotFoundError(path)
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def private_or_example(name):
    """private/<name> if present, else config/<name with .example>. Lets tests and new users run."""
    p = os.path.join(PRIVATE, name)
    if os.path.exists(p):
        return p
    stem, ext = os.path.splitext(name)
    return os.path.join(CONFIG, f"{stem}.example{ext}")


def fetch(url, data=None, raw=False, method=None, headers=None, timeout=30):
    body = None if data is None else (data if isinstance(data, bytes) else json.dumps(data).encode())
    req = urllib.request.Request(url, data=body, headers={**UA, **(headers or {})}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8", "replace")
    return text if raw else json.loads(text)


def strip_html(s, n=4000):
    s = re.sub(r"<[^>]+>", " ", html.unescape(s or ""))
    return re.sub(r"\s+", " ", s).strip()[:n]


SUFFIX = re.compile(r"\b(limited|ltd|unlimited|company|uc|dac|plc|designated activity|ireland|irish|europe|emea|"
                    r"international|operations|services|group|holdings|inc|llc|sa|se|co|the|branch|irl|"
                    r"technologies|technology|corporation|corp)\b", re.I)


def norm_company(s):
    s = re.sub(r"[^a-z0-9& ]", " ", (s or "").lower())
    s = s.replace("amazon web services", "amazon").replace("everpure", "pure storage")
    return re.sub(r"\s+", " ", SUFFIX.sub(" ", s)).strip()


def norm_title(s):
    s = re.sub(r"\(.*?\)", " ", (s or "").lower())
    s = re.sub(r"\b(\d+ openings?|dublin|cork|galway|limerick|ireland|emea|remote|hybrid)\b", " ", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def today():
    return dt.date.fromisoformat(os.environ["JH_TODAY"]) if os.environ.get("JH_TODAY") else dt.date.today()


def parse_date(v):
    """Best effort: ISO dates/datetimes, epoch ms, 'March 3, 2026', Workday 'Posted 5 Days Ago'."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return dt.datetime.fromtimestamp(v / 1000 if v > 1e11 else v, dt.timezone.utc).date()
    s = str(v).strip()
    m = re.search(r"Posted (Today|Yesterday|(\d+)\+? Days? Ago)", s, re.I)
    if m:
        word = m.group(1).lower()
        return today() - dt.timedelta(days=0 if word == "today" else 1 if word == "yesterday" else int(m.group(2)))
    m = re.search(r"(\d+)\s+(day|week|month)s?\s+ago", s, re.I)
    if m:
        mult = {"day": 1, "week": 7, "month": 30}[m.group(2).lower()]
        return today() - dt.timedelta(days=int(m.group(1)) * mult)
    m = re.match(r"(\d{4}-\d{2}-\d{2})", s)
    if m:
        return dt.date.fromisoformat(m.group(1))
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s)  # Irish dd/mm/yyyy
    if m:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def days_between(a, b=None):
    if a is None:
        return None
    return ((b or today()) - a).days
