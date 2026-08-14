"""Long-term memory for the Chief of Staff agent.

Backed by SQLite by default (see ``database/schema.sql`` for a
human-readable reference schema) via SQLAlchemy's async engine, so moving
to Postgres later is a connection-string change — see
``docs/DEPLOYMENT.md``.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings

logger = logging.getLogger("agent.memory")


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# ORM models (mirrors database/schema.sql)
# ---------------------------------------------------------------------------


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(200), default=None)
    relationship_label: Mapped[Optional[str]] = mapped_column(String(100), default=None)
    importance_score: Mapped[float] = mapped_column(Float, default=0.5)
    notes: Mapped[Optional[str]] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Preference(Base):
    __tablename__ = "preferences"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("channel", "external_conversation_id", name="uq_channel_conversation"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel: Mapped[str] = mapped_column(String(50))
    external_conversation_id: Mapped[str] = mapped_column(String(300))
    contact_id: Mapped[Optional[int]] = mapped_column(ForeignKey("contacts.id"), default=None)
    subject: Mapped[Optional[str]] = mapped_column(String(500), default=None)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    direction: Mapped[str] = mapped_column(String(10))  # "inbound" | "outbound"
    channel: Mapped[str] = mapped_column(String(50))
    sender: Mapped[str] = mapped_column(String(320))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ApprovedResponsePattern(Base):
    __tablename__ = "approved_response_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pattern_description: Mapped[str] = mapped_column(Text)
    example_input: Mapped[str] = mapped_column(Text)
    response_template: Mapped[str] = mapped_column(Text)
    times_approved: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    description: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DecisionLog(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("conversations.id"), default=None
    )
    decision: Mapped[str] = mapped_column(String(50))
    urgency_score: Mapped[Optional[float]] = mapped_column(Float, default=None)
    reasoning: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    approval_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    conversation_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("conversations.id"), default=None
    )
    draft_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    final_text: Mapped[Optional[str]] = mapped_column(Text, default=None)
    requested_via: Mapped[str] = mapped_column(String(50), default="telegram")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=None)


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class Memory:
    """Everything else in the app talks to this, never to the ORM directly."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        settings = get_settings()
        self._engine = create_async_engine(database_url or settings.database_url, echo=False)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("memory store initialised (%s)", self._engine.url)

    async def close(self) -> None:
        await self._engine.dispose()

    def session(self) -> AsyncSession:
        return self._session_factory()

    # -- contacts -----------------------------------------------------------
    async def get_or_create_contact(self, email: str, name: Optional[str] = None) -> Contact:
        async with self.session() as session:
            result = await session.execute(select(Contact).where(Contact.email == email))
            contact = result.scalar_one_or_none()
            if contact is None:
                contact = Contact(email=email, name=name)
                session.add(contact)
                await session.commit()
                await session.refresh(contact)
            elif name and not contact.name:
                contact.name = name
                await session.commit()
            return contact

    async def set_contact_importance(
        self, contact_id: int, score: float, notes: Optional[str] = None
    ) -> None:
        score = max(0.0, min(1.0, score))
        async with self.session() as session:
            values: dict[str, Any] = {"importance_score": score}
            if notes is not None:
                values["notes"] = notes
            await session.execute(update(Contact).where(Contact.id == contact_id).values(**values))
            await session.commit()

    # -- preferences ----------------------------------------------------------
    async def get_preference(self, key: str, default: Optional[str] = None) -> Optional[str]:
        async with self.session() as session:
            result = await session.execute(select(Preference).where(Preference.key == key))
            pref = result.scalar_one_or_none()
            return pref.value if pref else default

    async def get_all_preferences(self) -> dict[str, str]:
        async with self.session() as session:
            result = await session.execute(select(Preference))
            return {p.key: p.value for p in result.scalars().all()}

    async def set_preference(self, key: str, value: str) -> None:
        async with self.session() as session:
            result = await session.execute(select(Preference).where(Preference.key == key))
            pref = result.scalar_one_or_none()
            if pref:
                pref.value = value
            else:
                session.add(Preference(key=key, value=value))
            await session.commit()

    # -- conversations & messages ---------------------------------------------
    async def get_or_create_conversation(
        self,
        channel: str,
        external_conversation_id: str,
        contact_id: Optional[int] = None,
        subject: Optional[str] = None,
    ) -> Conversation:
        async with self.session() as session:
            result = await session.execute(
                select(Conversation).where(
                    Conversation.channel == channel,
                    Conversation.external_conversation_id == external_conversation_id,
                )
            )
            conversation = result.scalar_one_or_none()
            if conversation is None:
                conversation = Conversation(
                    channel=channel,
                    external_conversation_id=external_conversation_id,
                    contact_id=contact_id,
                    subject=subject,
                )
                session.add(conversation)
                await session.commit()
                await session.refresh(conversation)
            return conversation

    async def get_conversation_by_id(self, conversation_id: int) -> Optional[Conversation]:
        async with self.session() as session:
            result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
            return result.scalar_one_or_none()

    async def log_message(
        self, conversation_id: int, direction: str, channel: str, sender: str, text: str
    ) -> None:
        async with self.session() as session:
            session.add(
                Message(
                    conversation_id=conversation_id,
                    direction=direction,
                    channel=channel,
                    sender=sender,
                    text=text,
                )
            )
            await session.commit()

    async def get_recent_messages(self, conversation_id: int, limit: int = 10) -> Sequence[Message]:
        async with self.session() as session:
            result = await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc(),Message.id.desc())
                .limit(limit)
            )
            return list(reversed(result.scalars().all()))

    # -- learned response patterns ---------------------------------------------
    async def find_similar_approved_pattern(
        self, category: str
    ) -> Optional[ApprovedResponsePattern]:
        # Keyword match for the hackathon; swap for an embeddings lookup later.
        async with self.session() as session:
            result = await session.execute(
                select(ApprovedResponsePattern)
                .where(ApprovedResponsePattern.pattern_description.ilike(f"%{category}%"))
                .order_by(ApprovedResponsePattern.times_approved.desc())
            )
            return result.scalars().first()

    async def record_approved_pattern(
        self, description: str, example_input: str, response_template: str
    ) -> None:
        async with self.session() as session:
            session.add(
                ApprovedResponsePattern(
                    pattern_description=description,
                    example_input=example_input,
                    response_template=response_template,
                )
            )
            await session.commit()

    # -- decisions log (explainability) ------------------------------------------
    async def log_decision(
        self,
        conversation_id: Optional[int],
        decision: str,
        urgency_score: Optional[float],
        reasoning: str,
    ) -> None:
        async with self.session() as session:
            session.add(
                DecisionLog(
                    conversation_id=conversation_id,
                    decision=decision,
                    urgency_score=urgency_score,
                    reasoning=reasoning,
                )
            )
            await session.commit()

    # -- approvals -----------------------------------------------------------------
    async def create_approval(
        self, conversation_id: Optional[int], draft_text: str, requested_via: str = "telegram"
        #external_conversation_id: Optional[str] = None   
    ) -> Approval:
        code = secrets.token_hex(4).upper()  # e.g. "9F3A2B10" — short enough to type back
        async with self.session() as session:
            approval = Approval(
                approval_code=code,
                conversation_id=conversation_id,
                draft_text=draft_text,
                requested_via=requested_via,
            )
            session.add(approval)
            await session.commit()
            await session.refresh(approval)
            return approval

    async def get_pending_approval_by_code(self, code: str) -> Optional[Approval]:
        async with self.session() as session:
            result = await session.execute(
                select(Approval).where(
                    Approval.approval_code == code.upper(), Approval.status == "pending"
                )
            )
            return result.scalar_one_or_none()

    async def resolve_approval(
        self, code: str, status: str, final_text: Optional[str] = None
    ) -> Optional[Approval]:
        async with self.session() as session:
            result = await session.execute(select(Approval).where(Approval.approval_code == code.upper()))
            approval = result.scalar_one_or_none()
            if approval is None:
                return None
            approval.status = status
            approval.final_text = final_text
            approval.resolved_at = _now()
            await session.commit()
            await session.refresh(approval)
            return approval

    # -- daily summary --------------------------------------------------------------
    async def get_daily_summary_data(self, since: datetime) -> dict[str, list[Any]]:
        async with self.session() as session:
            msgs = await session.execute(select(Message).where(Message.created_at >= since))
            decisions = await session.execute(select(DecisionLog).where(DecisionLog.created_at >= since))
            pending = await session.execute(select(Approval).where(Approval.status == "pending"))
            return {
                "messages": list(msgs.scalars().all()),
                "decisions": list(decisions.scalars().all()),
                "pending_approvals": list(pending.scalars().all()),
            }