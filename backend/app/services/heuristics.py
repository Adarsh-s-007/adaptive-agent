"""Deterministic fallbacks used only when no LLM is available.

Every result produced here is labelled `heuristic` in API responses and the UI. These
functions never create memory on their own: extraction output still passes the
validator and a human review, and heuristic check findings are pattern evidence.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.core.taxonomy import slugify_area
from app.db.governed_models import MemoryRecord
from app.prompts.schemas import (
    ApplicabilityItem,
    ExtractedCandidate,
    ExtractionOutput,
    JudgeFinding,
    JudgeOutput,
    RelationItem,
)
from app.services.signals import SIGNAL_PATTERNS, TRANSIENT_SIGNALS
from app.services.transcript_parser import ParsedTurn

HEURISTIC_MODEL = "heuristic-v1"

STOP = {
    "the", "and", "for", "this", "that", "with", "from", "into", "your", "our", "are", "was",
    "use", "using", "add", "make", "new", "code", "app", "should", "must", "never", "always",
    "not", "all", "any", "only", "when", "then", "than", "have", "has", "will", "can", "via",
    "per", "its", "they", "them", "who", "how", "what", "why", "which", "also", "each", "one",
    "a", "an", "to", "of", "in", "on", "is", "be", "it", "we", "or", "as", "at", "by",
    "client", "user", "users", "keep", "handle", "data", "project", "rule", "task", "across", "show",
}

AREA_KEYWORDS: dict[str, set[str]] = {
    "auth": {"auth", "login", "logout", "signin", "sign", "signup", "session", "token", "tokens",
             "cookie", "cookies", "password", "jwt", "refresh", "csrf", "credential", "reloads"},
    "payments": {"stripe", "payment", "payments", "webhook", "webhooks", "charge", "refund",
                 "invoice", "payment_intent"},
    "database": {"database", "db", "prisma", "postgres", "sql", "query", "queries", "pool",
                 "pooling", "connection", "connections", "orders", "order", "column", "schema",
                 "table", "delete", "soft", "migration", "pgbouncer", "timeout", "timeouts"},
    "frontend": {"ui", "component", "components", "button", "toggle", "header", "css", "style",
                 "styling", "tailwind", "dark", "theme", "mode", "page", "layout", "react"},
    "infra": {"deploy", "deployment", "ci", "migrate", "migrations", "vercel", "env", "docker",
              "staging", "production", "release", "ship"},
    "testing": {"test", "tests", "bug", "fix", "regression", "vitest", "playwright", "twice"},
    "checkout": {"cart", "carts", "checkout", "guest", "basket", "redis"},
    "api": {"endpoint", "endpoints", "route", "routes", "api", "handler", "handlers", "response",
            "envelope", "post", "get", "zod", "validation"},
    "observability": {"log", "logs", "logging", "debug", "debugging", "trace", "monitor", "pii"},
}


def tokens(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-z0-9_@./-]+", (text or "").lower())
        if len(t) > 2 and t not in STOP
    } | {t.strip("./") for t in re.findall(r"[a-z]+", (text or "").lower()) if len(t) > 2 and t not in STOP}


def areas_for(text: str) -> set[str]:
    words = tokens(text)
    return {area for area, keys in AREA_KEYWORDS.items() if words & keys}


def record_text(record: MemoryRecord) -> str:
    applies = " ".join(json.loads(record.applies_to_json or "[]"))
    return f"{record.title} {record.statement} {record.area or ''} {applies}"


# ------------------------------------------------------------------ applicability
def applicability(task: str, records: list[MemoryRecord]) -> list[ApplicabilityItem]:
    task_words = tokens(task)
    task_areas = areas_for(task)
    items: list[ApplicabilityItem] = []
    for record in records:
        rec_words = tokens(record_text(record))
        overlap = sorted(task_words & rec_words - {"project", "rule"})
        applies_to = {a.lower() for a in json.loads(record.applies_to_json or "[]")}
        scope_hits = sorted(w for w in task_words if any(w == s or w in s.split() for s in applies_to))
        area_match = (record.area or "") in task_areas
        score = len(overlap) + 2 * len(scope_hits) + (2 if area_match else 0)
        applies = score >= 3 and (area_match or len(scope_hits) > 0 or len(overlap) >= 3)
        if applies:
            basis = scope_hits or overlap
            reason = f"Task touches {', '.join(basis[:3]) or record.area} — matches this record's scope."
        elif area_match:
            reason = f"Same area ({record.area}) but nothing in the task would follow or break it."
        else:
            reason = "No shared scope with the task."
        items.append(ApplicabilityItem(record_id=record.id, applies=applies, reason=reason[:150]))
    return items


# ---------------------------------------------------------------------- extraction
TYPE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("failed_approach", SIGNAL_PATTERNS["failed_approach"]),
    ("incident", SIGNAL_PATTERNS["incident"]),
    ("deployment", re.compile(r"(?i)\b(only ci|migrate deploy|migrations?|deploy|vercel|docker)\b")),
    ("security_constraint", re.compile(r"(?i)\b(token|cookie|csrf|xss|secret|password|auth|pii|rate.?limit|security)\b")),
    ("api_contract", re.compile(r"(?i)\b(envelope|response shape|returns? \{|status code|api contract|error code)\b")),
    ("convention", re.compile(r"(?i)\b(live in|lives in|folder|directory|naming|convention|components/)\b")),
    ("preference", re.compile(r"(?i)\b(every (?:bug )?fix|we prefer|team rule|working agreement)\b")),
]


def _sentences(text: str) -> list[str]:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z`\"'(])", text.strip())
    return [p.strip() for p in parts if p.strip()]


TRIGGER = re.compile(
    r"(?i)\b(we decided|decided to|from now on|going forward|never|always|must|must not|forbidden|"
    r"not allowed|every|only|replaces?|obsolete|no longer|team rule|we tried|reverted)\b"
)
DEFERRED = re.compile(r"(?i)(not (?:in )?this sprint|maybe later|let'?s (?:park|defer)|some other time)")
MECHANICS = re.compile(r"(?i)^(?:hi|hey|hello|morning|good (?:morning|afternoon)|thanks|thank you|great|looks (?:good|right))\b")
LEADS = re.compile(r"(?i)^(?:no[\s—,.-]+|we decided:?\s*|from now on,?\s*|also,?\s*|so\s+)+")


def _area(text: str) -> str | None:
    words = tokens(text)
    scored = sorted(((len(words & keys), area) for area, keys in AREA_KEYWORDS.items()), reverse=True)
    return scored[0][1] if scored and scored[0][0] > 0 else None


def extract(turns: list[ParsedTurn], max_candidates: int = 8) -> ExtractionOutput:
    """One candidate per human turn: its rule-bearing sentences merged, quote kept verbatim."""
    candidates: list[ExtractedCandidate] = []
    discarded: list[dict[str, str]] = []
    for turn in turns:
        if turn.role != "human":
            continue
        rule_sentences: list[str] = []
        for sentence in _sentences(turn.content):
            if TRANSIENT_SIGNALS.search(sentence):
                discarded.append({"item": sentence[:160], "reason": "Transient state (branch, machine, current build) — not a durable rule."})
                continue
            if DEFERRED.search(sentence):
                discarded.append({"item": sentence[:160], "reason": "Deferred idea, not a decision the team made."})
                continue
            if MECHANICS.search(sentence) and not TRIGGER.search(sentence):
                if len(discarded) < 12:
                    discarded.append({"item": sentence[:160], "reason": "Conversation mechanics."})
                continue
            if len(sentence) >= 25 and TRIGGER.search(sentence):
                rule_sentences.append(sentence)
        if not rule_sentences:
            continue
        strongest = max(
            rule_sentences,
            key=lambda s: (bool(re.search(r"(?i)we decided|from now on|every|only|replaces", s)), len(s)),
        )
        cleaned = [LEADS.sub("", s, count=1).strip() or s for s in rule_sentences]
        statement = " ".join(c[0].upper() + c[1:] for c in cleaned if c)
        if len(statement) > 400:
            statement = statement[:397].rsplit(" ", 1)[0] + "…"
        joined = " ".join(rule_sentences)
        memory_type = next((t for t, rx in TYPE_RULES if rx.search(joined)), "decision")
        title_src = LEADS.sub("", strongest, count=1).strip() or strongest
        title = re.split(r"[:;(]", title_src)[0].strip().rstrip(".")[:72]
        has_reason = bool(SIGNAL_PATTERNS["rationale"].search(turn.content))
        candidates.append(
            ExtractedCandidate(
                type=memory_type,
                title=title[0].upper() + title[1:] if title else "Team rule",
                statement=statement,
                rationale=None,
                area=slugify_area(_area(joined)),
                applies_to=sorted(areas_for(joined))[:4],
                evidence_quote=strongest,
                evidence_turn_ids=[turn.turn_index],
                stated_by="human",
                confidence=0.75 if has_reason or len(rule_sentences) > 1 else 0.6,
                importance=3 if memory_type in ("security_constraint", "incident", "failed_approach") else 2,
            )
        )
        if len(candidates) >= max_candidates:
            break
    return ExtractionOutput(candidates=candidates, discarded=discarded[:12])


# ----------------------------------------------------------------------- relation
IDENT = re.compile(r"[A-Za-z_@/.]*[_@/.=][A-Za-z0-9_@/.]+|[a-z]+[A-Z]\w+|[A-Z][a-z]+[A-Z]\w+")


def _identifiers(text: str) -> set[str]:
    out = set()
    for raw in IDENT.findall(text or ""):
        token = raw.strip(".,;:()").split("=")[0].lower()
        if len(token) >= 4:
            out.add(token)
    return out


def relate(statement: str, related: list[MemoryRecord], transcript_text: str = "") -> RelationItem:
    words = tokens(statement)
    idents = _identifiers(statement)
    obsolete = bool(SIGNAL_PATTERNS["obsolete"].search(statement))
    best: tuple[float, float, int, MemoryRecord | None] = (0.0, 0.0, 0, None)
    for record in related:
        other = tokens(record.statement)
        if not words or not other:
            continue
        jaccard = len(words & other) / len(words | other)
        shared = len(idents & _identifiers(record.statement))
        score = jaccard + 0.3 * shared
        if score > best[0]:
            best = (score, jaccard, shared, record)
    score, jaccard, shared, record = best
    if record is None or score < 0.2:
        return RelationItem(candidate_index=0, relation="new", reason="No similar active record.")
    if obsolete and (shared or jaccard >= 0.25):
        return RelationItem(candidate_index=0, relation="supersedes", target_record_id=record.id,
                            reason=f"Says the earlier rule is replaced and shares scope with {record.pill}.")
    if jaccard >= 0.6 or shared >= 2 or (shared >= 1 and jaccard >= 0.2):
        return RelationItem(candidate_index=0, relation="duplicate", target_record_id=record.id,
                            reason=f"Restates {record.pill} ({shared} shared identifier(s), {jaccard:.0%} term overlap).")
    return RelationItem(candidate_index=0, relation="refines", target_record_id=record.id,
                        reason=f"Overlaps {record.pill} without replacing it.")


# -------------------------------------------------------------------------- check
def pattern_hits(record: MemoryRecord, content: str) -> tuple[list[str], list[str]]:
    """Return (forbidden matches, required patterns missing)."""
    forbidden: list[str] = []
    missing: list[str] = []
    for raw in json.loads(record.check_patterns_json or "[]"):
        if not isinstance(raw, str) or not raw.strip():
            continue
        required = raw.startswith(("require:", "required:"))
        pattern = raw.split(":", 1)[1] if required else raw
        try:
            match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
        except re.error:
            match = re.search(re.escape(pattern), content, re.IGNORECASE)
        if required and not match:
            missing.append(pattern)
        elif not required and match:
            forbidden.append(match.group(0))
    return forbidden, missing


def derive_patterns(statement: str) -> list[str]:
    """Auto-derive deterministic Check hints from a rule's wording (pattern evidence only)."""
    text = statement or ""
    low = text.lower()
    patterns: list[str] = []
    prohibitive = bool(re.search(r"\b(never|no |not |forbidden|must not|don't|do not)\b", low))
    if prohibitive and ("localstorage" in low or "sessionstorage" in low):
        patterns.append(r"(?:local|session)Storage\.setItem\([^)]*(?:token|jwt|auth)")
    if prohibitive and "new prismaclient" in low:
        patterns.append(r"new PrismaClient\(")
    if prohibitive and "migrate dev" in low:
        patterns.append(r"prisma migrate dev")
    if "connection_limit=1" in low:
        patterns.append(r"connection_limit=(?:[2-9]|\d{2,})")
    for cookie in re.findall(r"__Host-[\w-]+", text):
        patterns.append(f"require:{re.escape(cookie)}")
    for header in re.findall(r"\bX-[A-Za-z][\w-]+", text):
        patterns.append(f"require:{re.escape(header)}")
    seen: list[str] = []
    for p in patterns:
        if p not in seen:
            seen.append(p)
    return seen[:6]


def judge(content: str, records: list[MemoryRecord]) -> JudgeOutput:
    violations: list[JudgeFinding] = []
    warnings: list[JudgeFinding] = []
    content_areas = areas_for(content)
    for record in records:
        forbidden, missing = pattern_hits(record, content)
        for excerpt in forbidden[:1]:
            target = warnings if record.confidence_band == "low" else violations
            target.append(
                JudgeFinding(
                    record_id=record.id,
                    severity="high" if record.importance >= 3 else "medium",
                    excerpt=excerpt,
                    explanation=f"Matches a pattern this record forbids: {record.statement[:160]}",
                    suggested_fix=f"Follow {record.pill}: {record.statement[:160]}",
                )
            )
        if missing and not forbidden and (record.area in content_areas):
            warnings.append(
                JudgeFinding(
                    record_id=record.id,
                    severity="low",
                    excerpt=content.strip().splitlines()[0][:80] if content.strip() else "",
                    explanation=f"Expected pattern not found: {', '.join(missing[:2])}",
                    suggested_fix=f"Check against {record.pill}: {record.statement[:160]}",
                )
            )
    return JudgeOutput(
        summary="Deterministic pattern check (no LLM configured).",
        verdict="violations" if violations else "compliant",
        violations=violations,
        warnings=warnings,
    )


def identifiers(content: str, limit: int = 12) -> list[str]:
    """Pull code identifiers out of an output to sharpen the Check recall query."""
    found = re.findall(
        r"(?:[A-Za-z_][\w]*\.[A-Za-z_][\w.]*\(?|__[A-Za-z][\w-]+|[A-Z][a-z]+[A-Z]\w+|X-[\w-]+|@[\w/-]+)",
        content or "",
    )
    seen: list[str] = []
    for item in found:
        item = item.rstrip("(")
        if item not in seen:
            seen.append(item)
        if len(seen) >= limit:
            break
    return seen


def summarize_output(content: str) -> str:
    first = next((line.strip() for line in (content or "").splitlines() if line.strip()), "")
    return first[:200]


def as_dicts(items: list[Any]) -> list[dict[str, Any]]:
    return [i.model_dump() if hasattr(i, "model_dump") else dict(i) for i in items]
