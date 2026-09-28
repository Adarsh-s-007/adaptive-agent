"""Unit and integration test suite for P3: Governed Records, Timeline, Metrics & Seed (RC-1..7, MT-1)."""

import asyncio
import unittest
import uuid

from app.core.ids import generate_uuidv7
from app.db.database import Base, get_db
from app.db.governed_models import MemoryRecord, OutboxMessage
from app.main import app
from app.models.entities import Project
from app.services.governed_memory_service import GovernedMemoryService
from app.services.metrics_service import MetricsService
from app.services.seed_service import SeedService
from app.services.timeline_service import TimelineService
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from tests.fakes.fake_hindsight import FakeHindsight


class TestP3GovernedRecords(unittest.TestCase):
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

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.clear()
        cls.client.close()
        cls.engine.dispose()

    def setUp(self):
        self.db = self.Session()
        self.fake_hindsight = FakeHindsight()
        self.mem_service = GovernedMemoryService(gateway=self.fake_hindsight)
        self.metrics_service = MetricsService(gateway=self.fake_hindsight)
        self.seed_service = SeedService(memory_service=self.mem_service)

        self.project_id = str(uuid.uuid4())
        self.project = Project(
            id=self.project_id,
            name=f"ApexCart-Test-{self.project_id[:6]}",
            description="E-Commerce testing platform",
            hindsight_bank_id=f"bank_{self.project_id[:8]}",
        )
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_record_lifecycle_create_and_supersede(self):
        async def _test():
            # 1. Create a record
            rec1 = await self.mem_service.create_record(
                db=self.db,
                project_id=self.project_id,
                title="Use Redis for cart state",
                statement="Shopping cart state is stored in Redis with 48h TTL.",
                memory_type="architecture_decision",
                rationale="Fast lookups during sales",
                area="cart",
                importance=4,
                evidence_quote="Cart items belong in Redis.",
            )
            self.assertIsNotNone(rec1.id)
            self.assertTrue(rec1.pill.startswith("MEM-"))
            self.assertEqual(rec1.status, "active")
            self.assertEqual(rec1.retain_state, "retained")
            docs = self.fake_hindsight.documents.get(self.project.hindsight_bank_id, [])
            self.assertEqual(len(docs), 1)

            # 2. 5-step supersession protocol (RC-2, RC-3)
            rec2 = await self.mem_service.supersede(
                db=self.db,
                old_record_id=rec1.id,
                title="Migrate cart state to Redis Cluster with 72h TTL",
                statement="Shopping cart state is stored in Redis Cluster with 72h TTL.",
                rationale="Extended holiday shopping windows.",
                area="cart",
                importance=5,
                evidence_quote="We must expand the cart TTL to 72h.",
            )
            self.db.refresh(rec1)
            self.assertEqual(rec1.status, "superseded")
            self.assertEqual(rec1.superseded_by_id, rec2.id)
            self.assertEqual(rec2.supersedes_id, rec1.id)
            self.assertEqual(rec2.status, "active")

            # 3. Retract (RC-4)
            rec3 = await self.mem_service.retract(self.db, rec2.id, reason="Deprecated approach")
            self.assertEqual(rec3.status, "retracted")

        asyncio.run(_test())

    def test_outbox_queueing_and_flush(self):
        async def _test():
            # Simulate Hindsight error
            self.fake_hindsight.simulated_error = "Hindsight 503 Unavailable"

            # Create record while offline -> should queue in Outbox (RC-5)
            rec = await self.mem_service.create_record(
                db=self.db,
                project_id=self.project_id,
                title="Offline rule",
                statement="All database connections must be pooled.",
                memory_type="coding_standard",
            )
            self.assertEqual(rec.retain_state, "failed")

            outbox_msgs = list(
                self.db.scalars(
                    select(OutboxMessage).where(OutboxMessage.project_id == self.project_id)
                ).all()
            )
            self.assertGreaterEqual(len(outbox_msgs), 1)
            self.assertEqual(outbox_msgs[0].status, "pending")

            # Restore connectivity and flush outbox
            self.fake_hindsight.simulated_error = None
            flush_res = await self.mem_service.flush_outbox(self.db, self.project_id)
            self.assertEqual(flush_res["synced"], 1)
            self.assertEqual(flush_res["failed"], 0)

            self.db.refresh(rec)
            self.assertEqual(rec.retain_state, "retained")

        asyncio.run(_test())

    def test_timeline_service(self):
        async def _test():
            await self.mem_service.create_record(
                db=self.db,
                project_id=self.project_id,
                title="Timeline Rule A",
                statement="First test timeline statement.",
                memory_type="security_constraint",
            )
            timeline = TimelineService.get_timeline(self.db, self.project_id)
            self.assertGreaterEqual(len(timeline), 1)
            self.assertEqual(timeline[0]["event_type"], "memory_retained")
            self.assertIn("Timeline Rule A", timeline[0]["title"])

        asyncio.run(_test())

    def test_metrics_service_section20(self):
        async def _test():
            # Seed 2 records
            await self.mem_service.create_record(
                db=self.db,
                project_id=self.project_id,
                title="Metric Rule 1",
                statement="Rule 1 statement.",
                memory_type="architecture_decision",
                area="cart",
            )
            r2 = await self.mem_service.create_record(
                db=self.db,
                project_id=self.project_id,
                title="Metric Rule 2",
                statement="Rule 2 statement.",
                memory_type="coding_standard",
                area="networking",
            )
            await self.mem_service.retract(self.db, r2.id)

            metrics = await self.metrics_service.get_project_metrics(self.db, self.project_id)
            self.assertEqual(metrics["project_id"], self.project_id)
            self.assertEqual(metrics["summary"]["active_records"], 1)
            self.assertEqual(metrics["summary"]["retracted_records"], 1)
            self.assertEqual(metrics["isolation_score"], 100.0)
            self.assertEqual(metrics["by_type"]["architecture_decision"], 1)
            self.assertEqual(metrics["by_area"]["cart"], 1)

        asyncio.run(_test())

    def test_seed_service_apexcart_and_ledgerlite(self):
        async def _test():
            seed_res = await self.seed_service.seed_dataset(self.db, self.project_id, dataset="apexcart")
            self.assertEqual(seed_res["dataset"], "apexcart")
            self.assertEqual(seed_res["records_seeded"], 8)
            self.assertEqual(seed_res["total_active"], 8)

        asyncio.run(_test())

    def test_p3_api_v1_endpoints(self):
        headers = {"Authorization": "Bearer dev-token-projectpulse"}
        pid = self.project_id

        # 1. POST /api/v1/projects/{pid}/seed
        res_seed = self.client.post(
            f"/api/v1/projects/{pid}/seed",
            json={"dataset": "apexcart"},
            headers=headers,
        )
        self.assertEqual(res_seed.status_code, 200)
        self.assertEqual(res_seed.json()["records_seeded"], 8)

        # 2. GET /api/v1/projects/{pid}/records
        res_list = self.client.get(f"/api/v1/projects/{pid}/records", headers=headers)
        self.assertEqual(res_list.status_code, 200)
        records = res_list.json()
        self.assertGreaterEqual(len(records), 8)
        rid = records[0]["id"]

        # 3. GET /api/v1/projects/{pid}/records/{rid}
        res_detail = self.client.get(f"/api/v1/projects/{pid}/records/{rid}", headers=headers)
        self.assertEqual(res_detail.status_code, 200)
        self.assertEqual(res_detail.json()["id"], rid)

        # 4. POST /api/v1/projects/{pid}/records/{rid}/supersede
        res_sup = self.client.post(
            f"/api/v1/projects/{pid}/records/{rid}/supersede",
            json={
                "title": "Updated Super Rule",
                "statement": "Updated statement superseding old decision.",
                "area": "cart",
                "importance": 5,
            },
            headers=headers,
        )
        self.assertEqual(res_sup.status_code, 200)
        new_rid = res_sup.json()["new_record_id"]

        # 5. POST /api/v1/projects/{pid}/records/{new_rid}/retract
        res_ret = self.client.post(
            f"/api/v1/projects/{pid}/records/{new_rid}/retract",
            json={"reason": "Testing retraction"},
            headers=headers,
        )
        self.assertEqual(res_ret.status_code, 200)

        # 6. GET /api/v1/projects/{pid}/timeline
        res_tl = self.client.get(f"/api/v1/projects/{pid}/timeline", headers=headers)
        self.assertEqual(res_tl.status_code, 200)
        self.assertIsInstance(res_tl.json(), list)

        # 7. GET /api/v1/projects/{pid}/metrics
        res_met = self.client.get(f"/api/v1/projects/{pid}/metrics", headers=headers)
        self.assertEqual(res_met.status_code, 200)
        self.assertIn("summary", res_met.json())

        # 8. POST /api/v1/projects/{pid}/outbox/flush
        res_flush = self.client.post(f"/api/v1/projects/{pid}/outbox/flush", headers=headers)
        self.assertEqual(res_flush.status_code, 200)


if __name__ == "__main__":
    unittest.main()
