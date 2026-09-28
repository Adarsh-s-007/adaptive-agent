"""Platform contract tests: auth, error envelope, health, I3. Owner: P1."""

from app.core.ids import record_pill, uuid7
from app.core.memory_conventions import document_id, record_id_from_document
from tests.conftest import AUTH


async def test_health_is_public(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["db"] == "ok"


async def test_api_requires_token(client):
    r = await client.get("/api/v1/projects/00000000-0000-0000-0000-000000000000/memories")
    assert r.status_code == 401
    body = r.json()["error"]
    assert body["code"] == "UNAUTHORIZED"
    assert body["request_id"]


async def test_unknown_route_uses_envelope(client):
    r = await client.get("/api/v1/nope", headers=AUTH)
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


async def test_no_endpoint_accepts_bank_id(client):
    """I3: the client can never choose a Hindsight bank."""
    spec = (await client.get("/openapi.json")).json()
    assert "bank_id" not in str(spec.get("components", {}).get("schemas", {})).replace(
        "hindsight_bank_id", ""
    )


def test_ids_and_conventions():
    rid = uuid7()
    assert rid.version == 7
    assert record_pill(rid).startswith("MEM-")
    assert record_id_from_document(document_id(rid)) == str(rid)
