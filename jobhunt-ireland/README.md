# jobhunt-ireland (v3)

A job-search and application pipeline for technical support, infrastructure and SRE roles in the Republic of Ireland,
built around Critical Skills permit sponsors. It finds roles, scores them against a truthful profile, and tells you
what to do each day. It also drafts every application pack, tracks each application to an outcome, and runs a weekly review.

It never applies, sends or connects for you. It drafts; you decide and send.

```
collect ──> score ──> decide ──> pack ──> apply ──> follow up ──> interview ──> outcome
  127+ sources   rubric +     you, 20 min   drafts     you log it   drafts, due   stages     weekly funnel
  + LinkedIn     knock-outs   a day                                  dates                     review
```

## What is in it

| Part | File | What it does |
|---|---|---|
| Sources | `jobhunt/sources.py` | Greenhouse, Ashby, Lever, Workday, SmartRecruiters, Amazon, Microsoft, Google, jobs.ie, 79 permit-sponsor career sites, LinkedIn guest search (no login), optional JobSpy. One failing source never stops a run. |
| Sponsors | `data/sponsors.json` | DETE employment permits issued to 155 employer brands (2025 + Jan–Sep 2026). |
| Score | `jobhunt/score.py` | 0–100: role family 30, CV evidence 20, level 10, sponsor 20, referral 10, freshness 10. Knock-outs, flags, permit route, CV choice, caps. |
| Store | `jobhunt/store.py` | SQLite. Jobs plus an event log (decisions, applications, referrals, follow-ups, stages). Duplicates across sources are merged. |
| Packs | `jobhunt/packs.py` | Keyword check, CV to send, screening answers, cover note, referral ask, recruiter note, follow-ups, interview questions, honest gap lines. |
| Tone gate | `jobhunt/tone.py` | Banned phrases, US spellings, long sentences, placeholders, never-claim facts. |
| Queue + review | `jobhunt/pipeline.py` | Today's actions, weekly targets, funnel by channel, diagnosis, Google Sheet sync. |
| CLI | `jh.py` | Every command below. |

## Set up (Windows or WSL, Python 3.10+, no pip needed)

```bash
git clone -b ccr-fc55cfa2-ngy9q8 https://github.com/behlmohit30-pixel/ckaPrep01.git
cd ckaPrep01/jobhunt-ireland
mkdir private
copy config\profile.example.json private\profile.json      # then replace every value with your own facts
copy config\referrers.example.json private\referrers.json
python -I -m unittest discover -s tests                    # 14 offline tests
```

`private/`, `state/` and `out/` are git-ignored. Your facts, contacts and history never go into the repository.
Optional: put LinkedIn's data export `Connections.csv` in `private/` to find referral paths automatically.

## Daily use (about 20 minutes)

```bash
python -I jh.py collect                          # fetch, score, write out/today.md and out/today.html
python -I jh.py today                            # what to do now
python -I jh.py decide "stripe support" approve  # approving builds the pack in out/packs/
python -I jh.py decide 4476361164 skip --reason "night shifts"
python -I jh.py referral 4475988763 asked --who "Sam"
python -I jh.py applied 4475988763 --via referral
python -I jh.py followup 4475988763              # after you send the follow-up the pack drafted
python -I jh.py stage 4475988763 interview --date 2026-11-12
python -I jh.py week                             # Sundays: targets, funnel, what to change
```

Other commands: `ingest` (job-alert emails as JSON), `import-sweep` (LinkedIn sweep file), `add` (one role by hand),
`adjust` / `adjust-file` (judged score after reading the ad), `rescore`, `show`, `note`, `contact`, `lab`,
`sheet-export` / `sheet-import` (Google Sheet tracker), `hosts` (allowed-domains list for a cloud run).

## How the score works, and its limits

60 points come from judgement (family, evidence, level) and 40 from data (sponsor, referral, freshness). It is a rubric,
not a model trained on outcomes. Treat it as a sorting aid until your own funnel numbers exist. A role scored only
from its title is tier **R** (read the ad first), never auto-rejected. Tier A needs permit-sponsor history.

See `PLAYBOOK.md` for the full process and `RUNBOOK.md` for scheduled runs by Claude.
