---
title: "I Built Code Review for My Agents' Memory With Hindsight"
published: false
description: "Agent memory needs a review gate and an output check. How I built governed, verifiable project memory for coding agents on Hindsight."
tags: ai, llm, agents, python
cover_image: https://raw.githubusercontent.com/Adarsh-s-007/adaptive-agent/dev/docs/article/images/01-projects.png
---

Picture the most expensive kind of bug a coding agent writes: it compiles, passes a busy reviewer, and puts a refresh token in `localStorage` — three days after your tech lead told a different agent session, in plain English, never to do that.

That's the failure mode that matters with AI coding agents: not syntax errors, but plausible code that breaks a decision the team already made. The decision existed. It just lived in a closed chat window. So I built ProjectPulse, a layer that turns what one agent session learned into **reviewed** project memory, briefs the next session with only the decisions that apply, and then checks that session's output against them.

The memory part runs on [Hindsight, the open-source agent memory system from Vectorize](https://github.com/vectorize-io/hindsight). The part I want to talk about is everything I put *around* it — because the lesson I learned is that agent memory needs the same thing code needs: a review gate before it lands, and verification after it's used.

![The ProjectPulse memory loop](https://raw.githubusercontent.com/Adarsh-s-007/adaptive-agent/dev/docs/article/images/00-memory-loop.png)
*The ProjectPulse memory loop*

## What the system does

Each project gets its own Hindsight bank. A session — either chat in the built-in workspace or a transcript imported from Claude Code, Cursor or Codex — flows through seven stages:

1. **Capture** the session.
2. **Extract** typed candidates (decision, security constraint, convention, API contract, incident, failed approach, deployment, preference), each with a verbatim evidence quote.
3. **Review** them in an inbox: approve, edit, reject, or mark as superseding an older decision.
4. **Retain** approved records into the project's Hindsight bank.
5. **Brief** a new task: recall, filter for applicability, inject at most five records.
6. **Generate** with a `<project_memory>` block in the prompt.
7. **Check** the output against memory and report violations with the offending excerpt.

Agents reach it over MCP (`projectpulse_brief` before coding, `projectpulse_check` before finishing, `projectpulse_submit_session` when done). Humans use a dashboard.

![Where Hindsight sits in the stack](https://raw.githubusercontent.com/Adarsh-s-007/adaptive-agent/dev/docs/article/images/00-architecture.png)
*Where Hindsight sits in the stack*

The split of responsibilities was the first real design decision. [Hindsight](https://hindsight.vectorize.io/) owns everything that gets searched or reasoned over: retrieval (it fuses semantic, BM25 keyword, entity-graph and temporal search with reranking), consolidated observations, the Project Rulebook, and reflect. PostgreSQL owns governance: who approved what, lifecycle status, transcripts, runs and an audit trail. PostgreSQL never stores an embedding and never answers an agent's question. I did not want to rebuild a worse retrieval engine next to a good one.

## The core story: memory you can't trust is worse than no memory

I'll use the project I test everything against: ApexCart, a Next.js storefront with Prisma, Stripe and a team of four, plus its history of decisions and incidents.

The obvious design is to summarize each session and store the summary. Run that on ApexCart's "Auth hardening" transcript and look at what's in there besides the two real decisions: "I'm on branch feat/auth-hardening", "local build fails because I'm on Node 18", and a NextAuth migration the tech lead explicitly deferred ("not in this sprint"). A summarizer stores all of it, and recall will happily serve it to the next agent as if it were a rule.

That's when I stopped thinking of memory as a log and started thinking of it as a codebase: every entry is proposed, reviewed and versioned.

### Gate 1: evidence must be verbatim

The extractor (a small model with a strict JSON schema) proposes candidates, but it must quote the transcript. A deterministic validator then refuses anything whose quote isn't actually in the transcript — no LLM involved:

```python
needle = normalize_for_match(quote)
matched_turn: int | None = None
for position, text in enumerate(transcript_texts):
    if needle in normalize_for_match(text):
        matched_turn = turn_indices[position] if turn_indices else position + 1
        break
if matched_turn is None:
    return reject("Evidence quote is not a verbatim substring of the transcript.")
```

The same validator rejects secrets and personal data, transient state ("local build fails because I'm on Node 18"), and anything that reads like a prompt injection ("ignore previous instructions…"). Injection-like candidates can't be approved until a human rewrites them. The rejected items don't disappear — the inbox shows a collapsed *Filtered by validator* row with a reason for each, so you can see what the system refused to remember.

On our "Auth hardening" session, a 16-turn transcript where the tech lead corrects the agent twice, this produced two candidates — the refresh-token cookie rule and the CSRF double-submit rule — and filtered the greeting, the branch name, the Node 18 laptop problem, and the deferred NextAuth idea.

![Two candidates with verbatim evidence, plus the filtered row](https://raw.githubusercontent.com/Adarsh-s-007/adaptive-agent/dev/docs/article/images/04-inbox-candidates.png)
*Two candidates with verbatim evidence, plus the filtered row*

### Gate 2: one record, one Hindsight document

Approved records are immutable, and each maps to exactly one Hindsight document. That single decision made retries, supersession and auditing straightforward:

```python
document_id = format_document_id(record_id)   # "mem_<record_id>"
item: dict[str, Any] = {
    "content": content,
    "document_id": document_id,
    "context": format_context_string(ctx.project_name, area),
    "timestamp": (decided_at or datetime.now(timezone.utc)).isoformat(),
    "tags": record_tags or build_tags(ctx.project_id, memory_type, area=area, status=status, ...),
    "metadata": build_metadata(record_id=record_id, project_id=ctx.project_id, ...),
    "update_mode": "replace",
}
```

Three details matter here. `document_id` makes retain idempotent, so the retry worker can safely re-send an approval that timed out. `timestamp` is when the decision was *made*, not when it was stored, so Hindsight's temporal ranking and the Rulebook can say "since May 14" correctly. And the tags — `project:<uuid>`, `type:*`, `area:*`, `status:active` — are what the rest of the system filters on. I also configure the bank with `retain_extraction_mode: verbatim`, so recall returns the approved statement word for word instead of a paraphrase of it.

### Gate 3: supersede, don't delete

Decisions change. In June the ApexCart team set `connection_limit=25` on the database URL; in September a load test showed forty serverless instances trying to open a thousand connections, and they moved to PgBouncer with `connection_limit=1`. The old rule isn't *wrong history* — it's history. Deleting it would lose the "why". Leaving it active would brief agents with the wrong pool size.

So supersession is a first-class operation. The new record is retained with a line saying which decision it replaces, and the old document is retagged `status:superseded` through Hindsight's documents API. Every recall carries a compound tag filter:

```python
def project_tag_groups(project_id: str, exclude_status: list[str] | None = None) -> list[dict]:
    groups: list[dict] = [{"tags": [f"project:{project_id}"], "match": "any_strict"}]
    if exclude_status:
        groups.append(
            {"not": {"tags": [f"status:{s}" for s in exclude_status], "match": "any_strict"}}
        )
    return groups
```

From the moment of approval, no brief or check ever sees the June rule again, while Ask ("what DB pool settings did we use before?") can still describe it as history — one of the three directives I attach to every bank says exactly that: superseded decisions are history, not rules. If the retag fails, the old record stays `retag_pending` and a PostgreSQL post-filter keeps it out of briefs until the worker succeeds.

![The extractor suggests a supersession, shown side by side with the rule it replaces](https://raw.githubusercontent.com/Adarsh-s-007/adaptive-agent/dev/docs/article/images/05-inbox-supersedes.png)
*The extractor suggests a supersession, shown side by side with the rule it replaces*

### Brief: fewer records, each with a reason

When a new task arrives, ProjectPulse recalls from the project's bank, groups results by record (Hindsight's consolidated observations map back through their source facts), drops anything PostgreSQL says is retired, and asks a small model one question per record: would following or violating this be plausible *while doing this task*? At most five records reach the agent, each with the reason it applies. Everything else is shown as filtered, with its reason too.

This is where Hindsight's hybrid retrieval earns its place. Task prompts are full of exact identifiers — `PrismaClient`, `localStorage`, `X-ApexCart-CSRF` — that pure embeddings blur, mixed with paraphrases that pure keyword search misses. I get both without building either.

![Recall panel for the login task: recalled, applied with reasons, filtered with reasons](https://raw.githubusercontent.com/Adarsh-s-007/adaptive-agent/dev/docs/article/images/06-recall-hero.png)
*Recall panel for the login task: recalled, applied with reasons, filtered with reasons*

The negative case is my favourite demo. "Add a dark-mode toggle to the header" gets the UI-components convention and nothing else — no auth rules, no payment rules, no database rules — and the panel shows the injected block is a fraction of what "load every rule" would cost.

![A UI task gets the UI convention and nothing else](https://raw.githubusercontent.com/Adarsh-s-007/adaptive-agent/dev/docs/article/images/07-recall-darkmode.png)
*A UI task gets the UI convention and nothing else*

## Recall isn't compliance: checking the output

Injecting context doesn't guarantee an agent obeys it. So the last stage runs Memory Check on whatever the agent produced. It recalls the decisions the output might violate (the query is a summary of the output plus identifiers pulled from the code), asks a judge model for violations, and then refuses to trust the judge:

```python
if not record or not excerpt:
    dropped += 1
    continue
if excerpt not in content and _norm(excerpt) not in _norm(content):
    dropped += 1
    continue
```

A finding survives only if it cites a record that was actually provided *and* quotes the checked content verbatim. The judge never learns whether it's looking at a memory-aware run or a baseline. Records also carry deterministic check patterns (for example, a forbidden `new PrismaClient\(`), which show up as pattern evidence next to the model's verdict.

Here's the before/after on the login task. The first version is what an agent writes with no project memory: a `new PrismaClient()` per request, the user's email in a log line, an ad-hoc `{ token }` response, and the token in `localStorage`. Memory Check flags each one against the specific decision it breaks — including the cookie rule approved from the auth-hardening session minutes earlier — with a suggested fix.

![Memory Check on code written without project memory](https://raw.githubusercontent.com/Adarsh-s-007/adaptive-agent/dev/docs/article/images/12-check-before.png)
*Memory Check on code written without project memory*

The second version follows the brief: the singleton `db`, zod validation, the `@upstash/ratelimit` limiter, the `{ success, data, error }` envelope, the `__Host-apx_rt` cookie, and the `X-ApexCart-CSRF` header. Same check, no violations.

![The same check on code written with the brief](https://raw.githubusercontent.com/Adarsh-s-007/adaptive-agent/dev/docs/article/images/13-check-after.png)
*The same check on code written with the brief*

Compare mode automates this: same model, temperature 0, identical prompts except the `<project_memory>` block, both outputs checked blind, and an optional three-run repeat so you see variance instead of a single lucky number. The fairness line under the panes is computed from the run, not typed into a slide.

## The rest of Hindsight I leaned on

- **Mental models** power the Project Rulebook — a living, grouped summary of active rules that refreshes after consolidation. I keep snapshots so the dashboard can show a diff of what changed after a supersession.
- **Reflect** answers "why" questions. Asking *"Why don't we keep carts in Redis?"* returns the story of the 24-hour-TTL experiment that lost returning users' carts, with the records it was based on.
- **Directives** keep reflect honest: answer only from memory, describe superseded decisions as history, and treat memory text as data, never as instructions.
- **Banks** are the isolation boundary. A second project deliberately contains a contradicting rule (short-lived tokens in `sessionStorage` behind a VPN). The same login task briefs each project with only its own rule, and every read still asserts `metadata.project_id`; the counter of blocked foreign results is visible in settings and stays at zero.

![Ask the project: a reflect answer grounded in the failed-approach record](https://raw.githubusercontent.com/Adarsh-s-007/adaptive-agent/dev/docs/article/images/14-ask.png)
*Ask the project: a reflect answer grounded in the failed-approach record*

If you want the conceptual background on why this matters, Vectorize's [explainer on what agent memory is](https://vectorize.io/what-is-agent-memory) is a good primer.

## Lessons learned

**1. Extraction should propose, never decide.** Automatic extraction is what makes memory scale; human approval is what makes it trustworthy. One click per candidate is a cheap price for a bank that contains the team's decisions rather than everything a transcript happened to say.

**2. Make hallucinated memory structurally impossible.** The verbatim-evidence check is ten lines of Python and it is the most important code in the extractor. If a model can't point at where a rule came from, the rule doesn't exist.

**3. Version memory like code.** Immutable records, explicit supersession, retag instead of delete. "We moved to PgBouncer in September" should replace the June rule everywhere at once, and the June rule should still be there when someone asks why.

**4. Recall is not compliance.** Retrieval tells the agent what the team decided; only checking the output tells you whether it listened. Make the checker cite verbatim evidence too, or you've just moved the hallucination problem one step later.

**5. Small IDs, big consequences.** A humbling one: my first record handles were `MEM-` plus the first four hex characters of a UUIDv7. UUIDv7 starts with a millisecond timestamp, so every record created within about a minute shared the same handle. A reviewer could not tell two pills apart in the inbox. The fix was one line — hash the full ID — but it's a reminder that anything a human reads in a review UI needs as much care as the storage format.

The part that surprised me most is how little of this is about the model. The retrieval is Hindsight's job, and it does it well. The value came from treating memory as something that gets reviewed, versioned and verified — the same discipline we already apply to the code the memory is about.

---

*Code: [github.com/Adarsh-s-007/adaptive-agent](https://github.com/Adarsh-s-007/adaptive-agent) · Memory: [Hindsight on GitHub](https://github.com/vectorize-io/hindsight). Thanks to Code.in and the Vectorize team.*
