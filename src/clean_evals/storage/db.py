"""SQLAlchemy ORM models and engine bootstrapping.

Schema (portable across MySQL 8 and Postgres 16):

- ``datasets`` — name, version, scorer, scorer_config, locked_at.
- ``cases`` — input/expected/tags JSON, lock flag, optimistic-concurrency
  ``rev`` counter for the Dataset Builder's editable rows.
- ``runs`` — config, dataset version, status, summary JSON, artifact URI,
  pricing version, triggered_by source.
- ``case_results`` — per ``(case, model)`` row, lightweight (no full raw
  body — that lives in the artifact store).
- ``schedules`` — per-dataset cron, enable flag, last/next run timestamps.

Indices live on the foreign keys plus ``(name, version)`` on ``datasets``
and ``(dataset_id, status)`` on ``runs``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Engine,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)


def _utcnow() -> datetime:
    """Timezone-aware replacement for the deprecated ``datetime.utcnow``."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base — common type metadata for every ORM class."""

    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSON}


class DatasetRow(Base):
    __tablename__ = "datasets"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_datasets_name_version"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    version: Mapped[str] = mapped_column(String(40))
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    scorer: Mapped[str] = mapped_column(String(100))
    scorer_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Prompt spec — how a case becomes a model request. "raw" sends each
    # case's single field verbatim; "templated" assembles system prompt +
    # context + variables per the golden-path flow (docs/docs/flow.md).
    request_shape: Mapped[str] = mapped_column(String(20), default="raw", nullable=False)
    system_prompt: Mapped[str | None] = mapped_column(Text(), nullable=True)
    shared_context: Mapped[str | None] = mapped_column(Text(), nullable=True)
    user_template: Mapped[str | None] = mapped_column(Text(), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    cases: Mapped[list[CaseRow]] = relationship(
        "CaseRow", back_populates="dataset", cascade="all, delete-orphan"
    )
    runs: Mapped[list[RunRow]] = relationship(
        "RunRow", back_populates="dataset", cascade="all, delete-orphan"
    )
    schedules: Mapped[list[ScheduleRow]] = relationship(
        "ScheduleRow", back_populates="dataset", cascade="all, delete-orphan"
    )
    judge_configs: Mapped[list[JudgeConfigRow]] = relationship(
        "JudgeConfigRow", back_populates="dataset", cascade="all, delete-orphan"
    )


class CaseRow(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    case_id_external: Mapped[str] = mapped_column(String(200))
    input_jsonb: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    expected_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    tags_jsonb: Mapped[list[str]] = mapped_column(JSON, default=list)
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    metadata_jsonb: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rev: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    dataset: Mapped[DatasetRow] = relationship("DatasetRow", back_populates="cases")
    candidates: Mapped[list[CandidateOutputRow]] = relationship(
        "CandidateOutputRow", back_populates="case", cascade="all, delete-orphan"
    )


class CandidateOutputRow(Base):
    """Stage 2 — one model's output for one case, before any golden answer exists."""

    __tablename__ = "candidate_outputs"
    __table_args__ = (UniqueConstraint("case_id", "model", name="uq_candidates_case_model"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(120), index=True)
    content: Mapped[str] = mapped_column(Text())
    parsed_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ok")  # ok|error|timeout
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    case: Mapped[CaseRow] = relationship("CaseRow", back_populates="candidates")
    rating: Mapped[RatingRow | None] = relationship(
        "RatingRow", back_populates="candidate", uselist=False, cascade="all, delete-orphan"
    )


class RatingRow(Base):
    """Stage 3 — a human review of one candidate output: 1–5 plus feedback."""

    __tablename__ = "ratings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    candidate_output_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_outputs.id", ondelete="CASCADE"), unique=True, index=True
    )
    rating: Mapped[int] = mapped_column(Integer)  # 1..5
    feedback: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    candidate: Mapped[CandidateOutputRow] = relationship(
        "CandidateOutputRow", back_populates="rating"
    )


class JudgeConfigRow(Base):
    """Stage 4 — a versioned, calibrated judge standard for a dataset."""

    __tablename__ = "judge_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    judge_model: Mapped[str] = mapped_column(String(120))
    rubric: Mapped[str] = mapped_column(Text())
    few_shot_jsonb: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    agreement_jsonb: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    dataset: Mapped[DatasetRow] = relationship("DatasetRow", back_populates="judge_configs")


class RunRow(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    dataset_version: Mapped[str] = mapped_column(String(40))
    config_jsonb: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), index=True)  # queued|running|done|aborted|error
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary_jsonb: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    artifact_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pricing_version: Mapped[str] = mapped_column(String(20))
    triggered_by: Mapped[str] = mapped_column(String(40), default="cli")  # cli|web|schedule|api
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    dataset: Mapped[DatasetRow] = relationship("DatasetRow", back_populates="runs")
    case_results: Mapped[list[CaseResultRow]] = relationship(
        "CaseResultRow", back_populates="run", cascade="all, delete-orphan"
    )


class CaseResultRow(Base):
    __tablename__ = "case_results"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    case_id: Mapped[str] = mapped_column(String(200), index=True)
    model: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(20))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    response_jsonb: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[RunRow] = relationship("RunRow", back_populates="case_results")


class ScheduleRow(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), index=True
    )
    cron: Mapped[str] = mapped_column(String(80))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config_jsonb: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    dataset: Mapped[DatasetRow] = relationship("DatasetRow", back_populates="schedules")


# ---------------------------------------------------------------------------
# Engine / session helpers
# ---------------------------------------------------------------------------


DEFAULT_SQLITE_PATH = Path("./clean-evals-data/clean_evals.sqlite")


def create_engine_from_env(url: str | None = None) -> Engine:
    """Create an Engine from ``CLEAN_EVALS_DATABASE_URL``, or default to SQLite.

    Zero-config default: a local SQLite file under ``./clean-evals-data/``.
    Set the env var to use MySQL or Postgres — e.g.
    ``mysql+pymysql://user:pass@localhost:3306/clean_evals``.
    """
    db_url = url or os.environ.get("CLEAN_EVALS_DATABASE_URL")
    if not db_url:
        DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{DEFAULT_SQLITE_PATH.as_posix()}"
    connect_args: dict[str, Any] = {}
    if db_url.startswith("sqlite"):
        # The web app touches sessions from request threads and background
        # tasks; SQLite's per-thread default would reject that.
        connect_args["check_same_thread"] = False
    # pool_pre_ping: MySQL needs stale-connection survival behind LBs.
    engine = create_engine(
        db_url,
        future=True,
        pool_pre_ping=True,
        json_serializer=_json_default,
        connect_args=connect_args,
    )
    if db_url.startswith("sqlite"):
        # WAL lets readers proceed during writes; busy_timeout waits out
        # short write-lock contention instead of raising "database is
        # locked". Both matter because request threads and background run
        # threads share one file.
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def _json_default(obj: Any) -> str:
    """Default JSON serialiser that handles datetime."""
    import json
    from datetime import date

    def _enc(x: Any) -> Any:
        if isinstance(x, (datetime, date)):
            return x.isoformat()
        raise TypeError(f"Object of type {type(x).__name__} is not JSON serializable")

    return json.dumps(obj, default=_enc, ensure_ascii=False)


_session_local: sessionmaker[Session] | None = None


def session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Singleton ``sessionmaker``. Lazily builds the engine on first call."""
    global _session_local
    if _session_local is None:
        eng = engine or create_engine_from_env()
        _session_local = sessionmaker(bind=eng, expire_on_commit=False, autoflush=False)
    return _session_local


@contextmanager
def session_scope() -> Iterator[Session]:
    """Standard transaction-managed session scope."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
