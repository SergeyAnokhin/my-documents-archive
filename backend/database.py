"""Database setup and session management."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from backend.config import DATABASE_URL

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields SQLite session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and FTS5 index."""
    Base.metadata.create_all(bind=engine)

    # Create FTS5 virtual table for full-text search
    with engine.connect() as conn:
        conn.exec_driver_sql("""
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                original_filename,
                ocr_text,
                summary,
                tags,
                content='documents',
                content_rowid='rowid'
            )
        """)
        # Triggers to keep FTS in sync
        conn.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS docs_ai AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(rowid, original_filename, ocr_text, summary, tags)
                VALUES (new.rowid, new.original_filename, new.ocr_text, new.summary, new.tags);
            END
        """)
        conn.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS docs_ad AFTER DELETE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, original_filename, ocr_text, summary, tags)
                VALUES ('delete', old.rowid, old.original_filename, old.ocr_text, old.summary, old.tags);
            END
        """)
        conn.exec_driver_sql("""
            CREATE TRIGGER IF NOT EXISTS docs_au AFTER UPDATE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, original_filename, ocr_text, summary, tags)
                VALUES ('delete', old.rowid, old.original_filename, old.ocr_text, old.summary, old.tags);
                INSERT INTO documents_fts(rowid, original_filename, ocr_text, summary, tags)
                VALUES (new.rowid, new.original_filename, new.ocr_text, new.summary, new.tags);
            END
        """)
        conn.commit()


def rebuild_fts():
    """Rebuild FTS5 index from documents table. Use after bulk imports."""
    with engine.connect() as conn:
        conn.exec_driver_sql("DELETE FROM documents_fts")
        conn.exec_driver_sql("""
            INSERT INTO documents_fts(rowid, original_filename, ocr_text, summary, tags)
            SELECT rowid, original_filename, ocr_text, summary, tags FROM documents
        """)
        conn.commit()


def search_documents(query: str, limit: int = 50):
    """Full-text search across documents. Returns matching document IDs and snippets."""
    from sqlalchemy import text

    with engine.connect() as conn:
        # Use FTS5 with snippet highlighting
        result = conn.execute(
            text("""
                SELECT d.id, d.original_filename, d.ocr_text, d.summary, d.tags,
                       snippet(documents_fts, 2, '<mark>', '</mark>', '…', 32) as snippet
                FROM documents_fts fts
                JOIN documents d ON d.rowid = fts.rowid
                WHERE documents_fts MATCH :query
                ORDER BY rank
                LIMIT :limit
            """),
            {"query": query, "limit": limit}
        )
        return [
            {
                "id": row[0],
                "original_filename": row[1],
                "ocr_text": row[2],
                "summary": row[3],
                "tags": row[4],
                "snippet": row[5],
            }
            for row in result
        ]
