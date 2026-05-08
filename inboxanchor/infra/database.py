from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from inboxanchor.config.settings import SETTINGS


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TriageRunORM(Base):
    __tablename__ = "triage_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    total_emails: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    digest_summary: Mapped[str] = mapped_column(Text, default="")
    approvals_required: Mapped[list[str]] = mapped_column(JSON, default=list)
    blocked_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)

    emails: Mapped[list[EmailRecordORM]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )
    recommendations: Mapped[list[RecommendationORM]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class EmailRecordORM(Base):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("triage_runs.run_id"))
    email_id: Mapped[str] = mapped_column(String(128))
    thread_id: Mapped[str] = mapped_column(String(128))
    sender: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str] = mapped_column(Text)
    snippet: Mapped[str] = mapped_column(Text)
    body_preview: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    labels: Mapped[list[str]] = mapped_column(JSON, default=list)
    has_attachments: Mapped[bool] = mapped_column(Boolean, default=False)
    unread: Mapped[bool] = mapped_column(Boolean, default=True)

    run: Mapped[TriageRunORM] = relationship(back_populates="emails")


class ClassificationORM(Base):
    __tablename__ = "classifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    email_id: Mapped[str] = mapped_column(String(128), index=True)
    category: Mapped[str] = mapped_column(String(32))
    priority: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)


class ActionItemORM(Base):
    __tablename__ = "action_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    email_id: Mapped[str] = mapped_column(String(128), index=True)
    action_type: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    due_hint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    requires_reply: Mapped[bool] = mapped_column(Boolean, default=False)


class RecommendationORM(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("triage_runs.run_id"))
    email_id: Mapped[str] = mapped_column(String(128), index=True)
    recommended_action: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32))
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    blocked_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    proposed_labels: Mapped[list[str]] = mapped_column(JSON, default=list)

    run: Mapped[TriageRunORM] = relationship(back_populates="recommendations")


class AuditLogORM(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_id: Mapped[str] = mapped_column(String(128), index=True)
    proposed_action: Mapped[str] = mapped_column(String(64))
    final_action: Mapped[str] = mapped_column(String(64))
    approved_by_user: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    reason: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    agent_decision: Mapped[str] = mapped_column(Text)
    safety_verifier_status: Mapped[str] = mapped_column(String(32))


class WorkspaceSettingsORM(Base):
    __tablename__ = "workspace_settings"

    workspace_id: Mapped[str] = mapped_column(String(32), primary_key=True, default="default")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ProviderConnectionORM(Base):
    __tablename__ = "provider_connections"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ProviderCheckpointORM(Base):
    __tablename__ = "provider_checkpoints"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    checkpoint_value: Mapped[str] = mapped_column(String(255))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


def _fallback_sqlite_url() -> str:
    app_dir = Path(
        os.getenv(
            "INBOXANCHOR_DATA_DIR",
            str(Path(tempfile.gettempdir()) / "inboxanchor"),
        )
    )
    app_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{app_dir / 'inboxanchor.db'}"


def _resolve_database_url(raw_url: str) -> str:
    if not raw_url.startswith("sqlite:///"):
        return raw_url

    sqlite_path = raw_url[len("sqlite:///") :]
    candidate = Path(sqlite_path).expanduser()
    if not candidate.is_absolute():
        return _fallback_sqlite_url()

    target = candidate.parent if candidate.exists() else candidate.parent
    if not target.exists():
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError:
            return _fallback_sqlite_url()

    if candidate.exists() and not candidate.is_file():
        return _fallback_sqlite_url()
    if candidate.exists() and not os.access(candidate, os.W_OK):
        return _fallback_sqlite_url()
    if not os.access(target, os.W_OK):
        return _fallback_sqlite_url()
    return f"sqlite:///{candidate}"


RESOLVED_DATABASE_URL = _resolve_database_url(SETTINGS.database_url)
engine = create_engine(
    RESOLVED_DATABASE_URL,
    future=True,
    connect_args=(
        {"check_same_thread": False}
        if RESOLVED_DATABASE_URL.startswith("sqlite:///")
        else {}
    ),
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
