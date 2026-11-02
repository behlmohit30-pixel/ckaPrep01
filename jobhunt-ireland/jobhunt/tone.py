"""Writing gate for everything the pipeline drafts (cover notes, referral asks, follow-ups).

Banned list = the candidate's own corpus-doc-build gate (plain, direct technical English).
Also checks: never-claim facts from profile.json, US spellings (he writes Irish/British English),
sentences over 25 words, and unfilled [[placeholders]].
Blind spot: it cannot judge whether a true-sounding sentence is actually true. The candidate reads every draft.
"""
import re

BANNED = ["delve", "leverage", "robust", "seamless", "crucial", "pivotal", "landscape", "realm", "tapestry",
          "underscore", "showcase", "foster", "it is important to note", "in conclusion", "passionate",
          "thrilled", "cutting-edge", "game-changer", "synergy", "dynamic team", "excited to apply"]
NOT_ONLY = re.compile(r"\bnot only\b.{1,80}\bbut also\b", re.I | re.S)
US_UK = {"optimize": "optimise", "organization": "organisation", "analyze": "analyse", "prioritize": "prioritise",
         "utilize": "use", "color": "colour", "behavior": "behaviour", "center": "centre", "license": "licence",
         "virtualization": "virtualisation", "specialize": "specialise", "recognize": "recognise", "program ": "programme "}


def check(text, profile=None, max_words=25):
    """Return a list of problems (empty = pass). Job titles quoted from an ad may keep US spelling:
    pass the draft without the quoted title, or accept that one flag knowingly."""
    problems = []
    low = text.lower()
    for w in BANNED:
        if re.search(rf"\b{re.escape(w)}\w*\b", low):
            problems.append(f"banned phrase: '{w}'")
    if NOT_ONLY.search(text):
        problems.append("banned pattern: 'not only ... but also'")
    for us, uk in US_UK.items():
        if re.search(rf"\b{us}", low):
            problems.append(f"US spelling '{us.strip()}' -> '{uk.strip()}'")
    for s in re.split(r"(?<=[.!?])\s+", text):
        n = len(re.findall(r"\b\w+\b", s))
        if n > max_words:
            problems.append(f"long sentence ({n} words): '{s[:60]}...'")
    if "[[" in text:
        problems.append("unfilled [[placeholder]]")
    for nc in (profile or {}).get("never_claim", []):
        if re.search(nc["rx"], text, re.I):
            problems.append(f"never-claim: {nc['why']}")
    return problems
