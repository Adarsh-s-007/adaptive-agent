# Your submission kit (article + social post)

The video is handled by your teammate (they can use `docs/demo-script.md`). You do **Part 1 (article)** and **Part 2 (LinkedIn post)**. Never write the word "hackathon" anywhere — title, body, hashtags or comments.

---

## Step 1 — Title (Prompt 1)

**Chosen:** `I Built Code Review for My Agents' Memory With Hindsight`

All 20 candidates, if you want to swap:

```
I Built Code Review for My Agents' Memory With Hindsight
Recall Isn't Compliance: Checking Agent Output Against Hindsight Memory
Why My Agent Memory Needs Approval Before Hindsight Stores It
Hindsight Remembered the Rule. My Agent Still Broke It.
How I Stopped Agents Re-Proposing Rejected Decisions Using Hindsight
I Made Hallucinated Agent Memory Impossible With One Hindsight Rule
What I Learned Versioning Agent Memory Like Code on Hindsight
Supersede, Don't Delete: Evolving Team Decisions in Hindsight
How I Keep One Agent's Correction Alive With Hindsight
I Gave Every Project Its Own Hindsight Memory Bank
My Agents Now Cite the Decision They Followed, via Hindsight
Designing a Review Inbox for Hindsight Agent Memory
Why I Inject Five Rules, Not Five Hundred, With Hindsight
How I Built Blind Memory Checks on Top of Hindsight
Turning Chat Transcripts Into Reviewed Hindsight Memory
The Dark-Mode Test: Proving Hindsight Recall Stays Relevant
How a Verbatim-Quote Check Saved My Hindsight Memory Bank
Building a Project Rulebook From Hindsight Mental Models
I Measured My Agent With and Without Hindsight Memory
What Broke When My Agents Shared Hindsight Memory Across Sessions
```

## Step 2 — Article

- File: **`article.md`** (repo root). ~1,900 words of prose, 5 real code snippets, first person, the 3 required links embedded, zero mentions of "hackathon".
- **Before you publish, read it once and change anything that doesn't sound like you** (the guide asks for your voice).
- The three links are already in the text with natural anchor text:
  - https://github.com/vectorize-io/hindsight
  - https://hindsight.vectorize.io/
  - https://vectorize.io/what-is-agent-memory

## Publishing on Dev.to (pictures already placed)

Use **`docs/article/article.devto.md`**, not `article.md`. It has the Dev.to header (title, tags, cover image) and every picture already in position, loaded from GitHub:
`https://raw.githubusercontent.com/Adarsh-s-007/adaptive-agent/dev/docs/article/images/<file>.png`

1. Push the images to GitHub on **main** (the repo must be public). If you push them on another branch instead, find-replace `/main/` with `/<branch>/` in the file.
2. Open one image URL in your browser to confirm it loads.
3. Dev.to → **Create Post** → the ⋯ / settings menu → **Basic markdown** editor.
4. Paste the **entire** contents of `article.devto.md` (including the `---` header).
5. Click **Preview** and scroll through: 10 pictures, captions under each, code blocks, links.
6. Change `published: false` to `published: true` (or click Publish).

No-GitHub fallback: in the Dev.to editor use the image-upload button for each picture; it gives you a link. Replace the matching `raw.githubusercontent.com/...` link with it.

## Step 3 — Images (all real, from the running app)

Upload these where the article references them (`docs/article/images/…`). On Medium/Dev.to you upload each image at that spot — relative paths won't work there.

| File | Where in the article | Caption |
| --- | --- | --- |
| `00-memory-loop.png` | after the intro | The ProjectPulse memory loop |
| `00-architecture.png` | "What the system does" | Where Hindsight sits in the stack |
| `04-inbox-candidates.png` | Gate 1 | Two candidates with verbatim evidence, plus the filtered row |
| `05-inbox-supersedes.png` | Gate 3 | The extractor suggests a supersession, side by side with the old rule |
| `06-recall-hero.png` | Brief | Recall panel: recalled, applied with reasons, filtered with reasons |
| `07-recall-darkmode.png` | Brief | A UI task gets the UI convention and nothing else |
| `12-check-before.png` | Recall isn't compliance | Memory Check on code written without project memory |
| `13-check-after.png` | Recall isn't compliance | The same check on code written with the brief |
| `14-ask.png` | The rest of Hindsight | Ask the project: a reflect answer grounded in the failed-approach record |

Extra shots you can use as the cover image or in the Reddit/LinkedIn post: `01-projects.png` (good cover), `02-overview-rulebook.png`, `03-workspace-extraction.png`, `08-timeline.png`, `09-record-drawer.png`, `10-constellation.png`, `11-library.png`, `15-isolation-ledgerlite.png`, `16-rulebook-what-changed.png`, `17-settings-eval-audit.png`.

Optional: a team photo (the guide says it adds personality).

## Step 4 — Publish the article

1. Pick one: **Dev.to** (easiest — paste the Markdown; code blocks render), Medium, Hashnode, or LinkedIn Articles. It must be public.
2. Paste `article.md`, re-upload the images at their spots, check headings, code blocks and the 3 links render.
3. Add tags on the platform (Dev.to allows 4): `ai`, `agents`, `llm`, `python`.
4. **Tag Code.in** in the article (the guide asks for this) — e.g. a last line: "Thanks to Code.in and the Vectorize team." On LinkedIn Articles, @-mention Code.in.
5. Copy the public URL.

## Step 5 — Reddit

Submit a **Link post** (not a text post) with your article URL to **one** of:
r/LLMDevs · r/AIAgents · r/AIMemory · r/SideProject

Suggested Reddit title (Reddit rewards plain titles):
`I built code review for my coding agents' memory (Hindsight + a review inbox + output checks)`

## Step 6 — LinkedIn post (Prompt 3)

Paste as the **main post** (694 characters, repo link included, hashtags on the last line only). Also in `docs/article/linkedin-post.txt`.

```
Your coding agent doesn't need more memory.
It needs memory that went through code review.

Agents keep re-proposing decisions the team already rejected. So I built ProjectPulse on Hindsight agent memory, which gave me hybrid recall for free so I could focus on governance:

1. Extract: each rule needs a verbatim quote. No quote, no memory.
2. Review: a human approves. Chatter gets filtered, with reasons.
3. Brief: max 5 rules, each with a reason. A dark-mode task gets the UI rule, not auth.
4. Supersede: retag, never delete.
5. Check the output. Before: token in localStorage. After: compliant.

Repo: https://github.com/Adarsh-s-007/adaptive-agent

#AIAgents #AgentMemory #Hindsight #LLM
```

Attach an image to the post: `12-check-before.png` + `13-check-after.png` (before/after) or `06-recall-hero.png`. @-mention Code.in in the post.

**Make sure the GitHub repo is public** before posting — the link must work.

### Comments (post these right after publishing)

First comment — the article:
```
Full write-up, with the code: <YOUR ARTICLE URL>
```

Second comment — Hindsight:
```
Here's Hindsight if you want to try it: https://github.com/vectorize-io/hindsight
```

## Final checklist

- [ ] Title is about the idea, not the event
- [ ] Opens with something specific (the localStorage token bug)
- [ ] Problem explained concretely (decisions lost between sessions)
- [ ] Shows where/how Hindsight is integrated (banks, retain, recall tag groups, documents retag, mental model, reflect, directives)
- [ ] Real code snippets (5 included)
- [ ] Before/after example (Memory Check before/after screenshots)
- [ ] Honest lesson / dead end (the UUIDv7 handle bug, "recall isn't compliance")
- [ ] Screenshots and diagrams uploaded
- [ ] Article published at a public URL
- [ ] Reddit link post submitted
- [ ] LinkedIn post live with repo link; article URL as first comment; Hindsight link as a comment
- [ ] Code.in tagged
- [ ] No "hackathon" anywhere
