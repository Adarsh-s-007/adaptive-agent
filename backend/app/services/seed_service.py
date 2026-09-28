"""Seed service for realistic multi-agent enterprise datasets: ApexCart & LedgerLite (RC-6, RC-7)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.governed_models import MemoryRecord, RecordEvidence
from app.gateways.hindsight_gateway import HindsightGateway
from app.models.entities import AgentSession, Project
from app.services.governed_memory_service import GovernedMemoryService


APEXCART_RECORDS = [
    {
        "type": "architecture_decision",
        "title": "Use Redis cluster for shopping cart state",
        "statement": "Shopping cart temporary states are stored in a dedicated Redis cluster with a strict 48-hour TTL.",
        "rationale": "Prevents relational database write saturation during flash sales while allowing fast ephemeral lookups.",
        "area": "cart",
        "importance": 4,
        "check_patterns": ["session.*cart", "cart_db_write", "save_cart_to_postgres"],
        "quote": "We agreed in sprint review that cart items belong in Redis with 48h TTL, not MySQL.",
    },
    {
        "type": "security_constraint",
        "title": "Store JWT tokens exclusively in HTTP-only Secure cookies",
        "statement": "Authentication JWT refresh tokens must be stored in HTTP-only, SameSite=Strict cookies. LocalStorage and sessionStorage are strictly forbidden.",
        "rationale": "Mitigates cross-site scripting (XSS) credential theft vectors.",
        "area": "auth",
        "importance": 5,
        "check_patterns": ["localStorage.setItem.*token", "sessionStorage.*token", "cookie.*httpOnly: false"],
        "quote": "Security audit flagged token storage in localStorage; we mandated HTTP-only cookies across all client apps.",
    },
    {
        "type": "coding_standard",
        "title": "Mandatory explicit timeouts on all asynchronous HTTP clients",
        "statement": "Every outbound HTTP client request must define explicit connection (default: 5.0s) and read timeouts (default: 15.0s).",
        "rationale": "Prevents event loop blocking and socket pool starvation during downstream provider latency spikes.",
        "area": "networking",
        "importance": 3,
        "check_patterns": ["httpx\\.AsyncClient\\(\\)", "requests\\.get\\([^)]*timeout=None\\)"],
        "quote": "The Stripe integration froze our workers last month because httpx had no read timeout configured.",
    },
    {
        "type": "architecture_decision",
        "title": "PostgreSQL with PgBouncer connection pooling as single source of truth",
        "statement": "PostgreSQL 16 using transaction-mode PgBouncer connection pooling is the authoritative datastore for orders and accounts.",
        "rationale": "Guarantees strict ACID transactional integrity for financial and inventory states.",
        "area": "database",
        "importance": 5,
        "check_patterns": ["mongodb.*orders", "sqlite.*production"],
        "quote": "Architecture board approved PostgreSQL as the sole datastore for billing and checkout entities.",
    },
    {
        "type": "dependency_rule",
        "title": "Domain boundary gateway isolation",
        "statement": "Cross-domain service communication must go through defined gateway interfaces; direct internal submodule imports are disallowed.",
        "rationale": "Maintains modular decoupling and enables deterministic mock injection during test execution.",
        "area": "architecture",
        "importance": 4,
        "check_patterns": ["from app\\.internal import", "import app\\.db\\.private"],
        "quote": "Keep domain boundaries clean by wrapping third-party APIs in gateway classes.",
    },
    {
        "type": "data_contract",
        "title": "Standard RFC-7807 problem details error envelopes",
        "statement": "All API error responses must adhere to the standard error envelope containing 'code', 'message', 'status_code', and optional 'details'.",
        "rationale": "Ensures uniform error handling across frontend clients and external agent consumers.",
        "area": "api",
        "importance": 4,
        "check_patterns": ["return.*\\{'error':.*'string'\\}", "JSONResponse\\(content=\\{'err':"],
        "quote": "Frontend team needs a consistent error structure across all checkout endpoints.",
    },
    {
        "type": "operational_rule",
        "title": "Idempotency keys required on payment and checkout mutations",
        "statement": "All POST and PATCH requests that initiate payment authorization or inventory reservations must include an 'Idempotency-Key' header.",
        "rationale": "Eliminates double-billing and duplicate order creation on network retries.",
        "area": "checkout",
        "importance": 5,
        "check_patterns": ["def process_payment\\((?!.*idempotency_key)", "POST.*checkout.*no_idempotency"],
        "quote": "Payment provider webhooks and client retries must be guarded with UUIDv7 idempotency keys.",
    },
    {
        "type": "testing_standard",
        "title": "Deterministic provider fakes for external billing APIs",
        "statement": "Integration test suites must use scriptable in-memory fakes instead of live third-party staging sandboxes.",
        "rationale": "Prevents flaky tests caused by sandbox rate-limits, network instability, and slow response times.",
        "area": "testing",
        "importance": 3,
        "check_patterns": ["stripe\\.live_call", "time\\.sleep.*waiting_for_sandbox"],
        "quote": "CI pipeline must never fail because an external sandbox is undergoing scheduled maintenance.",
    },
]

LEDGERLITE_RECORDS = [
    {
        "type": "architecture_decision",
        "title": "Immutable double-entry ledger bookkeeping",
        "statement": "All financial mutations must be recorded as immutable paired debit and credit balance adjustments totaling zero.",
        "rationale": "Provides a mathematically verifiable audit trail and eliminates silent balance drift.",
        "area": "ledger",
        "importance": 5,
        "check_patterns": ["UPDATE.*account_balances.*SET", "balance \\+= amount"],
        "quote": "Never update account balance columns in place; append journal entries with debits and credits.",
    },
    {
        "type": "security_constraint",
        "title": "Encrypt all PII and bank details at rest with AES-256-GCM",
        "statement": "Tax IDs, bank account numbers, and customer names must be encrypted before storage using envelope encryption with rotating KMS keys.",
        "rationale": "Regulatory compliance with PCI-DSS and SOC2 standards.",
        "area": "security",
        "importance": 5,
        "check_patterns": ["bank_account.*VARCHAR", "raw_ssn.*Text"],
        "quote": "KMS encryption envelope is mandatory for all banking fields before database persistence.",
    },
    {
        "type": "data_contract",
        "title": "Exact string representation for currency amounts",
        "statement": "Monetary values must be exchanged and persisted as integer cents or fixed-precision decimal strings; floating point types are prohibited.",
        "rationale": "Prevents IEEE-754 binary floating-point roundoff errors in interest and billing calculations.",
        "area": "currency",
        "importance": 5,
        "check_patterns": ["amount: float", "float\\(.*currency\\)"],
        "quote": "Floating point math has caused pennies discrepancies; everything must use string Decimals.",
    },
    {
        "type": "dependency_rule",
        "title": "Transactional Outbox pattern for external ledger events",
        "statement": "Financial events intended for message brokers must be committed into the local database outbox table in the same transaction as the ledger entries.",
        "rationale": "Prevents two-phase commit inconsistencies where messages are published but the database transaction rolls back.",
        "area": "messaging",
        "importance": 4,
        "check_patterns": ["kafka\\.send\\(.*db\\.commit\\)", "publish_event\\(.*before_commit=True\\)"],
        "quote": "Publishing events before commit led to ghost transactions; use the Outbox table instead.",
    },
    {
        "type": "operational_rule",
        "title": "Dual-control four-eyes authorization on settlement reversals",
        "statement": "Any manual settlement correction or transaction reversal exceeding $1,000 requires explicit cryptographic approval by two distinct compliance officers.",
        "rationale": "Mitigates insider fraud and rogue automated transaction cancellations.",
        "area": "settlement",
        "importance": 5,
        "check_patterns": ["approve_reversal\\(single_signer=True\\)"],
        "quote": "Four-eyes principle is required for any reversal over $1,000.",
    },
    {
        "type": "testing_standard",
        "title": "Property-based ledger invariant testing",
        "statement": "All accounting transaction processors must be fuzz-tested using property-based testing (Hypothesis) asserting sum(debits) == sum(credits).",
        "rationale": "Catches subtle boundary conditions and concurrent race conditions in balance calculations.",
        "area": "audit",
        "importance": 4,
        "check_patterns": ["assert.*balance > 0"],
        "quote": "Property tests run nightly generating 10,000 random transaction permutations to verify ledger invariants.",
    },
]


class SeedService:
    """Seeds authentic enterprise architecture memories and sessions."""

    def __init__(self, memory_service: GovernedMemoryService | None = None) -> None:
        self.memory_service = memory_service or GovernedMemoryService()

    async def seed_dataset(
        self,
        db: Session,
        project_id: str,
        dataset: str = "apexcart",
    ) -> dict[str, Any]:
        proj = db.get(Project, project_id)
        if not proj:
            return {"error": "Project not found"}

        records_to_seed = APEXCART_RECORDS if dataset == "apexcart" else LEDGERLITE_RECORDS

        # Create an associated Agent Session
        session = AgentSession(
            project_id=project_id,
            agent_name="Senior Staff Architect",
            task=f"Establish architectural baseline and governance policies for {proj.name} ({dataset})",
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        seeded_records = []
        for r_def in records_to_seed:
            # Check if duplicate already exists
            existing = db.scalar(
                select(MemoryRecord)
                .where(MemoryRecord.project_id == project_id, MemoryRecord.title == r_def["title"])
            )
            if existing:
                continue

            rec = await self.memory_service.create_record(
                db=db,
                project_id=project_id,
                title=r_def["title"],
                statement=r_def["statement"],
                memory_type=r_def["type"],
                rationale=r_def.get("rationale"),
                area=r_def.get("area"),
                importance=r_def.get("importance", 3),
                source_session_id=session.id,
                evidence_quote=r_def.get("quote"),
                tags=[f"project:{project_id}", f"type:{r_def['type']}", f"area:{r_def.get('area', '')}"],
                check_patterns=r_def.get("check_patterns", []),
            )
            seeded_records.append(rec)

        return {
            "project_id": project_id,
            "dataset": dataset,
            "session_id": session.id,
            "records_seeded": len(seeded_records),
            "total_active": self.memory_service.count_active(db, project_id),
            "status": "ready",
        }
