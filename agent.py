"""Multi-Agent Luxury Purse Concierge (`google-adk`) with Flash/Pro Routing & Safety Guardrails."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from memory import (
    get_memory_bank_service,
    get_session_service,
    save_client_memory_async,
)
from observability import log_intent_and_outcome, redact_pii
from schemas import AppraisalQuoteSchema
from tools import (
    complete_luxury_purse_transaction,
    estimate_purse_resale_value,
    search_luxury_purse_inventory,
)

# Clear Constitutional System Prompt defining Persona, Domain Knowledge, & Safety Rules
CONCIERGE_CONSTITUTION = """
You are the Maison Luxe Handbag Concierge, an AI specialist for buying and selling authentic designer purses (Hermes, Chanel, Dior, Louis Vuitton).

## Constitutional Rules
1. **Authenticity Zero-Tolerance**: Strictly refuse counterfeit, replica, or knockoff requests. Every bag requires authenticity verification.
2. **Privacy Protection**: Never expose client emails, phone numbers, credit cards, or secrets in outputs.
3. **Specialist Delegation**:
   - Route shopping & budget catalog searches to `inventory_shopping_agent` (`gemini-2.5-flash`).
   - Route seller condition & payout valuations to `resale_appraisal_agent` (`gemini-2.5-pro`).
4. **Human-in-the-Loop Gate**: NEVER complete a purchase or buyout without explicit client approval (`human_approved=True`). Always present the exact item and USD amount first.
"""

BLOCKED_TOPICS = (
    "counterfeit",
    "fake birkin",
    "replica bag",
    "ignore previous instructions",
)


def guardrail_before_model(callback_context: Any, llm_request: Any) -> Optional[Dict[str, Any]]:
    """Blocks counterfeit handbag requests and prompt-injection attempts before calling Gemini."""
    text = str(llm_request or "").lower()
    for term in BLOCKED_TOPICS:
        if term in text:
            log_intent_and_outcome("outcome", "guardrail_before_model", {"blocked_term": term})
            return {
                "status": "blocked_by_policy_guardrail",
                "reason": f"Blocked by boutique authenticity & safety guardrail ('{term}').",
            }
    return None


def self_eval_after_model(callback_context: Any, llm_response: Any) -> Optional[Dict[str, Any]]:
    """Self-evaluates LLM output to scrub any accidentally echoed client PII."""
    raw = str(llm_response or "")
    sanitized = redact_pii(raw)
    return {"sanitized_content": sanitized} if sanitized != raw else None


def hitl_before_tool(tool: Any, args: Dict[str, Any], tool_context: Any) -> Optional[Dict[str, Any]]:
    """Enforces Human-in-the-Loop stop before executing high-stakes purse transactions."""
    name = getattr(tool, "name", None) or getattr(tool, "__name__", str(tool))
    if name == "complete_luxury_purse_transaction" and not args.get("human_approved"):
        if hasattr(tool_context, "request_confirmation"):
            tool_context.request_confirmation(
                hint=f"Confirm {args.get('action')} of {args.get('bag_reference')} for ${args.get('amount_usd')}?"
            )
        return {
            "status": "awaiting_human_confirmation",
            "requires_confirmation": True,
            "recovery_instructions": "Ask the client to confirm the exact USD amount before passing human_approved=True.",
        }
    return None


def trigger_async_memory(callback_context: Any) -> None:
    """Schedules non-blocking background SQLite memory consolidation after agent turns."""
    try:
        asyncio.create_task(
            save_client_memory_async(
                session_id=str(getattr(callback_context, "session_id", "session-1")),
                client_id=str(getattr(callback_context, "user_id", "vip-client")),
                messages=[],
            )
        )
    except RuntimeError:
        pass


try:
    from google.adk.agents import Agent, SequentialAgent  # type: ignore[import-not-found]
    from google.adk.agents.context_cache_config import ContextCacheConfig  # type: ignore[import-not-found]
    from google.adk.apps.app import App, EventsCompactionConfig  # type: ignore[import-not-found]
    from google.adk.plugins.base_plugin import BasePlugin  # type: ignore[import-not-found]
    from google.adk.runners import Runner  # type: ignore[import-not-found]
    from google.adk.tools.function_tool import FunctionTool  # type: ignore[import-not-found]

    class LuxuryGuardrailPlugin(BasePlugin):
        """ADK App-level policy & safety guardrail plugin."""

        def __init__(self) -> None:
            super().__init__(name="luxury_boutique_guardrail")

    inventory_shopping_agent = Agent(
        name="inventory_shopping_agent",
        model="gemini-2.5-flash",
        description="Finds authentic luxury purses matching a buyer's brand and USD budget.",
        instruction="Use `search_luxury_purse_inventory` to help buyers browse authentic handbags.",
        tools=[search_luxury_purse_inventory],
        before_model_callback=guardrail_before_model,
        after_model_callback=self_eval_after_model,
    )

    resale_appraisal_agent = Agent(
        name="resale_appraisal_agent",
        model="gemini-2.5-pro",
        description="Appraises seller handbags based on brand, model, condition, and authenticity card.",
        instruction="Use `estimate_purse_resale_value` and return a structured `AppraisalQuoteSchema` quote.",
        output_schema=AppraisalQuoteSchema,
        tools=[estimate_purse_resale_value],
        before_model_callback=guardrail_before_model,
        after_model_callback=self_eval_after_model,
    )

    concierge_workflow = SequentialAgent(
        name="concierge_workflow",
        description="Coordinates luxury shopping lookup and resale appraisal specialists.",
        sub_agents=[inventory_shopping_agent, resale_appraisal_agent],
    )

    root_agent = Agent(
        name="luxury_purse_concierge",
        model="gemini-2.5-pro",
        description="Concierge agent for buying and selling authentic luxury designer purses.",
        instruction=CONCIERGE_CONSTITUTION,
        sub_agents=[concierge_workflow],
        tools=[FunctionTool(func=complete_luxury_purse_transaction, require_confirmation=True)],
        before_model_callback=guardrail_before_model,
        after_model_callback=self_eval_after_model,
        before_tool_callback=hitl_before_tool,
        after_agent_callback=trigger_async_memory,
    )

    app = App(
        name="luxury_purse_agent",
        root_agent=root_agent,
        context_cache_config=ContextCacheConfig(min_tokens=1024, ttl_seconds=600),
        events_compaction_config=EventsCompactionConfig(compaction_interval=6, overlap_size=2),
        plugins=[LuxuryGuardrailPlugin()],
    )

    runner = Runner(
        app=app,
        session_service=get_session_service(),
        memory_service=get_memory_bank_service(),
    )

except ImportError:
    class _Stub:
        def __init__(self, **kw: Any) -> None:
            self.__dict__.update(kw)

    inventory_shopping_agent = _Stub(name="inventory_shopping_agent", model="gemini-2.5-flash")  # type: ignore[assignment]
    resale_appraisal_agent = _Stub(name="resale_appraisal_agent", model="gemini-2.5-pro", output_schema=AppraisalQuoteSchema)  # type: ignore[assignment]
    concierge_workflow = _Stub(name="concierge_workflow", sub_agents=[inventory_shopping_agent, resale_appraisal_agent])  # type: ignore[assignment]
    root_agent = _Stub(name="luxury_purse_concierge", model="gemini-2.5-pro", sub_agents=[concierge_workflow])  # type: ignore[assignment]
