"""Automated Golden Evaluation & Unit Test Suite for the Luxury Purse Concierge Agent."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agent import (
    guardrail_before_model,
    hitl_before_tool,
    inventory_shopping_agent,
    resale_appraisal_agent,
    root_agent,
)
from memory import (
    ClientMemoryDB,
    compact_conversation_history,
    save_client_memory_async,
)
from observability import AUDIT_EVENTS, redact_pii
from tools import (
    complete_luxury_purse_transaction,
    estimate_purse_resale_value,
    search_luxury_purse_inventory,
)

GOLDEN_FILE = Path(__file__).resolve().parent / "golden_dataset.json"


class TestLuxuryPurseAgent(unittest.IsolatedAsyncioTestCase):
    """Validates all 5 rubric pillars: Tools/Schemas, Memory, Orchestration, Observability, & Eval."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="luxe_purse_test_"))
        AUDIT_EVENTS.clear()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree("orders", ignore_errors=True)

    def test_01_golden_dataset_cases(self) -> None:
        """Verifies all golden dataset scenarios and guided LLM recovery instructions."""
        cases = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))
        tools = {
            "search_luxury_purse_inventory": search_luxury_purse_inventory,
            "estimate_purse_resale_value": estimate_purse_resale_value,
            "complete_luxury_purse_transaction": complete_luxury_purse_transaction,
        }
        for case in cases:
            res = tools[case["tool"]](**case["input"])
            self.assertEqual(res["status"], case["expected_status"])
            if case.get("requires_recovery"):
                self.assertIn("recovery_instructions", res)

    def test_02_pii_redaction_and_intent_outcome_logs(self) -> None:
        """Verifies client email/phone/card scrubbing and explicit intent vs. outcome audit logs."""
        scrubbed = redact_pii(
            "VIP buyer coco@chanel.example, phone 212-555-0199, card 4111 2222 3333 4444"
        )
        self.assertNotIn("coco@chanel.example", scrubbed)
        self.assertNotIn("212-555-0199", scrubbed)
        self.assertNotIn("4111 2222 3333 4444", scrubbed)

        AUDIT_EVENTS.clear()
        quote = estimate_purse_resale_value("Chanel", "Classic Flap", "excellent", True)
        self.assertEqual(quote["status"], "success")
        phases = [e["event_type"] for e in AUDIT_EVENTS]
        self.assertIn("agent_intent", phases)
        self.assertIn("agent_outcome", phases)

    async def test_03_memory_compaction_and_async_sqlite_persistence(self) -> None:
        """Verifies context history compaction and non-blocking async SQLite client memory."""
        history = [{"role": "user", "content": f"Asking about bag #{i}"} for i in range(14)]
        compacted = compact_conversation_history(history, max_recent=5)
        self.assertEqual(len(compacted), 6)
        self.assertEqual(compacted[0]["event_type"], "compacted_digest")

        db = ClientMemoryDB(db_path=str(self.tmp / "client_memory.db"))
        saved = await save_client_memory_async("sess-1", "client-vip", history, db=db)
        self.assertEqual(saved["status"], "saved")
        self.assertEqual(len(db.get_memories("client-vip")), 1)

    def test_04_counterfeit_guardrail_hitl_and_model_routing(self) -> None:
        """Verifies counterfeit blocking guardrail, HITL stop, and Flash vs. Pro routing."""
        blocked = guardrail_before_model(None, "Can you sell me a replica bag cheap?")
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["status"], "blocked_by_policy_guardrail")  # type: ignore[index]

        gate = hitl_before_tool(
            complete_luxury_purse_transaction,
            {"action": "buy", "bag_reference": "CHANEL-FLAP-MED-BLK", "amount_usd": 7900.0, "human_approved": False},
            None,
        )
        self.assertIsNotNone(gate)
        self.assertTrue(gate["requires_confirmation"])  # type: ignore[index]

        self.assertEqual(inventory_shopping_agent.model, "gemini-2.5-flash")
        self.assertEqual(resale_appraisal_agent.model, "gemini-2.5-pro")
        self.assertEqual(root_agent.name, "luxury_purse_concierge")


if __name__ == "__main__":
    unittest.main()
