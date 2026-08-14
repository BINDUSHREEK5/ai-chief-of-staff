from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Optional

from caspian_sdk import CommClient

from app.approval import (
    approval_request_blocks,
    approval_request_fallback_text,
    parse_approval_reply,
)
from app.config import get_settings
from app.graph import build_graph
from app.memory import Memory
from app.models import AgentState

logger = logging.getLogger("agent.channels")

OWNER_TELEGRAM_CONVERSATION_KEY = "owner_telegram_conversation_id"


def _connect_email_compat(client: CommClient, username: str):
    try:
        return client.connect_email(username=username)
    except TypeError:
        return client.connect_email(display_name=username)


class ChannelManager:
    def __init__(self, memory: Memory, loop: asyncio.AbstractEventLoop) -> None:
        self.settings = get_settings()
        self.memory = memory
        self.loop = loop
        self.client = CommClient()
        self.graph = build_graph(memory)
        self._listener_thread: Optional[threading.Thread] = None
        self._behavior_prompt: Optional[str] = None

    def connect_channels(self) -> dict[str, Any]:
        connected: dict[str, Any] = {}
        email = _connect_email_compat(self.client, self.settings.agent_email_username)
        connected["email"] = email
        logger.info("connected email inbox: %s", email.get("address", email))
        if self.settings.telegram_bot_token:
            telegram = self.client.connect_telegram(bot_token=self.settings.telegram_bot_token)
            connected["telegram"] = telegram
            logger.info("connected telegram bot")
        else:
            logger.warning("TELEGRAM_BOT_TOKEN not set — running email-only.")
        try:
            self._behavior_prompt = self.client.behavior_prompt()
        except Exception:
            logger.debug("behavior_prompt() unavailable", exc_info=True)
        self.client.on_message(self._on_message)
        return connected

    def start_listening(self) -> threading.Thread:
        thread = threading.Thread(target=self.client.listen, name="caspian-listener", daemon=True)
        thread.start()
        self._listener_thread = thread
        return thread

    def _on_message(self, message: Any) -> None:
        logger.info("=" * 80)
        logger.info("🔥 INBOUND CASPIAN EVENT RECEIVED")
        logger.info("TYPE: %s", type(message))
        logger.info("REPR: %r", message)
        try:
            logger.info("ATTRS: %s", vars(message))
        except Exception:
            logger.info("Could not inspect vars(message)")

        for attr in [
            "channel",
            "text",
            "conversation_id",
            "sender",
            "data",
            "value",
            "callback_data",
            "button",
            "payload",
            "event",
            "type",
        ]:
            try:
                logger.info("message.%s = %r", attr, getattr(message, attr, None))
            except Exception as exc:
                logger.info("message.%s -> ERROR: %s", attr, exc)
        logger.info("=" * 80)
        future = asyncio.run_coroutine_threadsafe(self._handle_message(message), self.loop)
        future.add_done_callback(self._log_if_failed)

    @staticmethod
    def _log_if_failed(future: "asyncio.Future[Any]") -> None:
        try:
            future.result()
        except Exception:
            logger.exception("error while handling an inbound message")

    async def _handle_message(self, message: Any) -> None:
        channel = getattr(message, "channel", "email")
        text = getattr(message, "text", "") or ""
        if channel == "telegram":
            await self.memory.set_preference(
                OWNER_TELEGRAM_CONVERSATION_KEY, str(message.conversation_id)
            )
        command = parse_approval_reply(text)
        if command is not None:
            await self._handle_approval_command(message, command)
            return
        sender = getattr(message, "sender", "")
        if isinstance(sender, dict):
            sender = sender.get("address") or sender.get("email") or sender.get("id") or "unknown"
        else:
            sender = str(sender)
        logger.info("normalized sender:%r", sender)
        state: AgentState = {
            "channel": channel,
            "sender": sender,
            "conversation_id": str(message.conversation_id),
            "text": text,
            "behavior_prompt": self._behavior_prompt,
        }
        result = await self.graph.ainvoke(state)
        await self._deliver(message, result)

    async def _deliver(self, message: Any, result: dict[str, Any]) -> None:
        if result.get("reply_text"):
            self._reply(message, text=result["reply_text"])
            return
        approval_code = result.get("approval_code")
        if approval_code:
            draft_text = (result.get("draft") or {}).get("body", "")
            await self.notify_owner(
                text=approval_request_fallback_text(approval_code, draft_text),
                blocks=approval_request_blocks(approval_code, draft_text),
            )
            return
        if result.get("notify_text"):
            await self.notify_owner(text=result["notify_text"])

    async def _handle_approval_command(self, message: Any, command: Any) -> None:
        approval = await self.memory.get_pending_approval_by_code(command.code)
        if approval is None:
            self._reply(message, text=f"No pending approval found for code {command.code}.")
            return
        if command.action == "reject":
            await self.memory.resolve_approval(command.code, "rejected")
            self._reply(message, text=f"Discarded ({command.code}).")
            return
        final_text = command.edited_text if command.action == "edit" else approval.draft_text
        status = "edited" if command.action == "edit" else "approved"
        await self.memory.resolve_approval(command.code, status, final_text=final_text)
        delivered = False
        if approval.conversation_id:
            conv = await self.memory.get_conversation_by_id(approval.conversation_id)
            if conv:
                try:
                    self.client.send_message(conv.external_conversation_id, text=final_text)
                    delivered = True
                    logger.info("delivered approved reply to %s", conv.external_conversation_id)
                except Exception:
                    logger.exception("failed to deliver approved reply")
        if delivered:
            await self.memory.record_approved_pattern(
                description=f"approved reply ({status})",
                example_input=approval.draft_text,
                response_template=final_text,
            )
            self._reply(message, text=f"Sent. ✅ ({command.code})")
        else:
            self._reply(message, text=f"Approved ({command.code}) but couldn't find the original conversation to deliver it to.")

    async def notify_owner(self, text: str, blocks: Optional[list[dict]] = None) -> None:
        owner_conversation_id = await self.memory.get_preference(OWNER_TELEGRAM_CONVERSATION_KEY)
        if not owner_conversation_id:
            logger.warning("no Telegram owner registered yet; notification not pushed: %s", text[:120])
            return
        try:
            self.client.send_message(owner_conversation_id, text=text, blocks=blocks)
        except TypeError:
            self.client.send_message(owner_conversation_id, text=text)
        except Exception:
            logger.exception("failed to notify owner on Telegram")

    async def send_on_original_channel(self, conversation_db_id: Optional[int], text: str) -> bool:
        if conversation_db_id is None:
            return False
        conversation = await self.memory.get_conversation_by_id(conversation_db_id)
        if conversation is None:
            return False
        try:
            self.client.send_message(conversation.external_conversation_id, text=text)
            return True
        except Exception:
            logger.exception("failed to deliver approved reply to conversation %s", conversation_db_id)
            return False

    @staticmethod
    def _reply(message: Any, text: str, blocks: Optional[list[dict]] = None) -> None:
        logger.info("DELIVERING REPLY: %s", text)
        try:
            result = message.reply(text=text, blocks=blocks)
            logger.info("MESSAGE.REPLY RESULT: %r", result)
        except TypeError:
            logger.warning("message.reply() rejected blocks=, retrying plain text")
            result = message.reply(text=text)
            logger.info("MESSAGE.REPLY RESULT: %r", result)
        except Exception:
            logger.exception("MESSAGE.REPLY FAILED")