from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db import Base

UUID_TYPE = String(36)
JSON_TYPE = JSON


def uuid_pk() -> Mapped[str]:
    return mapped_column(UUID_TYPE, primary_key=True)


def json_object() -> Mapped[dict[str, Any]]:
    return mapped_column(JSON_TYPE, nullable=False, default=dict, server_default="{}")


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = uuid_pk()
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LlmProvider(Base):
    """A user-managed AI provider: endpoint configuration, encrypted credentials, and defaults."""

    __tablename__ = "llm_providers"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[str] = uuid_pk()
    user_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    provider_type: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict[str, Any]] = json_object()
    encrypted_secrets: Mapped[str | None] = mapped_column(Text)
    models_json: Mapped[list[str]] = mapped_column(
        JSON_TYPE, nullable=False, default=list, server_default="[]"
    )
    default_model: Mapped[str] = mapped_column(Text, nullable=False)
    default_reasoning_effort: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = uuid_pk()
    case_key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    issue_description: Mapped[str | None] = mapped_column(Text)
    product: Mapped[str | None] = mapped_column(Text)
    service: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str | None] = mapped_column(Text)
    incident_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    incident_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="UTC")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="created")
    created_by: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawFile(Base):
    __tablename__ = "raw_files"

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    object_uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str | None] = mapped_column(Text)
    upload_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (UniqueConstraint("case_id", "run_number"),)

    id: Mapped[str] = uuid_pk()
    case_id: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("cases.id"), nullable=False)
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    model_provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(Text, nullable=False)
    llm_provider_id: Mapped[str | None] = mapped_column(
        UUID_TYPE, ForeignKey("llm_providers.id", ondelete="SET NULL")
    )
    llm_provider_name: Mapped[str | None] = mapped_column(Text)
    reasoning_effort: Mapped[str | None] = mapped_column(Text)
    progress_json: Mapped[dict[str, Any]] = json_object()
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON_TYPE)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(UUID_TYPE, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
