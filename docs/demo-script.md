# 90-second ProjectPulse demo

| Time | Action | What to say |
| --- | --- | --- |
| 0–15s | Open the E-commerce Platform dashboard. | “Agent sessions forget earlier engineering decisions. This project has its own Hindsight memory bank.” |
| 15–35s | Click **Seed demo data**. Open **Retain learning**, use the JWT example, and save as Agent A. | “Agent A records that refresh tokens use HTTP-only cookies and must never go in localStorage.” |
| 35–55s | Select **Agent B - fresh session** and keep the login/authentication task. Click **Ask ProjectPulse**. | “This is a new session with no prior chat. ProjectPulse recalls only task-relevant learning.” |
| 55–75s | Point to the evidence panel and its source agent/date. | “Hindsight returned the JWT decision before Groq answered.” |
| 75–90s | Compare the two answer cards and show the new timeline event. | “The memory-aware answer follows the cookie rule; the generic answer has no project decision to follow.” |

If time permits, ask an unrelated footer task and show zero selected memories. Create a second project and run the login task there to show that its empty bank cannot access E-commerce learning.

Before the demo, set the three required server-side environment variables, start PostgreSQL, run both apps, and confirm that the header says **Keys configured**. The label confirms configuration, while a successful Retain and Recall confirms provider connectivity.
