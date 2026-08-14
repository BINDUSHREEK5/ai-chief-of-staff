"""Typed data contracts shared across the app.

Two different "shapes" live here on purpose:

- Pydantic ``BaseModel`` classes are used wherever we need validation —
  structured LLM outputs, and FastAPI request/response bodies.
- ``AgentState`` is a plain ``TypedDict`` because that is what LangGraph's
  ``StateGraph`` expects to merge node outputs into.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class Decision(str, Enum):
    AUTO_REPLY = "auto_reply"
    DRAFT_FOR_APPROVAL = "draft_for_approval"
    NOTIFY_ONLY = "notify_only"
    IGNORE = "ignore"


class IntentClassification(BaseModel):
    category: str = Field(
        description="One of: request, question, fyi, scheduling, complaint, spam, personal, other"
    )
    is_sensitive: bool = Field(
        description=(
            "true if a reply could have real-world consequences: money, legal "
            "commitments, contracts, confidential info, or anything the user "
            "would be upset to learn was sent without their sign-off"
        )
    )
    summary: str = Field(description="One sentence, plain-language summary of what the sender wants")


class UrgencyAssessment(BaseModel):
    score: float = Field(ge=0.0, le=1.0, description="0 = can wait indefinitely, 1 = drop everything")
    reason: str


class ReasoningResult(BaseModel):
    decision: Decision
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(description="Short internal explanation, shown in logs and the daily summary")


class DraftReply(BaseModel):
    subject: Optional[str] = None
    body: str


class NotificationText(BaseModel):
    text: str = Field(description="Short Telegram-friendly ping, one or two sentences")


class MemoryUpdate(BaseModel):
    contact_importance_delta: float = Field(
        default=0.0, ge=-0.3, le=0.3, description="Nudge to the contact's importance score, if warranted"
    )
    new_preference_key: Optional[str] = None
    new_preference_value: Optional[str] = None
    note: Optional[str] = Field(default=None, description="One-line note to append to the contact's file, if any")


class AgentState(TypedDict, total=False):
    """The LangGraph state object. Every node reads a slice of this and
    returns a partial dict that gets shallow-merged in."""

    # raw event
    channel: str
    sender: str
    conversation_id: str
    text: str
    behavior_prompt: Optional[str]  # Caspian's client.behavior_prompt(), if available

    # retrieved memory
    contact_id: Optional[int]
    contact_name: Optional[str]
    contact_importance: float
    preferences: dict[str, str]
    recent_history: list[str]
    similar_pattern: Optional[dict[str, Any]]
    conversation_db_id: Optional[int]

    # reasoning pipeline
    intent: dict[str, Any]
    urgency: dict[str, Any]
    reasoning: dict[str, Any]
    decision: str

    # outputs
    draft: Optional[dict[str, Any]]
    approval_code: Optional[str]
    reply_text: Optional[str]
    notify_text: Optional[str]
    memory_update: Optional[dict[str, Any]]


class ApprovalAction(BaseModel):
    action: Literal["approve", "reject", "edit"]
    edited_text: Optional[str] = None