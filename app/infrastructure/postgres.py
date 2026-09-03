"""PostgreSQL persistence for claim metadata and immutable audit events."""
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator
from sqlalchemy import DateTime, ForeignKey, JSON, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker
from app.core.config import settings


class Base(DeclarativeBase):
    pass


class ClaimRecord(Base):
    __tablename__ = "claims"
    claim_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    documents: Mapped[list["DocumentRecord"]] = relationship(back_populates="claim", cascade="all, delete-orphan")


class DocumentRecord(Base):
    __tablename__ = "claim_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.claim_id"), index=True)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    blob_uri: Mapped[str | None] = mapped_column(String(2048))
    detected_type: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    claim: Mapped[ClaimRecord] = relationship(back_populates="documents")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ReviewTaskRecord(Base):
    """Durable Human Review #1 task. The source document remains in Blob Storage."""
    __tablename__ = "review_tasks"
    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.claim_id"), index=True)
    stage: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="OPEN")
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    decision: Mapped[str | None] = mapped_column(String(50))
    reviewer_id: Mapped[str | None] = mapped_column(String(100))
    comment: Mapped[str | None] = mapped_column(String(2000))
    resumed_to: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def _session_factory() -> sessionmaker[Session]:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)


import logging

logger = logging.getLogger(__name__)


def initialize_database() -> None:
    """Create tables for a local proof-of-concept. Use Alembic migrations in deployment."""
    if not settings.database_url:
        return
    try:
        engine = create_engine(settings.database_url, pool_pre_ping=True)
        Base.metadata.create_all(engine)
    except Exception as exc:
        logger.warning("Could not connect to PostgreSQL database (%s). Persistence routes will require a running database.", exc)



@contextmanager
def session_scope() -> Generator[Session, None, None]:
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
