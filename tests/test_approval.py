from __future__ import annotations

from app.approval import approval_request_blocks, parse_approval_reply


def test_parses_button_callback_values():
    cmd = parse_approval_reply("approve:9F3A2B10")
    assert cmd is not None
    assert cmd.action == "approve"
    assert cmd.code == "9F3A2B10"


def test_parses_typed_reject():
    cmd = parse_approval_reply("  REJECT 9f3a2b10  ")
    assert cmd is not None
    assert cmd.action == "reject"
    assert cmd.code == "9F3A2B10"  # normalised to uppercase


def test_parses_edit_with_replacement_text():
    cmd = parse_approval_reply("edit 9F3A2B10: say Wednesday instead of Tuesday")
    assert cmd is not None
    assert cmd.action == "edit"
    assert cmd.edited_text == "say Wednesday instead of Tuesday"


def test_edit_without_replacement_text_is_not_actionable():
    assert parse_approval_reply("edit 9F3A2B10") is None


def test_unrelated_message_is_not_a_command():
    assert parse_approval_reply("Sounds good, thanks!") is None
    assert parse_approval_reply("") is None


def test_approval_blocks_have_three_buttons_with_the_code():
    blocks = approval_request_blocks("9F3A2B10", "Sure, I can make it work.")
    buttons = blocks[0]["buttons"]
    assert len(buttons) == 3
    assert {b["value"] for b in buttons} == {
        "approve:9F3A2B10",
        "edit:9F3A2B10",
        "reject:9F3A2B10",
    }