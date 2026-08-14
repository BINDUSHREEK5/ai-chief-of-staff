"""Builds the plain-text daily digest sent to the user on Telegram.

Deliberately not another LLM call: the classification/urgency/reasoning
judgment calls already happened per-message when they came in, so the
digest is a straightforward aggregation of what's already on record —
fewer moving parts, and it can never contradict what the agent already
decided in the moment.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.memory import Memory


async def build_daily_summary(memory: Memory) -> str:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    data = await memory.get_daily_summary_data(since)

    decisions = data["decisions"]
    pending = data["pending_approvals"]
    inbound = [m for m in data["messages"] if m.direction == "inbound"]

    if not inbound and not pending:
        return "Quiet last 24 hours — nothing came in that needed your attention."

    lines = [f"Daily summary — {len(inbound)} message(s) in the last 24h."]

    by_decision: dict[str, int] = {}
    for d in decisions:
        by_decision[d.decision] = by_decision.get(d.decision, 0) + 1
    if by_decision:
        breakdown = ", ".join(f"{count} {label}" for label, count in sorted(by_decision.items()))
        lines.append(f"Handled automatically: {breakdown}.")

    if pending:
        lines.append(f"\n{len(pending)} draft(s) still waiting on your approval:")
        for approval in pending[:10]:
            preview = approval.draft_text[:80] + ("..." if len(approval.draft_text) > 80 else "")
            lines.append(f"  • {approval.approval_code}: {preview}")

    return "\n".join(lines)