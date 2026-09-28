"""Comprehensive unit and integration test suite for ProjectPulse Blueprint implementation."""

import asyncio
import unittest
import uuid

from app.core.ids import generate_record_pill, generate_uuidv7
from app.core.memory_conventions import (
    build_tags,
    format_document_id,
    render_record_content,
)
from app.db.database import Base, get_db
from app.gateways.project_context import ProjectContext
from app.main import app
from app.models.entities import Project
from app.services.brief_service import BriefService
from app.services.check_service import CheckService
from app.services.compare_service import CompareService
from app.services.extraction_validator import ExtractionValidator
from app.services.generation_service import GenerationService
from app.services.governed_memory_service import GovernedMemoryService
from app.services.signals import TranscriptPreparer
from app.services.transcript_parser import TranscriptParser
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from tests.fakes.fake_hindsight import FakeHindsight
from tests.fakes.fake_llm import FakeLLM


class TestBlueprintImplementation(unittest.TestCase):
    """Test suite covering the complete blueprint architecture."""

    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine)

        def override_get_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

    def setUp(self):
        self.db = self.Session()
        self.fake_hindsight = FakeHindsight()
        self.fake_llm = FakeLLM()
        self.mem_service = GovernedMemoryService(gateway=self.fake_hindsight)
        self.brief_service = BriefService(hindsight=self.fake_hindsight, llm=self.fake_llm, memory_service=self.mem_service)
        self.check_service = CheckService(hindsight=self.fake_hindsight, llm=self.fake_llm, memory_service=self.mem_service)
        self.gen_service = GenerationService(llm=self.fake_llm, brief_service=self.brief_service)
        self.comp_service = CompareService(generation_service=self.gen_service, check_service=self.check_service)

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def _create_test_project(self, name: str = "ApexCart") -> Project:
        pid = str(uuid.uuid4())
        proj = Project(
            id=pid,
            name=f"{name}-{pid[:6]}",
            hindsight_bank_id=f"pp_apexcart_{pid[:6]}",
            description="E-commerce demo project",
        )
        self.db.add(proj)
        self.db.commit()
        self.db.refresh(proj)
        return proj

    # --- 1. Conventions & IDs ---
    def test_ids_and_conventions(self):
        u7 = generate_uuidv7()
        self.assertEqual(len(u7), 36)
        self.assertEqual(u7[14], "7")  # UUIDv7 version digit

        pill = generate_record_pill(u7)
        self.assertTrue(pill.startswith("MEM-"))

        doc_id = format_document_id("test-123")
        self.assertEqual(doc_id, "mem_test-123")

        tags = build_tags("proj-1", "architecture_decision", area="auth")
        self.assertIn("project:proj-1", tags)
        self.assertIn("type:architecture_decision", tags)
        self.assertIn("area:auth", tags)

        rendered = render_record_content(
            title="Use HTTP-only cookies",
            statement="JWT refresh tokens must be stored in HTTP-only cookies.",
            memory_type="security_rule",
            rationale="Prevent XSS token exfiltration.",
            area="auth",
        )
        self.assertIn("[security_rule] Use HTTP-only cookies", rendered)
        self.assertIn("Prevent XSS token exfiltration.", rendered)

    # --- 2. Transcript Parser & Validator ---
    def test_transcript_parser_and_validation(self):
        raw_md = (
            "Human (Priya): We decided that authentication must use HTTP-only cookies with CSRF protection.\n"
            "Agent: Understood. I will configure the cookie flags accordingly.\n"
            "Tool: Cookie options set: HttpOnly=True, Secure=True, SameSite=Lax."
        )
        turns = TranscriptParser.parse(raw_md)
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[0].role, "human")
        self.assertEqual(turns[1].role, "agent")
        self.assertEqual(turns[2].role, "tool")

        prepared = TranscriptPreparer.prepare_turns(turns)
        self.assertEqual(len(prepared), 3)

        # Validation success
        quote = "We decided that authentication must use HTTP-only cookies with CSRF protection."
        val = ExtractionValidator.validate(
            statement="Authentication must use HTTP-only cookies with CSRF protection.",
            memory_type="security_rule",
            evidence_quote=quote,
            transcript_texts=[t.content for t in prepared],
        )
        self.assertTrue(val.valid)
        self.assertEqual(val.status, "pending")

        # Validation failure: non-verbatim quote (C5)
        val_bad_quote = ExtractionValidator.validate(
            statement="Authentication must use HTTP-only cookies with CSRF protection.",
            memory_type="security_rule",
            evidence_quote="This sentence never appeared in the transcript at all.",
            transcript_texts=[t.content for t in prepared],
        )
        self.assertFalse(val_bad_quote.valid)
        self.assertEqual(val_bad_quote.status, "filtered")
        self.assertIn("verbatim", val_bad_quote.reason)

        # Validation failure: secret credential
        val_secret = ExtractionValidator.validate(
            statement="Our secret API key is sk-1234567890abcdef123456.",
            memory_type="security_rule",
            evidence_quote=quote,
            transcript_texts=[t.content for t in prepared],
        )
        self.assertFalse(val_secret.valid)

    # --- 3. Governed Memory Service: Outbox & 5-Step Supersession ---
    def test_governed_memory_lifecycle_and_supersession(self):
        proj = self._create_test_project()

        # Step A: Create initial record
        record1 = asyncio.run(
            self.mem_service.create_record(
                db=self.db,
                project_id=proj.id,
                title="Store JWT in LocalStorage",
                statement="Store authentication JWT tokens in browser localStorage.",
                memory_type="architecture_decision",
                area="auth",
                evidence_quote="Let's just put it in localStorage for now.",
            )
        )
        self.assertEqual(record1.status, "active")
        self.assertEqual(record1.retain_state, "retained")
        self.assertEqual(len(record1.evidence), 1)

        # Check active count
        count = self.mem_service.count_active(self.db, proj.id)
        self.assertEqual(count, 1)

        # Step B: Supersede with new decision (RC-2 5-step protocol)
        record2 = asyncio.run(
            self.mem_service.supersede(
                db=self.db,
                old_record_id=record1.id,
                title="Migrate JWT to HTTP-only cookies",
                statement="JWT refresh tokens must use HTTP-only cookies; LocalStorage is forbidden.",
                rationale="Mitigate XSS token theft vulnerability.",
                area="auth",
                evidence_quote="We must migrate out of localStorage immediately.",
            )
        )
        self.db.refresh(record1)
        self.assertEqual(record1.status, "superseded")
        self.assertEqual(record1.superseded_by_id, record2.id)
        self.assertEqual(record2.status, "active")
        self.assertEqual(record2.supersedes_id, record1.id)
        self.assertEqual(record2.retain_state, "retained")

        # Active count is still 1 because old record was superseded!
        self.assertEqual(self.mem_service.count_active(self.db, proj.id), 1)

    # --- 4. Isolation Checks (I1) ---
    def test_project_isolation(self):
        proj_a = self._create_test_project("ProjectA")
        proj_b = self._create_test_project("ProjectB")

        ctx_a = ProjectContext(project_id=proj_a.id, bank_id=proj_a.hindsight_bank_id, project_name=proj_a.name)

        # Record from project B injected into project A's context
        isolated = ctx_a.assert_record_isolated(proj_b.id)
        self.assertFalse(isolated)
        self.assertEqual(ctx_a.isolation_blocked_count, 1)

        # Native project A record passes
        self.assertTrue(ctx_a.assert_record_isolated(proj_a.id))
        self.assertEqual(ctx_a.isolation_blocked_count, 1)

    # --- 5. Brief Service (R1, R3) ---
    def test_brief_service_zero_records_and_applied(self):
        proj = self._create_test_project("EmptyProject")

        # R3: Zero active records short-circuit
        brief_empty = asyncio.run(self.brief_service.build_brief(self.db, proj.id, "Build checkout flow"))
        self.assertEqual(brief_empty.status, "empty")
        self.assertEqual(len(brief_empty.applied), 0)

        # Add active record
        rec = asyncio.run(
            self.mem_service.create_record(
                db=self.db,
                project_id=proj.id,
                title="Database Outbox Pattern",
                statement="Use outbox pattern: commit database transaction first, then make external HTTP calls.",
                memory_type="architecture_decision",
                area="database",
            )
        )

        # Configure fake LLM applicability response
        self.fake_llm.set_job_response(
            "applicability",
            {
                "selections": [
                    {"record_id": rec.id, "applies": True, "reason": "Applies to database transaction handling"}
                ]
            },
        )

        brief = asyncio.run(self.brief_service.build_brief(self.db, proj.id, "Implement order checkout transaction"))
        self.assertEqual(len(brief.applied), 1)
        self.assertEqual(brief.applied[0].record.id, rec.id)
        self.assertGreater(brief.injected_tokens, 0)

    # --- 6. Memory Check & Post-Validation (CK-1, CK-2) ---
    def test_memory_check_and_post_validation(self):
        proj = self._create_test_project("CheckProject")

        rec = asyncio.run(
            self.mem_service.create_record(
                db=self.db,
                project_id=proj.id,
                title="Strict HTTPS",
                statement="All external webhook URLs must use HTTPS.",
                memory_type="security_rule",
                check_patterns=["http://[a-zA-Z0-9]"],
            )
        )

        # Code containing violation
        bad_code = "const webhookUrl = 'http://api.partner.com/notify';"

        # Configure LLM judge response that matches excerpt and ID
        self.fake_llm.set_job_response(
            "judge",
            {
                "verdict": "fail",
                "violations": [
                    {
                        "record_id": rec.id,
                        "severity": "high",
                        "excerpt": "http://api.partner.com/notify",
                        "explanation": "Webhook uses insecure HTTP protocol.",
                        "suggested_fix": "Change to https://api.partner.com/notify",
                    }
                ],
            },
        )

        check_res = asyncio.run(self.check_service.check(self.db, proj.id, bad_code))
        self.assertEqual(check_res.verdict, "fail")
        self.assertEqual(len(check_res.violations), 1)
        self.assertEqual(check_res.violations[0].record_id, rec.id)
        # Check pattern evidence attached (CK-2)
        self.assertGreater(len(check_res.violations[0].pattern_evidence), 0)

        # Test Post-Validation: Judge hallucinates non-existent record ID -> MUST BE DROPPED!
        self.fake_llm.set_job_response(
            "judge",
            {
                "verdict": "fail",
                "violations": [
                    {
                        "record_id": "hallucinated-id-not-in-recalled-set",
                        "severity": "high",
                        "excerpt": "http://api.partner.com/notify",
                        "explanation": "Fabricated rule.",
                        "suggested_fix": "Fix.",
                    }
                ],
            },
        )

        check_hallucinated = asyncio.run(self.check_service.check(self.db, proj.id, bad_code))
        # Hallucinated violation dropped, verdict becomes pass
        self.assertEqual(check_hallucinated.verdict, "pass")
        self.assertEqual(len(check_hallucinated.violations), 0)

    # --- 7. Compare Service (CP-1) ---
    def test_compare_service(self):
        proj = self._create_test_project("CompareProject")
        rec = asyncio.run(
            self.mem_service.create_record(
                db=self.db,
                project_id=proj.id,
                title="No LocalStorage",
                statement="Do not store sensitive tokens in localStorage.",
                memory_type="security_rule",
            )
        )

        # Baseline generation output uses localStorage, Memory generation avoids it
        self.fake_llm.set_job_response(
            "generate",
            {
                "summary": "Implementation plan",
                "files": ["auth.js"],
                "notes": ["Using standard cookie auth."],
                "followed_record_ids": [rec.id],
            },
        )

        comp = asyncio.run(self.comp_service.compare(self.db, proj.id, "Build authentication flow"))
        self.assertEqual(comp.status, "completed")
        self.assertIsNotNone(comp.baseline_run)
        self.assertIsNotNone(comp.memory_run)
        self.assertIsNotNone(comp.fairness)

    # --- 8. API v1 Integration Endpoints ---
    def test_api_v1_endpoints(self):
        proj = self._create_test_project("ApiProject")

        # GET /api/v1/projects/{pid}/memories
        res_list = self.client.get(f"/api/v1/projects/{proj.id}/memories")
        self.assertEqual(res_list.status_code, 200)
        self.assertEqual(len(res_list.json()), 0)

        # POST /api/v1/projects/{pid}/memories
        res_create = self.client.post(
            f"/api/v1/projects/{proj.id}/memories",
            json={
                "title": "Use Redis for shopping cart sessions",
                "statement": "Shopping cart temporary states are stored in Redis cluster with 48h TTL.",
                "memory_type": "architecture_decision",
                "area": "cart",
                "importance": 4,
            },
        )
        self.assertEqual(res_create.status_code, 201)
        created_data = res_create.json()
        self.assertEqual(created_data["title"], "Use Redis for shopping cart sessions")
        self.assertEqual(created_data["status"], "active")

        # POST /api/v1/projects/{pid}/brief
        res_brief = self.client.post(
            f"/api/v1/projects/{proj.id}/brief",
            json={"task": "Implement shopping cart item update"},
        )
        self.assertEqual(res_brief.status_code, 200)
        brief_data = res_brief.json()
        self.assertIn("status", brief_data)

        # POST /api/v1/projects/{pid}/sessions/import
        transcript_content = (
            "Human: We should make sure carts expire after 48 hours.\n"
            "Agent: Agreed. We set the TTL to 48 hours in Redis."
        )
        res_import = self.client.post(
            f"/api/v1/projects/{proj.id}/sessions/import",
            json={
                "title": "Cart Architecture Session",
                "transcript": transcript_content,
            },
        )
        self.assertEqual(res_import.status_code, 201)
        import_data = res_import.json()
        self.assertIn("session_id", import_data)

        # GET /api/v1/projects/{pid}/candidates
        res_cands = self.client.get(f"/api/v1/projects/{proj.id}/candidates")
        self.assertEqual(res_cands.status_code, 200)


if __name__ == "__main__":
    unittest.main()
