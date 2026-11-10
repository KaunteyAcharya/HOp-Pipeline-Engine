"""SQLAlchemy models. Every operator-derived fact keeps provenance; synthetic rows are flagged."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    command: Mapped[str] = mapped_column(String(50))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    demo: Mapped[bool] = mapped_column(Boolean, default=False)
    stats: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Operator(Base):
    """A resolved (deduplicated) STR operator."""

    __tablename__ = "operators"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    domain: Mapped[str | None] = mapped_column(String(255), index=True)
    country: Mapped[str | None] = mapped_column(String(2))
    cities: Mapped[list[Any]] = mapped_column(default=list)
    listing_count: Mapped[int | None] = mapped_column(Integer)
    pms: Mapped[list[Any]] = mapped_column(default=list)
    direct_booking: Mapped[bool | None] = mapped_column(Boolean)
    instagram_handle: Mapped[str | None] = mapped_column(String(100))
    linkedin_company_url: Mapped[str | None] = mapped_column(String(300))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sources: Mapped[list[OperatorSource]] = relationship(back_populates="operator", cascade="all, delete-orphan")
    evidence: Mapped[list[Evidence]] = relationship(back_populates="operator", cascade="all, delete-orphan")
    signals: Mapped[list[Signal]] = relationship(back_populates="operator", cascade="all, delete-orphan")
    contacts: Mapped[list[Contact]] = relationship(back_populates="operator", cascade="all, delete-orphan")
    scores: Mapped[list[Score]] = relationship(back_populates="operator", cascade="all, delete-orphan")


class OperatorSource(Base):
    """One raw record from one collector, linked to its resolved operator."""

    __tablename__ = "operator_sources"
    __table_args__ = (UniqueConstraint("source", "source_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("operators.id"), index=True)
    source: Mapped[str] = mapped_column(String(50))  # inside_airbnb, permit, web_search, list_import, synthetic
    source_key: Mapped[str] = mapped_column(String(300))  # e.g. host_id, permit operator name
    source_url: Mapped[str | None] = mapped_column(String(500))
    snapshot: Mapped[str | None] = mapped_column(String(50))  # dataset date / file name
    raw: Mapped[dict[str, Any]] = mapped_column(default=dict)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    operator: Mapped[Operator | None] = relationship(back_populates="sources")


class FieldProvenance(Base):
    __tablename__ = "field_provenance"
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"), index=True)
    field: Mapped[str] = mapped_column(String(50))
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(50))
    source_url: Mapped[str | None] = mapped_column(String(500))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Evidence(Base):
    """A citable observation (used by scoring explanations and research briefs)."""

    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50))  # pms, listing_count, direct_booking, hiring, page, social
    claim: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(String(500))
    snippet: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    operator: Mapped[Operator] = relationship(back_populates="evidence")


class Signal(Base):
    __tablename__ = "signals"
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"), index=True)
    kind: Mapped[str] = mapped_column(String(50))  # hiring, listing_growth, direct_booking
    value: Mapped[float] = mapped_column(Float, default=1.0)
    detail: Mapped[str | None] = mapped_column(Text)
    evidence_id: Mapped[int | None] = mapped_column(ForeignKey("evidence.id"))
    operator: Mapped[Operator] = relationship(back_populates="signals")


class Score(Base):
    __tablename__ = "scores"
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"), index=True)
    total: Mapped[float] = mapped_column(Float)
    tier: Mapped[str] = mapped_column(String(1))
    breakdown: Mapped[list[Any]] = mapped_column(default=list)  # [{factor, points, reason, evidence_ids}]
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    operator: Mapped[Operator] = relationship(back_populates="scores")


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"), index=True)
    full_name: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254), index=True)
    email_status: Mapped[str | None] = mapped_column(String(30))  # verified only is stored
    email_source: Mapped[str | None] = mapped_column(String(50))
    linkedin_search_url: Mapped[str | None] = mapped_column(String(500))
    country: Mapped[str | None] = mapped_column(String(2))
    compliance_regime: Mapped[str | None] = mapped_column(String(30))
    lawful_basis_note: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    operator: Mapped[Operator] = relationship(back_populates="contacts")


class Hook(Base):
    __tablename__ = "hooks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)  # hook_id for A/B tracking
    segment: Mapped[str] = mapped_column(String(100))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Draft(Base):
    __tablename__ = "drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    channel: Mapped[str] = mapped_column(String(30))  # linkedin_note, linkedin_followup, email_1..3, instagram_dm
    hook_id: Mapped[str | None] = mapped_column(ForeignKey("hooks.id"))
    subject: Mapped[str | None] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    brief: Mapped[dict[str, Any]] = mapped_column(default=dict)
    validation_errors: Mapped[list[Any]] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, approved, rejected, edited
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Task(Base):
    """Manual task (LinkedIn / Instagram). The system never performs these."""

    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("drafts.id"))
    channel: Mapped[str] = mapped_column(String(30))
    due_date: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), default="todo")


class OutreachEvent(Base):
    """Manually logged status: sent, replied, positive, demo_booked, demo_held."""

    __tablename__ = "outreach_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    operator_id: Mapped[int] = mapped_column(ForeignKey("operators.id"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"))
    channel: Mapped[str] = mapped_column(String(30))
    list_name: Mapped[str | None] = mapped_column(String(100))
    hook_id: Mapped[str | None] = mapped_column(String(40))
    event: Mapped[str] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Suppression(Base):
    __tablename__ = "suppression"
    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(String(254), unique=True)  # email, domain or handle (lowercased)
    kind: Mapped[str] = mapped_column(String(20))  # email, domain, handle
    reason: Mapped[str] = mapped_column(String(100))  # opt_out, do_not_contact, bounced, customer
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SendingDomain(Base):
    __tablename__ = "sending_domains"
    id: Mapped[int] = mapped_column(primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), unique=True)
    last_check: Mapped[dict[str, Any]] = mapped_column(default=dict)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreditLedger(Base):
    __tablename__ = "api_credit_ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id"))
    provider: Mapped[str] = mapped_column(String(30))
    credits: Mapped[float] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(200))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CallInsight(Base):
    __tablename__ = "call_insights"
    id: Mapped[int] = mapped_column(primary_key=True)
    transcript_name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))  # objection, pain, phrase
    text: Mapped[str] = mapped_column(Text)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
