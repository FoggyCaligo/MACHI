from __future__ import annotations

import asyncio

from MK4.app.chat_jobs import ChatJobStore


def test_chat_job_is_owned_by_graph_user_and_keeps_completed_response() -> None:
    store = ChatJobStore(retention_seconds=3600)
    job = store.create(graph_user_id="alice")

    assert store.snapshot_for(job_id=job.job_id, graph_user_id="bob") is None

    store.mark_running(job.job_id)
    store.complete(job.job_id, {"text": "done", "used_tools": []})

    snapshot = store.snapshot_for(job_id=job.job_id, graph_user_id="alice")
    assert snapshot is not None
    assert snapshot["status"] == "completed"
    assert snapshot["response"]["text"] == "done"


def test_chat_job_failure_remains_explicit() -> None:
    store = ChatJobStore(retention_seconds=3600)
    job = store.create(graph_user_id="alice")
    store.fail(
        job.job_id,
        error="RuntimeError: boom",
        response={"detail": "RuntimeError: boom", "text": "[오류] RuntimeError: boom"},
    )

    snapshot = store.snapshot_for(job_id=job.job_id, graph_user_id="alice")
    assert snapshot is not None
    assert snapshot["status"] == "failed"
    assert snapshot["error"] == "RuntimeError: boom"
    assert snapshot["response"]["detail"] == "RuntimeError: boom"


def test_user_lock_serializes_jobs_for_same_graph_user() -> None:
    async def scenario() -> None:
        store = ChatJobStore(retention_seconds=3600)
        lock = store.lock_for("alice")
        order: list[str] = []

        async def first() -> None:
            async with lock:
                order.append("first-start")
                await asyncio.sleep(0)
                order.append("first-end")

        async def second() -> None:
            async with store.lock_for("alice"):
                order.append("second")

        await asyncio.gather(first(), second())
        assert order == ["first-start", "first-end", "second"]

    asyncio.run(scenario())
