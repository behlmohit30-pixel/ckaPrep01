# Playbook: job search and applications in Ireland (v3)

This is the process the pipeline runs. It starts from the common 6-step LinkedIn method (targets, alerts, tracker,
tailoring, referrals, weekly review) and adds the parts that method leaves out. No method is proven best for everyone.
This one covers every main channel and closes the feedback loop, so you can see which step is failing and fix it.

## 1. The whole process on one page

| Stage | What you do | What the pipeline does | Done when |
|---|---|---|---|
| 0. Position | Write one line: what you do, for whom, at what level. | `profile.json` holds the facts; every draft uses them. | You can say it in 15 seconds. |
| 1. Target | Pick role families, locations, must-haves, deal-breakers. | `config/sources.json` filters; knock-out rules in `score.py`. | Filters match what you would apply to. |
| 2. Find | Nothing daily. Read job-alert emails only if Claude is not running. | 127+ sources twice a day, LinkedIn guest search, alert emails, sponsors tagged. | New roles appear on the Today page. |
| 3. Decide | Approve or skip up to 5 roles a day, with a reason for skips. | Ranks by fit; flags years asked, pay, caps, office days, permits. | Nothing waits longer than 3 days. |
| 4. Prepare | Read the pack. Fix any `[[ ]]` gaps. Pick the CV. | Builds the pack: keywords, screening answers, cover note, referral ask. | Pack has no open placeholders. |
| 5. Referral first | Send the referral ask before you apply. Wait up to 4 days. | Finds referrers from your list and `Connections.csv`; reminds you to nudge. | Referral given, or 4 days passed. |
| 6. Apply | Apply on the employer's own site (not Easy Apply where you can avoid it). | Logs the application, the channel and the CV. | Logged with `jh applied`. |
| 7. Follow up | Send follow-up 1 at day 7 and follow-up 2 at day 14. Stop at day 21. | Puts each due follow-up on the Today page, with the draft. | Two follow-ups sent, or a reply. |
| 8. Interview | Prepare with the pack's questions and your STAR stories. Send a thank-you the same day. | Lists likely questions per role family; reminds you about the thank-you. | Thank-you sent; next step known. |
| 9. Outcome | Log offer, rejection or silence. | Ends the role; feeds the funnel numbers. | Every role has an end state. |
| 10. Review | 15 minutes on Sunday. | Targets vs done, funnel by channel, what to change. | One change chosen for next week. |

## 2. Weekly targets (edit in `profile.json`)

| Activity | Target | Why |
|---|---|---|
| Applications | 8 | Quality over volume. Eight tailored applications beat forty Easy Apply clicks. |
| Referral asks | 4 | A referred application usually gets read. A cold one often does not. |
| Follow-ups sent | as due (about 4) | Most people never follow up. It is cheap and it works. |
| Networking conversations | 2 | Many roles are filled from conversations before the ad goes up. |
| Agency contacts | 1 | Irish tech hiring uses agencies a lot (Cpl, Sigmar, Morgan McKinley, Hays, Collins McNicholas, Harvey Nash, Reperio, Stelfox). |
| Lab hours | 5 | Closes the gaps that keep coming up in ads. Log with `jh lab`. |

## 3. Channels, in order of value

| Channel | How to use it | Watch-out |
|---|---|---|
| Referral | Ask a contact at the company with the job ID and link. Use one referrer per role. | Respect each referrer's terms, e.g. "do not apply yourself". |
| Employer careers site | Apply there, not through LinkedIn Easy Apply, where you can. | Some employers cap applications (e.g. 3 in 30 days, 5 in 180 days). |
| Hiring manager / recruiter note | A 300-character LinkedIn note after you apply. | Never more than two follow-ups. |
| Agency | Send your CV to one tech recruiter a week. Ask them about sponsorship up front. | Ask which employer it is before you agree to be put forward. |
| LinkedIn job search and alerts | The pipeline reads the public guest search slowly, without logging in. | Search misses live jobs; check known employers directly. |
| Networking before posting | Meetups (Dublin, Cork, Limerick, Galway), alumni groups, ex-colleagues, community groups in Ireland. | Ask for advice, not a job. The job conversation follows. |

## 4. Work permits: what matters for Stamp 1G holders

- Stamp 1G lets you work full-time now. Before it ends, an employer must sponsor an employment permit.
- Employers that already sponsor permits are the main target. The pipeline ranks them by DETE permit counts.
  A count shows the employer sponsors permits. It is not a count of Critical Skills permits.
- Critical Skills Employment Permit (CSEP): roles on the Critical Skills list (most ICT engineering codes) from the
  lower salary threshold, or any role at or above the higher threshold. Support-coded roles (3132) usually need the
  higher threshold, or a General permit. Thresholds are in `config/sources.json`. Re-check them with DETE each January.
- Never answer "No" to "Will you need sponsorship in future?". It is a yes, and saying so early saves months.
- Knock-outs: EU citizenship only, Stamp 4 only, "no sponsorship", security clearance, sovereign-cloud residency.

## 5. Tailoring without lying

| Rule | Example |
|---|---|
| Use the ad's words for things you have done. | Ad says "CSI storage": you write "CNS/CSI storage faults", because you did them. |
| Never add a skill you cannot defend at interview. | Terraform stays off until a lab is done, then goes under "Home lab". |
| Describe support work as support work. | "Supported customers moving VM estates onto Kubernetes", not "Moved VM estates". |
| Scripts: say what you did. | "Ran and adapted Bash scripts", not "Automated". |
| Keep facts identical across CV versions. | Titles, dates, contacts and metrics never change between variants. |

## 6. Interviews and tests

- Five STAR stories cover most questions: a P1 you owned, a difficult customer, a time you did not know,
  a process you improved, leading or mentoring. The pack maps each likely question to a story.
- Technical rounds for support roles test how you troubleshoot. Talk through evidence first, then hypotheses, then fixes.
- Psychometric and video tests: practise one of each type before your first real one.
- Thank-you note the same day. Check in after 5 working days if you have not heard back.

## 7. Offers, rejections and pace

- **Offer:** ask for the permit type the employer will sponsor and when. Negotiate base pay, sign-on and start date.
  Most Irish ads do not state pay, so ask the recruiter for the band early.
- **Rejection:** log it, ask for one line of feedback, and keep the company on your list. Many re-apply within 6 months.
- **Pace:** fixed hours for the search (for example 08:00–09:00 and one evening slot), one day a week off it.
  A steady routine lasts longer than evenings of grinding.

## 8. Reading your funnel (the weekly review does this)

| Symptom | Likely cause | First fix |
|---|---|---|
| Few applications | Decisions pile up | Decide in one sitting, max 5 a day. |
| Under 10% replies after 10+ applications | CV or targeting | Referrals first, tailor the summary, drop roles under 65. |
| Replies but few interviews | Screening calls | Practise the 90-second intro, the permit answer and the salary answer. |
| Interviews but no offers | Interview stories | Rehearse STAR stories with numbers; do a mock interview. |

These thresholds are rules of thumb. Replace them with your own numbers after 4 to 6 weeks.
