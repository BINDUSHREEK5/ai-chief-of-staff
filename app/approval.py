"""Human-in-the-loop approval workflow.

Design: when the agent drafts something sensitive, it sends the user a
Caspian "card" block on Telegram with Approve / Edit / Reject buttons.
Tapping a button sends its `value` back through the *same* `on_message`
handler as any other inbound message — so approvals reuse all the normal
plumbing instead of needing a separate webhook or UI. A plain-text
fallback ("reply APPROVE 9F3A2B10" / "REJECT 9F3A2B10") is always
included too, for channels or clients that don't render buttons, and as
a fallback path through the FastAPI endpoints in `app.main` for judges
who'd rather click a link than use Telegram.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional

_COMMAND_RE = re.compile(
    r"^\s*(approve|reject|edit)\s*[:\s]\s*([A-Za-z0-9]{6,10})\s*:?\s*(.*)$", re.IGNORECASE | re.DOTALL
)


@dataclass
class ParsedApprovalCommand:
    action: Literal["approve", "reject", "edit"]
    code: str
    edited_text: Optional[str] = None


def parse_approval_reply(text: str) -> Optional[ParsedApprovalCommand]:
    """Recognise both button-callback values (e.g. "approve:9F3A2B10") and
    typed replies (e.g. "REJECT 9F3A2B10" or "edit 9F3A2B10: say Tuesday
    instead"). Returns None if `text` isn't an approval command at all,
    so callers can fall through to normal message handling."""
    match = _COMMAND_RE.match(text.strip())
    if not match:
        return None
    action, code, rest = match.groups()
    action = action.lower()
    edited_text = rest.strip() or None
    if action == "edit" and not edited_text:
        return None  # "edit" with no replacement text isn't actionable
    return ParsedApprovalCommand(action=action, code=code.upper(), edited_text=edited_text)


def approval_request_blocks(code: str, draft_preview: str, subject: Optional[str] = None) -> list[dict]:
    """Caspian `Block` payload for an approval card. Buttons with a
    `value` (rather than a `url`) come back as the text of the next
    inbound message when tapped."""
    preview = draft_preview if len(draft_preview) <= 500 else draft_preview[:497] + "..."
    title = f"Approve reply to: {subject}" if subject else "Approve this reply?"
    return [
        {
            "type": "card",
            "title": title,
            "subtitle": f"Approval code {code}",
            "text": preview,
            "buttons": [
                {"label": "✅ Approve", "value": f"approve:{code}"},
                {"label": "✏️ Edit", "value": f"edit:{code}"},
                {"label": "❌ Reject", "value": f"reject:{code}"},
            ],
        }
    ]


def approval_request_fallback_text(code: str, draft_preview: str) -> str:
    """Plain-text version used as the `text=` fallback for channels/clients
    that can't render blocks (and shown alongside the card everywhere)."""
    return (
        f"Draft reply ready for your review (code {code}):\n\n"
        f"{draft_preview}\n\n"
        f'Reply "approve {code}" to send as-is, "reject {code}" to discard, '
        f'or "edit {code}: <new text>" to send something different.'
    )