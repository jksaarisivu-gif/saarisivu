"""Luxury Handbag Buying & Selling Tools with Explicit Schemas & Guided Error Recovery."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, List

from observability import log_intent_and_outcome, trace_tool
from schemas import (
    PurseTransactionInput,
    ResaleValuationInput,
    SearchInventoryInput,
)

BOUTIQUE_INVENTORY: List[Dict[str, Any]] = [
    {"sku": "HERMES-BIRKIN25-BLK", "brand": "Hermes", "model": "Birkin 25 Togo Black", "condition": "pristine", "price_usd": 14800.0},
    {"sku": "CHANEL-FLAP-MED-BLK", "brand": "Chanel", "model": "Medium Classic Flap Caviar", "condition": "excellent", "price_usd": 7900.0},
    {"sku": "LV-SPEEDY25-MONO", "brand": "Louis Vuitton", "model": "Speedy Bandouliere 25", "condition": "excellent", "price_usd": 1750.0},
    {"sku": "DIOR-LADY-MINI", "brand": "Dior", "model": "Mini Lady Dior Lambskin", "condition": "pristine", "price_usd": 4600.0},
]

BASE_RESALE_VALUES: Dict[str, float] = {
    "hermes": 12500.0,
    "chanel": 6800.0,
    "dior": 3900.0,
    "louis vuitton": 1500.0,
}

CONDITION_MULTIPLIER: Dict[str, float] = {
    "pristine": 1.0,
    "excellent": 0.85,
    "good": 0.68,
}


@trace_tool("tool.search_luxury_purse_inventory")
def search_luxury_purse_inventory(
    brand: str,
    max_price_usd: float = 15000.0,
) -> Dict[str, Any]:
    """Searches authenticated luxury handbags available for purchase by brand and budget.

    Args:
        brand: Designer brand name (e.g., 'Hermes', 'Chanel', 'Louis Vuitton', 'Dior').
        max_price_usd: Maximum budget in USD (must be strictly greater than 0).

    Returns:
        Dictionary with matching authenticated bags or guided `recovery_instructions` if inputs fail validation.
    """
    log_intent_and_outcome("intent", "search_luxury_purse_inventory", {"brand": brand, "max_price_usd": max_price_usd})
    try:
        validated = SearchInventoryInput(brand=brand, max_price_usd=max_price_usd)
    except Exception as exc:
        err = {
            "status": "error",
            "error_code": "INVALID_SEARCH_FILTER",
            "message": str(exc),
            "recovery_instructions": (
                "Provide a designer `brand` name of at least 2 characters and a positive "
                "`max_price_usd` budget greater than 0 (e.g., 8500.0), then retry."
            ),
        }
        log_intent_and_outcome("outcome", "search_luxury_purse_inventory", err)
        return err

    matches = [
        item for item in BOUTIQUE_INVENTORY
        if validated.brand.lower() in item["brand"].lower() and item["price_usd"] <= validated.max_price_usd
    ]
    res = {"status": "success", "brand": validated.brand, "matches": matches}
    log_intent_and_outcome("outcome", "search_luxury_purse_inventory", res)
    return res


@trace_tool("tool.estimate_purse_resale_value")
def estimate_purse_resale_value(
    brand: str,
    model_name: str,
    condition: str,
    has_authenticity_card: bool = True,
) -> Dict[str, Any]:
    """Calculates a fair market seller payout quote for consigning or selling a luxury purse.

    Args:
        brand: Designer house name (e.g., 'Chanel', 'Hermes', 'Dior', 'Louis Vuitton').
        model_name: Specific bag style (e.g., 'Classic Flap', 'Birkin 25').
        condition: Verified bag condition grade ('pristine', 'excellent', or 'good').
        has_authenticity_card: True if original boutique authenticity card/dustbag is included.

    Returns:
        Appraisal breakdown with estimated payout in USD or clear recovery instructions on invalid inputs.
    """
    log_intent_and_outcome(
        "intent",
        "estimate_purse_resale_value",
        {"brand": brand, "model_name": model_name, "condition": condition},
    )
    try:
        validated = ResaleValuationInput(
            brand=brand,
            model_name=model_name,
            condition=condition,
            has_authenticity_card=has_authenticity_card,
        )
    except Exception as exc:
        err = {
            "status": "error",
            "error_code": "INVALID_APPRAISAL_INPUT",
            "message": str(exc),
            "recovery_instructions": (
                "Set `condition` strictly to one of: 'pristine', 'excellent', or 'good', "
                "and provide non-empty `brand` and `model_name` strings."
            ),
        }
        log_intent_and_outcome("outcome", "estimate_purse_resale_value", err)
        return err

    base_val = BASE_RESALE_VALUES.get(validated.brand.lower(), 1200.0)
    card_bonus = 1.08 if validated.has_authenticity_card else 0.92
    quote = round(base_val * CONDITION_MULTIPLIER[validated.condition] * card_bonus, 2)

    res = {
        "status": "success",
        "brand": validated.brand,
        "model_name": validated.model_name,
        "condition": validated.condition,
        "estimated_payout_usd": quote,
        "includes_authenticity_card": validated.has_authenticity_card,
    }
    log_intent_and_outcome("outcome", "estimate_purse_resale_value", res)
    return res


@trace_tool("tool.complete_luxury_purse_transaction")
def complete_luxury_purse_transaction(
    action: str,
    bag_reference: str,
    amount_usd: float,
    human_approved: bool = False,
) -> Dict[str, Any]:
    """Finalizes buying or selling a luxury purse ONLY after explicit Human-in-the-Loop confirmation.

    Args:
        action: Either 'buy' (client purchasing from inventory) or 'sell' (client accepting buyout quote).
        bag_reference: Bag SKU or model identifier (e.g., 'CHANEL-FLAP-MED-BLK').
        amount_usd: Agreed USD price or seller payout amount.
        human_approved: Must be True after explicit user sign-off; otherwise execution pauses safely.

    Returns:
        Confirmed order receipt JSON or a Human-in-the-Loop pause requesting user approval.
    """
    log_intent_and_outcome(
        "intent",
        "complete_luxury_purse_transaction",
        {"action": action, "bag_reference": bag_reference, "amount_usd": amount_usd, "human_approved": human_approved},
    )
    try:
        validated = PurseTransactionInput(
            action=action,
            bag_reference=bag_reference,
            amount_usd=amount_usd,
            human_approved=human_approved,
        )
    except Exception as exc:
        err = {
            "status": "error",
            "error_code": "INVALID_TRANSACTION_REQUEST",
            "message": str(exc),
            "recovery_instructions": "Set `action` to 'buy' or 'sell' and `amount_usd` > 0.",
        }
        log_intent_and_outcome("outcome", "complete_luxury_purse_transaction", err)
        return err

    if not validated.human_approved:
        pause = {
            "status": "awaiting_human_confirmation",
            "requires_confirmation": True,
            "bag_reference": validated.bag_reference,
            "amount_usd": validated.amount_usd,
            "recovery_instructions": (
                f"High-value luxury transaction ({validated.action} '{validated.bag_reference}' for "
                f"${validated.amount_usd:,.2f}) requires explicit client confirmation. Ask the user "
                "to confirm the exact price first, then re-invoke with human_approved=True."
            ),
        }
        log_intent_and_outcome("outcome", "complete_luxury_purse_transaction", pause)
        return pause

    orders_dir = Path("orders")
    orders_dir.mkdir(parents=True, exist_ok=True)
    receipt = {
        "status": "completed",
        "action": validated.action,
        "bag_reference": validated.bag_reference,
        "amount_usd": validated.amount_usd,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    (orders_dir / f"{validated.bag_reference}.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    log_intent_and_outcome("outcome", "complete_luxury_purse_transaction", receipt)
    return receipt
