"""The agent's decision pipeline, as a LangGraph StateGraph.

    receive_event -> classify_intent -> retrieve_memory -> assess_urgency
        -> reason -> (route on `decision`)
            auto_reply         -> draft_reply -> auto_send        -> save_memory
            draft_for_approval -> draft_reply -> request_approval -> save_memory
            notify_only        -> notify                          -> save_memory
            ignore              ------------------------------->  save_memory

Sending an *approved* draft happens outside this graph: it's triggered by
a later, unrelated inbound message (the user's "approve <code>" reply),
handled directly in `app.channels` rather than re-running the whole
pipeline. See `app/approval.py`.
"""
from __future__ import annotations

import logging

from langgraph.graph import END, START, StateGraph

from app import prompts
from app.llm import complete, complete_structured
from app.memory import Memory
from app.models import (
    AgentState,
    Decision,
    IntentClassification,
    MemoryUpdate,
    ReasoningResult,
    UrgencyAssessment,
)

logger = logging.getLogger("agent.graph")


def build_graph(memory: Memory):
    """Factory so nodes can close over a `Memory` instance — this is what
    lets tests substitute an isolated, temp-file SQLite database instead
    of monkeypatching module globals."""

    # -- nodes ----------------------------------------------------------------

    async def classify_intent_node(state: AgentState) -> dict:
        result = await complete_structured(
            prompts.CLASSIFY_INTENT_SYSTEM,
            f"Channel: {state['channel']}\nFrom: {state['sender']}\n\nMessage:\n{state['text']}",
            IntentClassification,
        )
        logger.info("intent: %s (sensitive=%s)", result.category, result.is_sensitive)
        return {"intent": result.model_dump()}

    async def retrieve_memory_node(state: AgentState) -> dict:
        contact = await memory.get_or_create_contact(email=state["sender"])
        conversation = await memory.get_or_create_conversation(
            channel=state["channel"],
            external_conversation_id=state["conversation_id"],
            contact_id=contact.id,
        )
        await memory.log_message(
            conversation_id=conversation.id,
            direction="inbound",
            channel=state["channel"],
            sender=state["sender"],
            text=state["text"],
        )
        recent = await memory.get_recent_messages(conversation.id, limit=6)
        preferences = await memory.get_all_preferences()
        pattern = None
        if state.get("intent"):
            found = await memory.find_similar_approved_pattern(state["intent"]["category"])
            pattern = (
                {
                    "description": found.pattern_description,
                    "response_template": found.response_template,
                    "times_approved": found.times_approved,
                }
                if found
                else None
            )
        return {
            "contact_id": contact.id,
            "contact_name": contact.name,
            "contact_importance": contact.importance_score,
            "preferences": preferences,
            "recent_history": [f"[{m.direction}] {m.text}" for m in recent],
            "similar_pattern": pattern,
            "conversation_db_id": conversation.id,  # internal, not part of the public schema
        }

    async def assess_urgency_node(state: AgentState) -> dict:
        context = (
            f"Sender importance score (0-1, higher = more important): {state.get('contact_importance', 0.5)}\n"
            f"Intent: {state.get('intent')}\n"
            f"User preferences on record: {state.get('preferences')}\n\n"
            f"Message:\n{state['text']}"
        )
        result = await complete_structured(prompts.ASSESS_URGENCY_SYSTEM, context, UrgencyAssessment)
        logger.info("urgency: %.2f (%s)", result.score, result.reason)
        return {"urgency": result.model_dump()}

    async def reason_node(state: AgentState) -> dict:
        context = (
            f"Intent: {state.get('intent')}\n"
            f"Urgency: {state.get('urgency')}\n"
            f"Sender importance: {state.get('contact_importance', 0.5)}\n"
            f"Similar previously-approved pattern: {state.get('similar_pattern')}\n"
            f"Recent history in this conversation: {state.get('recent_history')}\n"
            f"User preferences: {state.get('preferences')}\n\n"
            f"Message:\n{state['text']}"
        )
        result = await complete_structured(prompts.REASONING_SYSTEM, context, ReasoningResult,)

        # A reply on Telegram goes straight back to the owner's own chat —
        # nothing leaves the house, so the approval gate (which exists to
        # protect the user from an unreviewed message reaching a third
        # party) doesn't apply. Email replies do leave the house, so those
        # still respect whatever the model decided.
        channel =str(state.get("channel","")).strip().strip('"').strip("'").lower()
        intent = state.get("intent") or {}
        urgency = state.get("urgency") or {}

        is_sensitive = bool(intent.get("is_sensitive", False))
        urgency_score = float(urgency.get("score", 0.0))
        #try:
         #   urgency_score = float(
          #      urgency.get("score", 0.0)
           # )
        #except (TypeError, ValueError):
         #   urgency_score = 0.0

        if channel == "telegram":
            if result.decision == Decision.DRAFT_FOR_APPROVAL:
                result = result.model_copy(
                    update={"decision": Decision.AUTO_REPLY}
            )

        
        elif channel == "email":
            # Only *escalate* to draft_for_approval — never override
            # notify_only or ignore that the model chose intentionally.
            if (is_sensitive or urgency_score >= 0.75) and result.decision == Decision.AUTO_REPLY:
                result = result.model_copy(
                    update={"decision": Decision.DRAFT_FOR_APPROVAL}
                )

        logger.info("decision: %s (confidence=%.2f) — %s", result.decision, result.confidence, result.reasoning,)

        conversation_db_id = state.get("conversation_db_id")
        await memory.log_decision(
            conversation_id=conversation_db_id,
            decision=result.decision.value,
            urgency_score=state.get("urgency", {}).get("score"),
            reasoning=result.reasoning,
        )
        return {"reasoning": result.model_dump(), "decision": result.decision.value,}
        
    async def draft_reply_node(state: AgentState) -> dict:
        etiquette = prompts.channel_etiquette_block(state.get("behavior_prompt"))
        context = (
            f"Channel: {state['channel']}\n"
            f"Recent history: {state.get('recent_history')}\n"
            f"User preferences: {state.get('preferences')}\n"
            f"Similar previously-approved pattern to reuse as a style guide, if relevant: "
            f"{state.get('similar_pattern')}\n\n"
            f"Message to reply to:\n{state['text']}"
        )
        body = await complete(prompts.DRAFT_REPLY_SYSTEM + etiquette, context, temperature=0.4)
        return {"draft": {"body": body}}

    async def auto_send_node(state: AgentState) -> dict:
        draft = state.get("draft") or {}
        return {"reply_text": draft.get("body", "")}

    async def request_approval_node(state: AgentState) -> dict:
        draft = state.get("draft") or {}
        conv_id = state.get("conversation_db_id")
        approval = await memory.create_approval(
            conversation_id=conv_id,
            draft_text=draft.get("body", ""),
            requested_via="telegram",
        )
        return {"approval_code": approval.approval_code}

    async def notify_node(state: AgentState) -> dict:
        context = f"Reasoning: {state.get('reasoning', {}).get('reasoning')}\n\nMessage:\n{state['text']}"
        text = await complete(prompts.NOTIFICATION_SYSTEM, context, temperature=0.4, max_tokens=150)
        return {"notify_text": text}

    async def ignore_node(state: AgentState) -> dict:
        return {}

    async def save_memory_node(state: AgentState) -> dict:
        # Log the outbound side of the conversation, if anything was sent.
        conversation_db_id = state.get("conversation_db_id")
        outbound_text = state.get("reply_text") or state.get("notify_text")
        if outbound_text and conversation_db_id:
            await memory.log_message(
                conversation_id=conversation_db_id,
                direction="outbound",
                channel=state["channel"],
                sender="agent",
                text=outbound_text,
            )

        # Conservative, LLM-proposed nudge to what the agent remembers.
        context = (
            f"Intent: {state.get('intent')}\nUrgency: {state.get('urgency')}\n"
            f"Decision taken: {state.get('decision')}\n\nMessage:\n{state['text']}"
        )
        try:
            update = await complete_structured(prompts.MEMORY_UPDATE_SYSTEM, context, MemoryUpdate)
        except RuntimeError:
            logger.warning("memory-update proposal failed validation; skipping this cycle")
            return {}

        contact_id = state.get("contact_id")
        if contact_id and update.contact_importance_delta:
            new_score = state.get("contact_importance", 0.5) + update.contact_importance_delta
            await memory.set_contact_importance(contact_id, new_score, notes=update.note)
        if update.new_preference_key and update.new_preference_value:
            await memory.set_preference(update.new_preference_key, update.new_preference_value)

        return {"memory_update": update.model_dump()}

    # -- routing ----------------------------------------------------------------

    def route_after_reasoning(state: AgentState) -> str:
        decision = state.get("decision", Decision.IGNORE.value)
        if decision == Decision.AUTO_REPLY.value:
            return "draft_reply_auto"
        if decision == Decision.DRAFT_FOR_APPROVAL.value:
            return "draft_reply_approval"
        if decision == Decision.NOTIFY_ONLY.value:
            return "notify"
        return "ignore"

    # -- assemble -----------------------------------------------------------------

    graph = StateGraph(AgentState)
    graph.add_node("classify_intent", classify_intent_node)
    graph.add_node("retrieve_memory", retrieve_memory_node)
    graph.add_node("assess_urgency", assess_urgency_node)
    graph.add_node("reason", reason_node)
    graph.add_node("draft_reply", draft_reply_node)
    graph.add_node("auto_send", auto_send_node)
    graph.add_node("request_approval", request_approval_node)
    graph.add_node("notify", notify_node)
    graph.add_node("ignore", ignore_node)
    graph.add_node("save_memory", save_memory_node)

    graph.add_edge(START, "classify_intent")
    graph.add_edge("classify_intent", "retrieve_memory")
    graph.add_edge("retrieve_memory", "assess_urgency")
    graph.add_edge("assess_urgency", "reason")

    graph.add_conditional_edges(
        "reason",
        route_after_reasoning,
        {
            "draft_reply_auto": "draft_reply",
            "draft_reply_approval": "draft_reply",
            "notify": "notify",
            "ignore": "ignore",
        },
    )

    # `draft_reply` is shared by both drafting branches; decide the next
    # hop the same way reasoning did, based on `decision` already in state.
    def route_after_draft(state: AgentState) -> str:
        return "auto_send" if state.get("decision") == Decision.AUTO_REPLY.value else "request_approval"

    graph.add_conditional_edges(
        "draft_reply",
        route_after_draft,
        {"auto_send": "auto_send", "request_approval": "request_approval"},
    )

    graph.add_edge("auto_send", "save_memory")
    graph.add_edge("request_approval", "save_memory")
    graph.add_edge("notify", "save_memory")
    graph.add_edge("ignore", "save_memory")
    graph.add_edge("save_memory", END)

    return graph.compile()