"""Pins startup recovery of orphaned "running" tasks — see docs/batch-ocr.md
§Resume support and docs/code-map.md (routers/tasks.py: recover_running_tasks).

A background runner is just an in-process asyncio coroutine (FastAPI
BackgroundTasks, no separate worker) — a pod restart kills it mid-flight
without ever updating the Task row, leaving it stuck at status="running"
forever. `recover_running_tasks()` runs once at app startup (see main.py) to
fix that: batch tasks with a remote job already submitted are auto-resumed
(the remote job survives on the provider's servers); everything else is reset
to "stopped" so the Run/Resume buttons work again.

Each test carries:
  Doc:  which documented area it protects
  Rule: the specific behavior it asserts
"""
import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Task
from app.routers import tasks as tasks_module


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(tasks_module, "SessionLocal", TestSessionLocal)
    yield TestSessionLocal


@pytest.fixture
def resume_calls(monkeypatch):
    calls = []

    async def _fake_run_task_bg(task_id, task_type, config):
        calls.append((task_id, task_type, config))

    monkeypatch.setattr(tasks_module, "_run_task_bg", _fake_run_task_bg)
    # _log writes via the real app.database engine — stub it out so the
    # recovery sweep stays hermetic to the test's temp sqlite file.
    monkeypatch.setattr(tasks_module, "_log", lambda *a, **k: None)
    return calls


def _run_recovery():
    async def _drive():
        await tasks_module.recover_running_tasks()
        await asyncio.sleep(0)  # let the scheduled create_task() coroutines run
    asyncio.run(_drive())


def test_resumes_batch_task_with_remote_job_id(db_session, resume_calls):
    # Doc:  docs/batch-ocr.md §Resume support — "POST /resume-batch restarts
    #       polling for a stopped or interrupted job without re-submitting it."
    # Rule: a batch task left "running" with a saved batch_job_id is
    #       auto-resumed with that id, not reset to "stopped".
    db = db_session()
    task = Task(
        task_type="batch_ocr_mistral", title="t", status="running",
        config={"limit": 50}, result_summary={"batch_job_id": "job-123", "phase": "polling"},
    )
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    _run_recovery()

    assert len(resume_calls) == 1
    resumed_id, task_type, config = resume_calls[0]
    assert resumed_id == task_id
    assert task_type == "batch_ocr_mistral"
    assert config["resume_batch_job_id"] == "job-123"
    assert config["limit"] == 50

    db = db_session()
    refreshed = db.query(Task).filter(Task.id == task_id).first()
    assert refreshed.status == "running"
    db.close()


def test_stops_batch_task_without_remote_job_id(db_session, resume_calls):
    # Doc:  docs/batch-ocr.md §Resume support — resume needs a saved
    #       batch_job_id; without one there is nothing remote to reconnect to.
    # Rule: a batch task that crashed before the job id was saved is reset to
    #       "stopped" instead of being left stuck at "running" forever.
    db = db_session()
    task = Task(task_type="batch_ocr_mistral", title="t", status="running", result_summary=None)
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    _run_recovery()

    assert resume_calls == []
    db = db_session()
    refreshed = db.query(Task).filter(Task.id == task_id).first()
    assert refreshed.status == "stopped"
    assert refreshed.finished_at is not None
    db.close()


def test_stops_non_batch_task(db_session, resume_calls):
    # Doc:  docs/code-map.md — recover_running_tasks: "Everything else is
    #       reset to stopped so the user can manually re-run it."
    # Rule: non-batch task types (no remote job concept) are reset to
    #       "stopped" on recovery rather than auto-resumed.
    db = db_session()
    task = Task(task_type="index_unindexed", title="t", status="running")
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    _run_recovery()

    assert resume_calls == []
    db = db_session()
    refreshed = db.query(Task).filter(Task.id == task_id).first()
    assert refreshed.status == "stopped"
    db.close()


def test_leaves_non_running_tasks_untouched(db_session, resume_calls):
    # Rule: tasks that aren't "running" (done/idle/error/stopped) are not
    #       touched by the recovery sweep.
    db = db_session()
    task = Task(task_type="batch_ocr_mistral", title="t", status="done")
    db.add(task)
    db.commit()
    task_id = task.id
    db.close()

    _run_recovery()

    assert resume_calls == []
    db = db_session()
    refreshed = db.query(Task).filter(Task.id == task_id).first()
    assert refreshed.status == "done"
    db.close()
