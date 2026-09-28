# Demo script

Numbers in narration are whatever the live run measures — never pre-written.

## Setup (once)

1. `.env` has `HINDSIGHT_API_KEY` and `GROQ_API_KEY`; API and web are running.
2. Projects → **Launch the ApexCart demo**, then **Add LedgerLite (isolation)**. (Or `python scripts/seed.py --reset`.)

## Hero — 90 seconds

| Time | Screen | Action | Narration |
| --- | --- | --- | --- |
| 0:00 | Overview (ApexCart) | — | "AI coding agents start every session with amnesia. Last Tuesday our tech lead corrected one about auth. Today a different developer opens a fresh session. Will it know?" |
| 0:10 | Workspace → S-104 | **Extract memories** | "ProjectPulse read the session and found two decisions — each with the exact quote it came from — and threw away the chatter: the branch name, a laptop Node issue, a deferred NextAuth idea." |
| 0:22 | Inbox | `A`, `A` | "I approve; they're now in ApexCart's own Hindsight bank." |
| 0:30 | Compare | Hero task → **Run** | "Same model, same task, temperature 0. Left: no memory. Right: ProjectPulse recalls what applies." |
| 0:45 | Compare result | Point at both verdicts and the strip | "Left puts the token in localStorage and invents its own response format — violations of decisions this team already made. Right uses the `__Host-apx_rt` cookie and CSRF header from Tuesday's session, our envelope and login rate limit. Every rule links to where it came from." |
| 0:55 | Recall panel (right pane) | Expand **Filtered** | "It recalled more than it used. Webhook and pooling rules were filtered out, with reasons — memory is selective, not dumped." |
| 1:10 | Workspace | New session → "Add a dark-mode toggle to the header" | "A UI task gets the UI convention — and none of the auth rules." |
| 1:25 | Memory → Timeline | — | "One correction, captured once, applied and checked in every later session." |

## Extended (≈ 4 minutes)

1. **Supersession** — Workspace → S-131 *Checkout load test* → Extract. The Inbox shows a *supersedes* candidate side by side with the June `connection_limit=25` rule, and a *duplicate* of the singleton-db incident (approve → evidence added, nothing re-retained). Approve the replacement. Memory → Timeline shows the strike-through chain; Compare/Workspace with *"Checkout times out under load — how should I configure the database client?"* uses only the PgBouncer rule.
2. **Ask** — Check & Ask → *"Why don't we keep carts in Redis?"* → answer from the failed-approach record with Based-on pills.
3. **Rulebook history** — Overview → **What changed**: before/after diff of the Rulebook.
4. **Isolation** — switch to LedgerLite (top bar) and brief the same login task: LedgerLite's own sessionStorage rule, nothing from ApexCart. Settings → isolation violations blocked: **0**.
5. **Degradation** — Settings → *Force Hindsight offline*: red banner, memory-aware runs blocked with the reason, approvals queue as *Waiting to sync*, baseline still runs. Toggle back; the retry worker syncs the queue.
6. **Check** — Check & Ask → sample code → violations with excerpts, fixes and pattern evidence.
7. **Proof** — Settings → **Run eval**: precision / recall / forbidden-record rate on the labelled set, reported as measured.
