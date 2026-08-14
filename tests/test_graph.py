"""Tests for the decision graph.

The LLM calls (`app.graph.complete` / `app.graph.complete_structured`) are
monkeypatched with a small fake that returns whatever `ReasoningResult`
decision the test wants — this lets every branch of the routing logic be
exercised deterministically and without spending real API calls, while
everything downstream of the LLM call (memory writes, routing, the
approval record, the "Telegram never needs approval" rule) is real.
"""
from __future__ import annotations

import pytest

from app import graph as graph_module
from app.models import (
    Decision,
    IntentClassification,
    MemoryUpdate,
    ReasoningResult,
    UrgencyAssessment,
)


class FakeLLM:
    def __init__(self, decision: Decision = Decision.NOTIFY_ONLY, is_sensitive: bool = False):
        self.decision = decision
        self.is_sensitive = is_sensitive

    async def complete_structured(self, system_prompt, user_prompt, schema, **kwargs):
        if schema is IntentClassification:
            return IntentClassification(category="request", is_sensitive=self.is_sensitive, summary="test summary")
        if schema is UrgencyAssessment:
            return UrgencyAssessment(score=0.5, reason="test reason")
        if schema is ReasoningResult:
            return ReasoningResult(decision=self.decision, confidence=0.9, reasoning="test reasoning")
        if schema is MemoryUpdate:
            return MemoryUpdate()
        raise AssertionError(f"unexpected schema requested: {schema}")

    async def complete(self, system_prompt, user_prompt, **kwargs):
        return "This needs your attention — a fake but plausible reply."


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(graph_module, "complete_structured", fake.complete_structured)
    monkeypatch.setattr(graph_module, "complete", fake.complete)
    return fake


def _base_state(channel: str, conversation_id: str, text: str, sender: str = "someone@example.com") -> dict:
    return {
        "channel": channel,
        "sender": sender,
        "conversation_id": conversation_id,
        "text": text,
        "behavior_prompt": None,
    }


async def test_notify_only_path(memory, fake_llm):
    fake_llm.decision = Decision.NOTIFY_ONLY
    compiled = graph_module.build_graph(memory)
    result = await compiled.ainvoke(_base_state("email", "t1", "The server is down, need you now."))

    assert result["decision"] == "notify_only"
    assert result.get("notify_text")
    assert not result.get("reply_text")
    assert not result.get("approval_code")


async def test_auto_reply_path(memory, fake_llm):
    fake_llm.decision = Decision.AUTO_REPLY
    compiled = graph_module.build_graph(memory)
    result = await compiled.ainvoke(_base_state("email", "t2", "Does 3pm work for you?"))

    assert result["decision"] == "auto_reply"
    assert result.get("reply_text")
    assert not result.get("approval_code")


async def test_draft_for_approval_creates_a_pending_approval(memory, fake_llm):
    fake_llm.decision = Decision.DRAFT_FOR_APPROVAL
    fake_llm.is_sensitive = True
    compiled = graph_module.build_graph(memory)
    result = await compiled.ainvoke(_base_state("email", "t3", "Can you confirm the contract terms?"))

    assert result["decision"] == "draft_for_approval"
    code = result.get("approval_code")
    assert code
    pending = await memory.get_pending_approval_by_code(code)
    assert pending is not None
    assert pending.status == "pending"


async def test_telegram_chat_never_needs_approval(memory, fake_llm):
    # Even if the model says draft_for_approval, a reply on Telegram goes
    # straight back to the owner's own chat, so the graph should collapse
    # this to auto_reply instead of generating an approval card.
    fake_llm.decision = Decision.DRAFT_FOR_APPROVAL
    compiled = graph_module.build_graph(memory)
    result = await compiled.ainvoke(_base_state("telegram", "t4", "remind me to call the accountant", sender="owner"))

    assert result["decision"] == "auto_reply"
    assert result.get("reply_text")
    assert not result.get("approval_code")


async def test_ignore_path_produces_no_outbound_action(memory, fake_llm):
    fake_llm.decision = Decision.IGNORE
    compiled = graph_module.build_graph(memory)
    result = await compiled.ainvoke(_base_state("email", "t5", "You've won a prize!!!", sender="spam@example.com"))

    assert result["decision"] == "ignore"
    assert not result.get("reply_text")
    assert not result.get("notify_text")
    assert not result.get("approval_code")


async def test_second_message_in_a_thread_reuses_the_conversation(memory, fake_llm):
    fake_llm.decision = Decision.NOTIFY_ONLY
    compiled = graph_module.build_graph(memory)
    await compiled.ainvoke(_base_state("email", "same-thread", "First message", sender="a@example.com"))
    await compiled.ainvoke(_base_state("email", "same-thread", "Second message", sender="a@example.com"))

    contact = await memory.get_or_create_contact("a@example.com")
    conversation = await memory.get_or_create_conversation("email", "same-thread", contact_id=contact.id)
    history = await memory.get_recent_messages(conversation.id, limit=10)
    inbound_texts = [m.text for m in history if m.direction == "inbound"]
    assert inbound_texts == ["First message", "Second message"]