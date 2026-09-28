"""ProjectPulse contract and end-to-end API tests with provider boundaries stubbed."""

import asyncio
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

_test_dir = tempfile.TemporaryDirectory()
os.environ["DATABASE_URL"] = "sqlite:///" + str(
    Path(_test_dir.name) / "projectpulse-test.db"
)
os.environ["HINDSIGHT_API_KEY"] = "test-hindsight-key"
os.environ["GROQ_API_KEY"] = "test-groq-key"

from app.api import routes
from app.db.database import SessionLocal, engine
from app.main import app
from app.models.entities import Project
from app.services import mcp_server
from app.services.groq_service import GroqService
from app.services.hindsight_service import HindsightService
from fastapi import HTTPException
from fastapi.testclient import TestClient


class FakeHindsight:
    def __init__(self):
        self.banks = {}
        self.recall_calls = []

    bank_slug = staticmethod(HindsightService.bank_slug)

    async def create_bank(self, bank_id, name, description):
        self.banks[bank_id] = []
        return {"bank_id": bank_id}

    async def retain(self, bank_id, *, content, document_id, metadata, tags):
        self.banks[bank_id].append(
            {
                "content": content,
                "document_id": document_id,
                "metadata": metadata,
                "tags": tags,
            }
        )
        return {"success": True, "items_count": 1}

    async def retain_batch(self, bank_id, items):
        for item in items:
            self.banks[bank_id] = [
                old
                for old in self.banks[bank_id]
                if old["document_id"] != item["document_id"]
            ]
            self.banks[bank_id].append(item)
        return {"success": True, "items_count": len(items)}

    async def list_memories(self, bank_id, project_id, memory_type=None, tag=None):
        items = [
            {
                "id": item["document_id"],
                "text": item["content"],
                "type": item["metadata"]["memory_type"],
                "tags": item["tags"],
                "metadata": item["metadata"],
                "source_agent": item["metadata"]["source_agent"],
                "session_id": item["metadata"].get("session_id"),
                "timestamp": "2026-09-28T10:00:00Z",
                "origin": "hindsight",
            }
            for item in self.banks[bank_id]
            if (not memory_type or item["metadata"]["memory_type"] == memory_type)
            and (not tag or tag in item["tags"])
        ]
        return items

    async def recall(self, bank_id, project_id, query, limit):
        self.recall_calls.append((bank_id, project_id, query))
        return [
            {
                "id": item["document_id"],
                "text": item["content"].split("Decision / learning: ")[-1],
                "type": "world",
                "metadata": item["metadata"],
                "document_id": item["document_id"],
                "source_text": item["content"],
                "timestamp": "2026-09-28T10:00:00Z",
                "why_relevant": None,
            }
            for item in self.banks[bank_id][:limit]
        ]


class FakeGroq:
    async def select_relevant(self, task, memories):
        words = task.lower()
        if "login" in words or "authentication" in words:
            return [
                {**item, "why_relevant": "The task implements authentication."}
                for item in memories
                if "JWT refresh tokens" in item["text"]
            ]
        return []

    async def answer(self, prompt, *, memory_aware=False):
        if memory_aware:
            return "Use HTTP-only cookies for JWT refresh tokens; avoid localStorage."
        return "Build a login form, validate credentials, and handle errors."


class FlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old_hindsight = routes.hindsight
        cls.old_groq = routes.groq
        cls.old_service_hindsight = routes.memory_service.hindsight
        cls.old_mcp_hindsight = mcp_server.service.hindsight
        cls.fake_hindsight = FakeHindsight()
        routes.hindsight = cls.fake_hindsight
        routes.memory_service.hindsight = cls.fake_hindsight
        mcp_server.service.hindsight = cls.fake_hindsight
        routes.groq = FakeGroq()
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        routes.hindsight = cls.old_hindsight
        routes.groq = cls.old_groq
        routes.memory_service.hindsight = cls.old_service_hindsight
        mcp_server.service.hindsight = cls.old_mcp_hindsight
        cls.client.close()
        engine.dispose()
        _test_dir.cleanup()

    def test_fresh_agent_recall_and_bank_isolation(self):
        with SessionLocal() as db:
            db.query(Project).filter(Project.name.in_(["E-commerce Platform", "Inventory Tool"])).delete()
            db.commit()

        ecom_response = self.client.post(
            "/projects",
            json={"name": "E-commerce Platform", "description": "Storefront demo"},
        )
        self.assertEqual(ecom_response.status_code, 201, ecom_response.text)
        ecom = ecom_response.json()

        seed = self.client.post(f"/projects/{ecom['id']}/seed-demo-data")
        self.assertEqual(seed.status_code, 200, seed.text)
        self.assertEqual(seed.json()["seeded"], 8)
        self.assertEqual(
            self.client.post(f"/projects/{ecom['id']}/seed-demo-data").json()["seeded"],
            0,
        )
        self.assertEqual(len(self.fake_hindsight.banks[ecom["hindsight_bank_id"]]), 8)

        retained = self.client.post(
            f"/projects/{ecom['id']}/memories",
            json={
                "memory_type": "coding convention",
                "source_agent": "Agent A",
                "content": "Use one consistent field-error shape in checkout forms.",
            },
        )
        self.assertEqual(retained.status_code, 201, retained.text)
        self.assertEqual(retained.json()["event"]["agent_name"], "Agent A")
        self.assertEqual(
            self.client.get(f"/projects/{ecom['id']}/stats").json()["retained"], 9
        )

        auth = self.client.post(
            f"/projects/{ecom['id']}/agent-answer",
            json={
                "agent_name": "Agent B - fresh session",
                "task": "Build login authentication",
            },
        )
        self.assertEqual(auth.status_code, 200, auth.text)
        answer = auth.json()
        self.assertEqual(len(answer["memories"]), 1)
        self.assertIn("HTTP-only cookies", answer["memory_aware_answer"])
        self.assertNotIn("HTTP-only cookies", answer["generic_answer"])
        self.assertEqual(answer["used_bank_id"], ecom["hindsight_bank_id"])
        self.assertEqual(answer["session"]["agent_name"], "Agent B - fresh session")
        self.assertEqual(
            json.loads(answer["event"]["hindsight_memory_reference"]),
            ["seed-jwt-security-v2"],
        )
        self.assertEqual(
            self.fake_hindsight.recall_calls[-1][0], ecom["hindsight_bank_id"]
        )

        unrelated = self.client.post(
            f"/projects/{ecom['id']}/agent-answer",
            json={"task": "Improve footer typography and keyboard focus"},
        )
        self.assertEqual(unrelated.status_code, 200, unrelated.text)
        self.assertEqual(unrelated.json()["memories"], [])
        self.assertEqual(
            unrelated.json()["generic_answer"],
            unrelated.json()["memory_aware_answer"],
        )

        second = self.client.post(
            "/projects", json={"name": "Inventory Tool", "description": "Warehouse"}
        ).json()
        self.assertNotEqual(second["hindsight_bank_id"], ecom["hindsight_bank_id"])
        second_answer = self.client.post(
            f"/projects/{second['id']}/agent-answer",
            json={"task": "Build login authentication"},
        )
        self.assertEqual(second_answer.status_code, 200, second_answer.text)
        self.assertEqual(second_answer.json()["memories"], [])
        self.assertEqual(
            self.fake_hindsight.recall_calls[-1][0], second["hindsight_bank_id"]
        )
        self.assertEqual(
            self.client.post(f"/projects/{second['id']}/seed-demo-data").status_code,
            400,
        )
        self.assertGreaterEqual(
            len(self.client.get(f"/projects/{ecom['id']}/timeline").json()),
            11,
        )
        self.assertEqual(
            self.client.post(
                f"/projects/{ecom['id']}/agent-answer", json={"task": "   "}
            ).status_code,
            422,
        )
        self.assertEqual(self.client.get("/projects/not-a-uuid").status_code, 422)

        listed = self.client.get(f"/projects/{ecom['id']}/memories")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["origin"], "hindsight")
        self.assertEqual(listed.json()["count"], 9)

        mcp_demo = self.client.post(f"/projects/{ecom['id']}/run-mcp-demo")
        self.assertEqual(mcp_demo.status_code, 200, mcp_demo.text)
        self.assertEqual(
            mcp_demo.json()["tool_call"], "projectpulse.recall_project_memory"
        )
        self.assertIn("HTTP-only", mcp_demo.json()["memories"][0]["text"])
        self.assertIn("not an external coding agent", mcp_demo.json()["sample_result"])
        activity = self.client.get(f"/projects/{ecom['id']}/activity").json()
        self.assertTrue(
            any(
                item["tool_name"] == "projectpulse.recall_project_memory"
                for item in activity
            )
        )
        self.assertTrue(any(item["kind"] == "agent_result" for item in activity))


class DemoModeTests(unittest.TestCase):
    def test_local_memory_is_labelled_relevant_and_project_scoped(self):
        first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
        with SessionLocal() as db:
            db.add(
                Project(
                    id=first_id,
                    name="Demo Checkout " + first_id[:8],
                    description="Local sample",
                    hindsight_bank_id="demo-" + first_id,
                )
            )
            db.add(
                Project(
                    id=second_id,
                    name="Demo Checkout " + second_id[:8],
                    description="Other project",
                    hindsight_bank_id="demo-" + second_id,
                )
            )
            db.commit()
            service = routes.memory_service
            saved = asyncio.run(
                service.retain(
                    db,
                    first_id,
                    "Refresh tokens use HTTP-only Secure cookies, not LocalStorage.",
                    "security_rule",
                    ["authentication"],
                    "Agent A",
                )
            )
            self.assertEqual(saved["origin"], "demo")
            self.assertIn("Demo mode", saved["mode_label"])
            found = asyncio.run(
                service.recall(db, first_id, "Implement refresh token login", 5)
            )
            self.assertEqual(len(found["memories"]), 1)
            self.assertEqual(found["memories"][0]["origin"], "demo")
            unrelated = asyncio.run(
                service.recall(
                    db, first_id, "Improve footer typography and keyboard focus", 5
                )
            )
            self.assertEqual(unrelated["memories"], [])
            isolated = asyncio.run(
                service.recall(db, second_id, "Implement refresh token login", 5)
            )
            self.assertEqual(isolated["memories"], [])
            filtered = asyncio.run(
                service.list_memories(db, first_id, "security_rule", "authentication")
            )
            self.assertEqual(filtered["count"], 1)
            empty = asyncio.run(service.list_memories(db, first_id, tag="payments"))
            self.assertEqual(empty["count"], 0)
            with self.assertRaises(HTTPException):
                asyncio.run(
                    service.recall(
                        db,
                        second_id,
                        "Implement login",
                        5,
                        session_id=found["session_id"],
                    )
                )
            with self.assertRaises(HTTPException):
                asyncio.run(
                    service.retain(
                        db,
                        first_id,
                        "password=supersecret is the new default.",
                        "security_rule",
                        [],
                        "Agent A",
                    )
                )


class ProviderContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_hindsight_probe_is_read_only_and_does_not_expose_credentials(self):
        service = HindsightService()
        service._request = AsyncMock(return_value={"items": []})

        status = await service.probe()

        self.assertEqual(status["status"], "connected")
        self.assertTrue(status["configured"])
        self.assertNotIn("key", status["message"].lower())
        service._request.assert_awaited_once_with(
            "GET", "/banks", params=[("limit", "1")]
        )

    async def test_hindsight_recall_uses_current_schema_and_provenance(self):
        service = HindsightService()
        service._request = AsyncMock(
            return_value={
                "results": [
                    {
                        "id": "fact-1",
                        "text": "Refresh tokens belong in HTTP-only cookies.",
                        "type": "world",
                        "chunk_id": "chunk-1",
                        "metadata": {
                            "memory_type": "architecture decision",
                            "source_agent": "Agent A",
                        },
                        "mentioned_at": "2026-09-28T10:00:00Z",
                        "scores": {"final": 0.42},
                    }
                ],
                "chunks": {
                    "chunk-1": {"text": "Never use localStorage for refresh tokens."}
                },
            }
        )
        memories = await service.recall("bank-1", "project-1", "Build login", 5)
        payload = service._request.await_args.args[2]
        self.assertEqual(payload["tags"], ["project:project-1"])
        self.assertEqual(payload["tags_match"], "any_strict")
        self.assertIn("max_tokens", payload)
        self.assertIn("chunks", payload["include"])
        self.assertNotIn("max_results", payload)
        self.assertEqual(
            memories[0]["source_text"], "Never use localStorage for refresh tokens."
        )
        self.assertEqual(memories[0]["timestamp"], "2026-09-28T10:00:00Z")

    async def test_hindsight_list_uses_project_tag_and_filters(self):
        service = HindsightService()
        service._request = AsyncMock(
            return_value={
                "items": [
                    {
                        "id": "fact-1",
                        "text": "Use HttpOnly cookies.",
                        "metadata": {
                            "memory_type": "security_rule",
                            "source_agent": "Agent A",
                        },
                        "tags": ["project:project-1", "authentication"],
                    }
                ],
                "total": 1,
                "limit": 100,
                "offset": 0,
            }
        )
        items = await service.list_memories(
            "bank-1", "project-1", "security_rule", "authentication"
        )
        self.assertEqual(len(items), 1)
        params = service._request.await_args.kwargs["params"]
        self.assertIn(("tags", "project:project-1"), params)
        self.assertIn(("tags", "authentication"), params)
        self.assertIn(("tags_match", "all_strict"), params)
        self.assertEqual(items[0]["origin"], "hindsight")

    async def test_groq_selector_can_abstain(self):
        service = GroqService()
        service._complete = AsyncMock(return_value='{"selected":[]}')
        selected = await service.select_relevant(
            "Improve footer typography",
            [{"id": "payment", "text": "Payment pool exhaustion", "source_text": ""}],
        )
        self.assertEqual(selected, [])


if __name__ == "__main__":
    unittest.main()
