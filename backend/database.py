"""
MediaVault - Database Layer
SQLite with WAL mode, SQLAlchemy ORM models, FTS5 virtual table.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Column, Integer, String, Boolean, Float, Text, DateTime, ForeignKey,
    create_engine, event, text,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

from backend.config import DB_PATH, logger

Base = declarative_base()


# ════════════════════════════════════════════
# ORM Models
# ════════════════════════════════════════════

class Workspace(Base):
    __tablename__ = "workspaces"
    id = Column(Integer, primary_key=True, autoincrement=True)
    absolute_path = Column(String, unique=True, nullable=False)
    alias = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    files = relationship("File", back_populates="workspace", cascade="all, delete-orphan")


class File(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True, autoincrement=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    relative_path = Column(String, nullable=False)
    filename = Column(String, nullable=False)
    extension = Column(String, nullable=False)
    size = Column(Integer, default=0)
    is_favorite = Column(Boolean, default=False)
    media_type = Column(String, nullable=False)  # 'image' | 'video'

    # Dimensions
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)

    # Video-specific metadata
    duration = Column(Float, nullable=True)
    fps = Column(Float, nullable=True)
    codec = Column(String, nullable=True)
    bitrate = Column(Integer, nullable=True)

    # Tracking
    file_hash = Column(String, nullable=True)
    media_created_at = Column(DateTime, nullable=True)
    thumbnail_path = Column(String, nullable=True)
    sync_status = Column(String, default="synced")  # synced | pending_write | failed
    retry_count = Column(Integer, default=0)
    phash = Column(String, nullable=True)
    last_indexed = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, default=False)  # Soft delete
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    workspace = relationship("Workspace", back_populates="files")
    file_tags = relationship("FileTag", back_populates="file", cascade="all, delete-orphan")


class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    file_tags = relationship("FileTag", back_populates="tag", cascade="all, delete-orphan")


class FileTag(Base):
    __tablename__ = "file_tags"
    id = Column(Integer, primary_key=True, autoincrement=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    tag_id = Column(Integer, ForeignKey("tags.id"), nullable=False)
    confidence_score = Column(Float, nullable=True)
    source = Column(String, default="manual")  # manual | ai
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    file = relationship("File", back_populates="file_tags")
    tag = relationship("Tag", back_populates="file_tags")


# ════════════════════════════════════════════
# Engine & Session
# ════════════════════════════════════════════

DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    """Enable WAL mode and performance pragmas on every new connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=NORMAL;")
    cursor.execute("PRAGMA temp_store=MEMORY;")
    cursor.execute("PRAGMA mmap_size=268435456;")  # 256MB mmap
    cursor.execute("PRAGMA cache_size=-64000;")  # 64MB cache
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Dependency for FastAPI to get a DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables and FTS5 virtual table."""
    Base.metadata.create_all(bind=engine)

    # Create FTS5 virtual table for tag search
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS tags_fts USING fts5(
                name,
                content='tags',
                content_rowid='id'
            );
        """))
        # Triggers to keep FTS5 in sync with tags table
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS tags_ai AFTER INSERT ON tags BEGIN
                INSERT INTO tags_fts(rowid, name) VALUES (new.id, new.name);
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS tags_ad AFTER DELETE ON tags BEGIN
                INSERT INTO tags_fts(tags_fts, rowid, name) VALUES('delete', old.id, old.name);
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS tags_au AFTER UPDATE ON tags BEGIN
                INSERT INTO tags_fts(tags_fts, rowid, name) VALUES('delete', old.id, old.name);
                INSERT INTO tags_fts(rowid, name) VALUES (new.id, new.name);
            END;
        """))
        # FTS5 for filenames
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                filename,
                relative_path,
                content='files',
                content_rowid='id'
            );
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS files_fts_ai AFTER INSERT ON files BEGIN
                INSERT INTO files_fts(rowid, filename, relative_path) VALUES (new.id, new.filename, new.relative_path);
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS files_fts_ad AFTER DELETE ON files BEGIN
                INSERT INTO files_fts(files_fts, rowid, filename, relative_path) VALUES('delete', old.id, old.filename, old.relative_path);
            END;
        """))
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS files_fts_au AFTER UPDATE ON files BEGIN
                INSERT INTO files_fts(files_fts, rowid, filename, relative_path) VALUES('delete', old.id, old.filename, old.relative_path);
                INSERT INTO files_fts(rowid, filename, relative_path) VALUES (new.id, new.filename, new.relative_path);
            END;
        """))
        conn.commit()

    logger.info("Database initialized at %s", DB_PATH)
