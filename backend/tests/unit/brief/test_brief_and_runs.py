"""Brief and runs: R3, X1a, X3, M1, M2. Owner: P5."""

from app.core.errors import AppError, ErrorCode
from app.gateways.project_context import resolve
from app.schemas.memories import RecordCreate
from app.services import generation_service, memory_service
from app.services.brief_service import build_brief
from app.services.prompt_assembler import build_messages
from tests.fakes.fake_llm import FakeLLM
from tests.unit.memory.fakes import MiniHindsight, make_project

COOKIE = RecordCreate(
    type="security_constraint",
    title="Refresh token storage",
    statement="Refresh tokens live only in the __Host-apx_rt cookie; never store tokens in localStorage.",
    area="auth",
    applies_to=["login", "session"],
    importance=3,
)
WEBHOOK = RecordCreate(
    type="decision",
    title="Stripe webhook raw body",
    statement="The Stripe webhook route reads the raw body and verifies the signature for login-free events.",
    area="payments",
)


def applies_only(title_word: str):
    def handler(messages, schema):
        import json

        records = json.loads(
            messages[1]["content"].split("instructions):\n", 1)[1].split("\n\nReturn")[0]
        )
        return {
            "decisions": [
                {"record_id": r["record_id"], "applies": title_word in r["rule"], "reason": "test"}
                for r in records
            ]
        }

    return handler


def generation(messages, schema):
    return {"summary": "done", "files": [], "notes": [], "followed_record_ids": ["not-a-record"]}


async def _setup(db, hs):
    project = await make_project(db)
    for body in (COOKIE, WEBHOOK):
        await memory_service.create_record(db, project.id, body, gateway=hs)
    return project, await resolve(db, project.id)


async def test_zero_records_makes_no_recall_call(db):
    """R3"""
    hs = MiniHindsight()
    project = await make_project(db)
    ctx = await resolve(db, project.id)
    result = await build_brief(db, ctx, "Add a login route", hindsight=hs, llm=FakeLLM())
    assert result.brief.status == "empty" and hs.recall_calls == 0


async def test_applicability_splits_applied_and_filtered(db):
    hs = MiniHindsight()
    _, ctx = await _setup(db, hs)
    llm = FakeLLM({"applicability": applies_only("localStorage")})
    brief = (
        await build_brief(
            db, ctx, "Add login route and keep the session token", hindsight=hs, llm=llm
        )
    ).brief
    assert brief.status == "ok"
    assert [a.record.title for a in brief.applied] == ["Refresh token storage"]
    assert [f.record.title for f in brief.filtered] == ["Stripe webhook raw body"]
    assert brief.injected_tokens > 0


async def test_applicability_failure_falls_back_unfiltered(db):
    """X3"""
    hs = MiniHindsight()
    _, ctx = await _setup(db, hs)

    def fail(messages, schema):
        raise AppError(ErrorCode.LLM_UNAVAILABLE, "down")

    brief = (
        await build_brief(
            db, ctx, "login session token", hindsight=hs, llm=FakeLLM({"applicability": fail})
        )
    ).brief
    assert brief.status == "unfiltered" and 1 <= len(brief.applied) <= 3


async def test_hindsight_down_brief_unavailable_but_baseline_runs(db):
    """X1a + M1"""
    hs = MiniHindsight()
    project, ctx = await _setup(db, hs)
    hs.fail = True
    brief = (await build_brief(db, ctx, "login session token", hindsight=hs, llm=FakeLLM())).brief
    assert brief.status == "memory_unavailable"
    llm = FakeLLM({"generate": generation})
    hs.recall_calls = 0
    run, _ = await generation_service.run(
        db, project.id, "login", "baseline", hindsight=hs, llm=llm
    )
    assert run.status == "done" and hs.recall_calls == 0 and run.followed_record_ids == []


async def test_memory_run_filters_invented_record_ids(db):
    hs = MiniHindsight()
    project, _ = await _setup(db, hs)
    llm = FakeLLM({"applicability": applies_only("localStorage"), "generate": generation})
    run, brief = await generation_service.run(
        db, project.id, "login session token", "memory", hindsight=hs, llm=llm
    )
    assert brief.applied and run.followed_record_ids == []


async def test_prompts_differ_only_by_memory_block(db):
    """M2"""
    hs = MiniHindsight()
    project, _ = await _setup(db, hs)
    records = await memory_service.list_records(db, project.id)
    base, _ = build_messages(project, "task", None)
    mem, block = build_messages(project, "task", records[:1])
    assert base[1] == mem[1]
    assert mem[0]["content"].startswith(base[0]["content"])
    assert block in mem[0]["content"] and "<project_memory>" not in base[0]["content"]
