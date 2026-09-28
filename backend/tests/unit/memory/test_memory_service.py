"""Record lifecycle: C2-style retain, F1 supersede, F3 retag failure, X1b pending. Owner: P3."""

from app.gateways.project_context import resolve
from app.schemas.memories import RecordCreate
from app.services import memory_service as ms
from tests.unit.memory.fakes import MiniHindsight, make_project

POOL = RecordCreate(
    type="decision",
    title="DB connection limit",
    statement="Set connection_limit=25 on the API DATABASE_URL for Prisma.",
    area="database",
    applies_to=["database", "prisma"],
    seed_key="A07",
)
PGBOUNCER = RecordCreate(
    type="decision",
    title="Pooled DB URL",
    statement="Serverless functions use the pooled URL with pgbouncer=true&connection_limit=1.",
    area="database",
)


async def test_create_retains_with_conventions(db):
    hs = MiniHindsight()
    project = await make_project(db)
    record = await ms.create_record(db, project.id, POOL, gateway=hs)
    assert record.retain_state == "retained"
    doc = hs.docs[str(record.id)]
    assert "status:active" in doc.tags and "type:decision" in doc.tags
    assert doc.metadata["record_id"] == str(record.id)
    assert "connection_limit" in doc.entities
    assert record.hindsight_document_id == f"mem_{record.id}"


async def test_seed_key_is_idempotent(db):
    hs = MiniHindsight()
    project = await make_project(db)
    first = await ms.create_record(db, project.id, POOL, gateway=hs)
    second = await ms.create_record(db, project.id, POOL, gateway=hs)
    assert first.id == second.id and len(hs.docs) == 1


async def test_hindsight_down_leaves_record_failed_then_retry(db):
    hs = MiniHindsight()
    hs.fail = True
    project = await make_project(db)
    record = await ms.create_record(db, project.id, PGBOUNCER, gateway=hs)
    assert record.retain_state == "failed"
    hs.fail = False
    record = await ms.retry(db, project.id, record.id, gateway=hs)
    assert record.retain_state == "retained" and len(hs.docs) == 1


async def test_supersede_excludes_old_from_recall(db):
    """F1"""
    hs = MiniHindsight()
    project = await make_project(db)
    old = await ms.create_record(db, project.id, POOL, gateway=hs)
    new, old = await ms.supersede(db, project.id, old.id, PGBOUNCER, reviewer="Priya", gateway=hs)
    assert old.status == "superseded" and old.superseded_by_record_id == new.id
    assert "Replaces the decision of" in hs.docs[str(new.id)].content
    ctx = await resolve(db, project.id)
    ids = [
        f.record_id for f in await hs.recall(ctx, "prisma connection limit pooled", purpose="brief")
    ]
    assert str(new.id) in ids and str(old.id) not in ids
    assert await ms.version_chain(db, new) == [old.id, new.id]


async def test_retag_failure_marks_retag_pending(db):
    """F3"""
    hs = MiniHindsight()
    project = await make_project(db)
    old = await ms.create_record(db, project.id, POOL, gateway=hs)

    async def boom(*a, **k):
        from app.core.errors import AppError, ErrorCode

        raise AppError(ErrorCode.HINDSIGHT_UNAVAILABLE, "down")

    hs.retag = boom
    _, old = await ms.supersede(db, project.id, old.id, PGBOUNCER, reviewer="Priya", gateway=hs)
    assert old.status == "superseded" and old.retain_state == "retag_pending"
    statuses = await ms.active_status_map(db, project.id, [old.id])
    assert statuses[str(old.id)] == "superseded"  # post-filter still excludes it


async def test_secrets_rejected(db):
    project = await make_project(db)
    bad = POOL.model_copy(
        update={"statement": "Use api_key=gsk_abcdefghijklmnop for Groq calls", "seed_key": None}
    )
    try:
        await ms.create_record(db, project.id, bad, gateway=MiniHindsight())
    except Exception as exc:
        assert "secrets" in str(exc)
    else:
        raise AssertionError("secret accepted")
