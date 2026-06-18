from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from pathlib import Path
from .config import settings


def get_engine():
    db_dir = Path(settings.db_path).parent
    db_dir.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{settings.db_path}",
        connect_args={"check_same_thread": False},
    )


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401 — triggers model registration
    Base.metadata.create_all(bind=engine)
    _apply_migrations(engine)


def _apply_migrations(eng) -> None:
    """Add new columns to existing tables without Alembic. Idempotent."""
    with eng.connect() as conn:
        for stmt in [
            "ALTER TABLE ai_providers ADD COLUMN model TEXT",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # column already exists
