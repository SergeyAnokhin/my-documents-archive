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
            "ALTER TABLE ai_providers ADD COLUMN task_type TEXT DEFAULT 'both'",
            "ALTER TABLE ai_providers ADD COLUMN sort_order INTEGER DEFAULT 0",
            "ALTER TABLE ai_providers ADD COLUMN total_tokens_in INTEGER DEFAULT 0",
            "ALTER TABLE ai_providers ADD COLUMN total_tokens_out INTEGER DEFAULT 0",
            "ALTER TABLE ai_providers ADD COLUMN total_cost_usd REAL DEFAULT 0.0",
            "ALTER TABLE ai_providers ADD COLUMN key_name TEXT",
            "ALTER TABLE ai_providers ADD COLUMN extra_params TEXT",
            "ALTER TABLE documents ADD COLUMN person_first_name TEXT",
            "ALTER TABLE documents ADD COLUMN person_last_name TEXT",
            "ALTER TABLE documents ADD COLUMN classification_confidence REAL",
            "ALTER TABLE documents ADD COLUMN classification_source TEXT",
            "ALTER TABLE documents ADD COLUMN manually_classified INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # column already exists
