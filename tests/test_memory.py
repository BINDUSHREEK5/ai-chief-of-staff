from __future__ import annotations

import pytest


async def test_get_or_create_contact_is_idempotent(memory):
    a = await memory.get_or_create_contact("jane@example.com", name="Jane")
    b = await memory.get_or_create_contact("jane@example.com")
    assert a.id == b.id
    assert b.name == "Jane"  # name from the first call stuck


async def test_preferences_roundtrip(memory):
    assert await memory.get_preference("tone") is None
    await memory.set_preference("tone", "casual")
    assert await memory.get_preference("tone") == "casual"
    await memory.set_preference("tone", "formal")  # overwrite, not duplicate
    assert await memory.get_preference("tone") == "formal"
    assert await memory.get_all_preferences() == {"tone": "formal"}


async def test_conversation_is_reused_across_messages(memory):
    contact = await memory.get_or_create_contact("bob@example.com")
    conv1 = await memory.get_or_create_conversation("email", "thread-123", contact_id=contact.id)
    conv2 = await memory.get_or_create_conversation("email", "thread-123", contact_id=contact.id)
    assert conv1.id == conv2.id

    await memory.log_message(conv1.id, "inbound", "email", "bob@example.com", "Hi there")
    await memory.log_message(conv1.id, "outbound", "email", "agent", "Hello!")
    history = await memory.get_recent_messages(conv1.id)
    assert [m.text for m in history] == ["Hi there", "Hello!"]


async def test_approval_lifecycle(memory):
    approval = await memory.create_approval(conversation_id=None, draft_text="Sounds good, see you then.")
    assert approval.status == "pending"

    fetched = await memory.get_pending_approval_by_code(approval.approval_code)
    assert fetched is not None
    assert fetched.draft_text == "Sounds good, see you then."

    resolved = await memory.resolve_approval(approval.approval_code, "approved", final_text=fetched.draft_text)
    assert resolved.status == "approved"
    assert resolved.resolved_at is not None

    # A resolved approval is no longer "pending".
    assert await memory.get_pending_approval_by_code(approval.approval_code) is None


async def test_approved_pattern_lookup_is_keyword_based(memory):
    await memory.record_approved_pattern(
        description="scheduling confirmation",
        example_input="Does 3pm Tuesday work?",
        response_template="3pm Tuesday works for me!",
    )
    found = await memory.find_similar_approved_pattern("scheduling")
    assert found is not None
    assert found.response_template == "3pm Tuesday works for me!"
    assert await memory.find_similar_approved_pattern("complaint") is None


async def test_contact_importance_is_clamped(memory):
    contact = await memory.get_or_create_contact("vip@example.com")
    await memory.set_contact_importance(contact.id, 5.0)  # out of range
    # re-fetch through get_or_create (idempotent lookup) to check persisted value
    refreshed = await memory.get_or_create_contact("vip@example.com")
    assert refreshed.importance_score == 1.0