"""Shared runtime helpers for background task runners.

Each helper opens its own short-lived session because task runners execute in
FastAPI BackgroundTasks, detached from any request-scoped session. Used by the
tasks router and the batch-OCR runners.
"""
from datetime import datetime
from contextlib import contextmanager
from contextvars import ContextVar

from ..database import SessionLocal
from ..models import Task, TaskLog

_captured_finishes: ContextVar[list[tuple[str, dict | None]] | None] = ContextVar(
    "captured_task_finishes", default=None
)


@contextmanager
def capture_finishes():
    """Capture nested runner completion so a parent pipeline remains running."""
    outcomes: list[tuple[str, dict | None]] = []
    token = _captured_finishes.set(outcomes)
    try:
        yield outcomes
    finally:
        _captured_finishes.reset(token)


def log_task(task_id: int, message: str, level: str = "info") -> None:
    db = SessionLocal()
    try:
        db.add(TaskLog(task_id=task_id, message=message, level=level))
        db.commit()
    finally:
        db.close()


def is_stopped(task_id: int) -> bool:
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        return task is None or task.status == "stopped"
    finally:
        db.close()


def set_progress(task_id: int, current: int, total: int) -> None:
    db = SessionLocal()
    try:
        db.query(Task).filter(Task.id == task_id).update(
            {"progress_current": current, "progress_total": total}
        )
        db.commit()
    finally:
        db.close()


def finish(task_id: int, status: str, result: dict | None = None) -> None:
    captured = _captured_finishes.get()
    if captured is not None:
        captured.append((status, result))
        return
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task and task.status != "stopped":
            task.status = status
            task.finished_at = datetime.utcnow()
            if result:
                task.result_summary = result
            db.commit()
    finally:
        db.close()
