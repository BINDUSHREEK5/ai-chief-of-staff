"""FastAPI entrypoint.

Responsibilities:
- On startup: initialise the memory store, connect Caspian channels, start
  the listener thread, and kick off the daily-summary scheduler.
- Expose a small set of HTTP endpoints as a *secondary* approval surface
  (the primary one is the Telegram card — see `app/approval.py`) and for
  operational visibility (health, pending approvals, an on-demand summary).

Run with: `uvicorn app.main:app --host 0.0.0.0 --port 8000`
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from app.approval import approval_request_blocks, approval_request_fallback_text
from app.channels import ChannelManager
from app.config import get_settings
from app.graph import build_graph
from app.logging_config import configure_logging
from app.memory import Memory
from app.models import AgentState, ApprovalAction
from app.summary import build_daily_summary

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("agent.main")


async def _daily_summary_loop(memory: Memory, channels: ChannelManager) -> None:
    while True:
        now = datetime.now(timezone.utc)
        next_run = now.replace(hour=settings.daily_summary_hour_utc, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
        try:
            text = await build_daily_summary(memory)
            await channels.notify_owner(text=text)
            logger.info("sent daily summary")
        except Exception:
            logger.exception("daily summary run failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    memory = Memory()
    await memory.init()

    loop = asyncio.get_running_loop()
    channels = ChannelManager(memory, loop)
    channels.connect_channels()
    channels.start_listening()

    summary_task = asyncio.create_task(_daily_summary_loop(memory, channels))

    app.state.memory = memory
    app.state.channels = channels

    logger.info("agent is live — email%s connected",
                " + telegram" if settings.telegram_bot_token else " only")
    try:
        yield
    finally:
        summary_task.cancel()
        await memory.close()


app = FastAPI(title="AI Chief of Staff", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/approvals", response_class=JSONResponse)
async def list_pending_approvals() -> list[dict]:
    memory: Memory = app.state.memory
    data = await memory.get_daily_summary_data(datetime.now(timezone.utc) - timedelta(days=30))
    return [
        {
            "code": a.approval_code,
            "status": a.status,
            "draft_preview": a.draft_text[:200],
            "created_at": a.created_at.isoformat(),
        }
        for a in data["pending_approvals"]
    ]


@app.get("/approvals/{code}", response_class=HTMLResponse)
async def view_approval(code: str) -> str:
    memory: Memory = app.state.memory
    approval = await memory.get_pending_approval_by_code(code)
    if approval is None:
        raise HTTPException(status_code=404, detail="No pending approval with that code.")
    # Minimal, dependency-free HTML — this is a fallback for reviewers who'd
    # rather click a link than reply on Telegram, not the primary UI.
    return f"""<!DOCTYPE html>
<html><head><title>Approve {code}</title>
<style>body{{font-family:sans-serif;max-width:640px;margin:40px auto;padding:0 16px}}
textarea{{width:100%;height:160px}} button{{padding:8px 16px;margin-right:8px}}</style>
</head><body>
<h2>Draft reply — {code}</h2>
<form method="post" action="/approvals/{code}/action">
<textarea name="edited_text">{approval.draft_text}</textarea><br><br>
<button name="action" value="approve">Approve &amp; send</button>
<button name="action" value="edit">Send edited version</button>
<button name="action" value="reject">Reject</button>
</form>
</body></html>"""


@app.post("/approvals/{code}/action")
async def resolve_approval_action(code: str, action: ApprovalAction) -> dict:
    memory: Memory = app.state.memory
    channels: ChannelManager = app.state.channels

    approval = await memory.get_pending_approval_by_code(code)
    if approval is None:
        raise HTTPException(status_code=404, detail="No pending approval with that code.")

    if action.action == "reject":
        await memory.resolve_approval(code, "rejected")
        return {"status": "rejected"}

    final_text = action.edited_text if action.action == "edit" else approval.draft_text
    status = "edited" if action.action == "edit" else "approved"
    await memory.resolve_approval(code, status, final_text=final_text)
    delivered = await channels.send_on_original_channel(approval.conversation_id, final_text)
    return {"status": status, "delivered": delivered}


@app.get("/summary/daily")
async def daily_summary(push: bool = False) -> dict:
    memory: Memory = app.state.memory
    text = await build_daily_summary(memory)
    if push:
        channels: ChannelManager = app.state.channels
        await channels.notify_owner(text=text)
    return {"summary": text}


@app.post("/dev/simulate-message")
async def simulate_message(channel: str, sender: str, text: str, conversation_id: str = "dev-thread") -> dict:
    """Development-only helper: runs the LangGraph pipeline directly on a
    synthetic message, bypassing Caspian entirely. Useful for exercising
    the agent's reasoning without live email/Telegram traffic — this is
    NOT the hackathon demo path (that's real inbound mail/Telegram, per
    the "no mocked demos" rule); it's for local iteration and CI smoke
    tests only.
    """
    memory: Memory = app.state.memory
    graph = build_graph(memory)
    state: AgentState = {
        "channel": channel,
        "sender": sender,
        "conversation_id": conversation_id,
        "text": text,
        "behavior_prompt": None,
    }
    result = await graph.ainvoke(state)
    return dict(result)