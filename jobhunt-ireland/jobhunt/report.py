"""Today page and weekly review, as Markdown (for chat / Drive) and a phone-friendly HTML page."""
import html
import os

from .util import OUT, today


def _line(r):
    d = r.get("data") or {}
    gaps = ", ".join(d.get("gaps", [])[:2])
    return f"**{r['company']}** · {r['title']} · {r['score']} ({r['tier']}) · {r['location'][:30]}" + (f" · gaps: {gaps}" if gaps else "")


def today_md(ctx, acts, summary=None):
    t = today()
    L = [f"# Job hunt · today ({t:%a %d %b %Y})", ""]
    if summary:
        L += [f"Run: {summary['matching']} matching roles, {summary['new']} new (A {summary['tier_a']}, B {summary['tier_b']}, "
              f"screened {summary['screened']}). Sources OK {summary['sources_ok']}." + (f" Failed: {summary['failed']}." if summary['failed'] else ""), ""]
    L += [f"## 1. Decide ({len(acts['decide'])} of {acts['decide_total']} waiting, best first)", "",
          "Reply `approve` or `skip` with a reason. Approved roles get a pack.", ""]
    L += [f"{i}. {_line(r)}  \n   `{r['key']}` · {r['url']}" for i, r in enumerate(acts["decide"], 1)] or ["Nothing waiting."]
    L += ["", f"## 2. Apply ({len(acts['apply'])})", ""]
    for r in acts["apply"][:6]:
        rule = (r.get("data") or {}).get("referral_rule")
        L.append(f"- {_line(r)}" + (f"  \n  Rule: {rule}" if rule else ""))
    if not acts["apply"]:
        L.append("Nothing approved yet.")
    L += ["", "## 3. Follow up", ""]
    for r, who in acts["nudge"]:
        L.append(f"- Nudge **{who}** about {r['company']} · {r['title']}")
    for r, which, age in acts["follow"]:
        L.append(f"- {which}: {r['company']} · {r['title']} (applied {age} days ago). Draft is in the pack, section 7.")
    for r, age in acts["close"]:
        L.append(f"- {r['company']} · {r['title']}: {age} days, two follow-ups, no reply. Mark `ghosted` and move on.")
    for r, d in acts["thank"]:
        L.append(f"- Thank-you note today: {r['company']} · {r['title']} (interview {d:%d %b}).")
    if not (acts["nudge"] or acts["follow"] or acts["close"] or acts["thank"]):
        L.append("Nothing due.")
    if acts["read"]:
        L += ["", f"## 4. Read the ad first ({len(acts['read'])} title-only scores)", "",
              "Claude reads these on the next run and records `jh adjust`. Top ones:", ""]
        L += [f"- {r['company']} · {r['title']} · pre-score {r['score']} · {r['url']}" for r in acts["read"][:8]]
    if acts["watch"]:
        L += ["", "## 5. Must-include employers (below 60, for your awareness)", ""]
        L += [f"- {r['company']} · {r['title']} · {r['score']}" for r in acts["watch"][:10]]
    if acts["caps"]:
        L += ["", "## Caps", ""] + [f"- {c}" for c in acts["caps"]]
    return "\n".join(L) + "\n"


def week_md(wk):
    L = [f"# Weekly review · {wk['start']} to {wk['end']}", "", "## Targets", "", "| Activity | Done | Target |", "|---|---|---|"]
    for k, (done, tgt) in wk["targets"].items():
        L.append(f"| {k.replace('_', ' ')} | {done} | {tgt} |")
    L += ["", f"Found {wk['found']} new roles · approved {wk['approved']} · skipped {wk['skipped']} · replies {wk['replies']} · "
          f"interviews {wk['interviews']} · offers {wk['offers']}", "", "## Funnel (all time, by channel)", "",
          "| Channel | Applied | Replied | Interview | Offer |", "|---|---|---|---|---|"]
    for ch, f in sorted(wk["funnel_by_channel"].items()):
        L.append(f"| {ch} | {f['applied']} | {f['replied']} | {f['interview']} | {f['offer']} |")
    t = wk["funnel_total"]
    L.append(f"| **total** | {t['applied']} | {t['replied']} | {t['interview']} | {t['offer']} |")
    L += ["", "## What to change", ""] + [f"- {d}" for d in wk["diagnosis"]]
    return "\n".join(L) + "\n"


CSS = """
:root{--bg:#f7f7f5;--fg:#1d1d1b;--muted:#5f5e5a;--card:#fff;--line:#e3e2dc;--accent:#1f6f5c;--a:#d8efe5;--b:#fdf2d6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161615;--fg:#ecebe6;--muted:#a8a69f;--card:#21211f;--line:#34332f;--accent:#7fd1b6;--a:#1e3a31;--b:#3a321c}}
:root[data-theme=dark]{--bg:#161615;--fg:#ecebe6;--muted:#a8a69f;--card:#21211f;--line:#34332f;--accent:#7fd1b6;--a:#1e3a31;--b:#3a321c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}h1{font-size:1.4rem;margin:.2rem 0 1rem}h2{font-size:1.05rem;margin:1.6rem 0 .6rem;color:var(--accent)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px;margin:8px 0}
.meta{color:var(--muted);font-size:.9rem}.tier{display:inline-block;min-width:1.6em;text-align:center;border-radius:6px;padding:0 6px;font-weight:600}
.A{background:var(--a)}.B{background:var(--b)}a{color:var(--accent);word-break:break-all}code{font-size:.85rem;color:var(--muted)}
table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid var(--line);padding:6px 4px;text-align:left;font-size:.95rem}
"""


def today_html(ctx, acts, wk=None):
    e = html.escape
    t = today()
    parts = [f"<!doctype html><html lang=en><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
             f"<title>Job Hunt Today</title><style>{CSS}</style></head><body><main>",
             f"<h1>Job hunt · {t:%a %d %b %Y}</h1>",
             f"<h2>Decide · {len(acts['decide'])} of {acts['decide_total']} waiting</h2>"]
    for r in acts["decide"]:
        d = r.get("data") or {}
        flags = "".join(f"<li>{e(f)}</li>" for f in d.get("flags", [])[:4])
        parts.append(f"<div class=card><span class='tier {e(r['tier'])}'>{e(r['tier'])}</span> <b>{r['score']}</b> · "
                     f"<b>{e(r['company'])}</b> · {e(r['title'])}<div class=meta>{e(r['location'])} · {e(d.get('permit_route', ''))}</div>"
                     f"<div class=meta>Have: {e(', '.join(d.get('have', [])[:4]))} · Gaps: {e(', '.join(d.get('gaps', [])[:3]))}</div>"
                     f"{'<ul class=meta>' + flags + '</ul>' if flags else ''}<a href='{e(r['url'] or '')}'>{e(r['url'] or '')}</a> <code>{e(r['key'])}</code></div>")
    parts.append(f"<h2>Apply · {len(acts['apply'])}</h2>")
    for r in acts["apply"][:6]:
        parts.append(f"<div class=card><b>{e(r['company'])}</b> · {e(r['title'])} <span class=meta>({r['score']})</span><br>"
                     f"<a href='{e(r['url'] or '')}'>open ad</a></div>")
    due = [(f"Nudge {who}", r) for r, who in acts["nudge"]] + [(f"{w} ({a} d)", r) for r, w, a in acts["follow"]] + \
          [("Mark ghosted", r) for r, _ in acts["close"]] + [("Thank-you note", r) for r, _ in acts["thank"]]
    parts.append(f"<h2>Follow up · {len(due)}</h2>")
    parts += [f"<div class=card>{e(what)}: <b>{e(r['company'])}</b> · {e(r['title'])}</div>" for what, r in due] or ["<p class=meta>Nothing due.</p>"]
    if wk:
        parts.append("<h2>This week</h2><table><tr><th>Activity</th><th>Done</th><th>Target</th></tr>")
        parts += [f"<tr><td>{e(k.replace('_', ' '))}</td><td>{d}</td><td>{tg}</td></tr>" for k, (d, tg) in wk["targets"].items()]
        parts.append("</table>" + "".join(f"<p class=meta>{e(x)}</p>" for x in wk["diagnosis"]))
    parts.append("</main></body></html>")
    return "".join(parts)


def write(name, text):
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p
