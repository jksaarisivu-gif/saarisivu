"""Pydantic JSON Schemas validating tool inputs and structuring luxury appraisal outputs."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

try:
    from pydantic import BaseModel, Field  # type: ignore[import-not-found]
except ImportError:
    class _FieldSpec:
        def __init__(
            self,
            default: Any = ...,
            *,
            gt: Optional[float] = None,
            ge: Optional[float] = None,
            min_length: Optional[int] = None,
            pattern: Optional[str] = None,
            description: str = "",
        ):
            self.default = default
            self.gt = gt
            self.ge = ge
            self.min_length = min_length
            self.pattern = pattern
            self.description = description

    def Field(default: Any = ..., **kwargs: Any) -> Any:  # type: ignore[misc]
        return _FieldSpec(default, **kwargs)

    class BaseModel:  # type: ignore[no-redef]
        def __init__(self, **data: Any) -> None:
            for name, attr in self.__class__.__dict__.items():
                if isinstance(attr, _FieldSpec):
                    val = data.get(name, attr.default)
                    if val is ...:
                        raise ValueError(f"Missing required field '{name}'")
                    if isinstance(val, (int, float)) and not isinstance(val, bool):
                        if attr.gt is not None and val <= attr.gt:
                            raise ValueError(f"'{name}' must be > {attr.gt}")
                        if attr.ge is not None and val < attr.ge:
                            raise ValueError(f"'{name}' must be >= {attr.ge}")
                    if isinstance(val, str):
                        if attr.min_length and len(val) < attr.min_length:
                            raise ValueError(f"'{name}' must be at least {attr.min_length} chars")
                        if attr.pattern and not re.match(attr.pattern, val):
                            raise ValueError(f"'{name}' does not match {attr.pattern}")
                    setattr(self, name, val)

        def model_dump(self) -> Dict[str, Any]:
            return dict(self.__dict__)


class SearchInventoryInput(BaseModel):
    """Input schema for searching available authenticated luxury handbags."""

    brand: str = Field(
        ...,
        min_length=2,
        description="Designer brand name (e.g., 'Hermes', 'Chanel', 'Louis Vuitton', 'Dior').",
    )
    max_price_usd: float = Field(
        default=15000.0,
        gt=0,
        description="Maximum buyer budget in USD (must be strictly greater than 0).",
    )


class ResaleValuationInput(BaseModel):
    """Input schema for estimating the resale payout value of a seller's handbag."""

    brand: str = Field(..., min_length=2, description="Designer brand name.")
    model_name: str = Field(..., min_length=2, description="Bag model (e.g., 'Classic Flap', 'Birkin 25').")
    condition: str = Field(
        ...,
        pattern=r"^(pristine|excellent|good)$",
        description="Condition tier: must be 'pristine', 'excellent', or 'good'.",
    )
    has_authenticity_card: bool = Field(
        default=True,
        description="Whether original boutique authenticity card/receipt is included.",
    )


class PurseTransactionInput(BaseModel):
    """Input schema for buying a bag or accepting a seller resale offer."""

    action: str = Field(
        ...,
        pattern=r"^(buy|sell)$",
        description="Transaction direction: 'buy' (purchase bag) or 'sell' (consign/sell bag).",
    )
    bag_reference: str = Field(
        ...,
        min_length=3,
        description="Bag SKU or description (e.g., 'CHANEL-FLAP-001').",
    )
    amount_usd: float = Field(..., gt=0, description="Agreed USD price or payout amount.")
    human_approved: bool = Field(
        default=False,
        description="Explicit human confirmation required before completing high-value transactions.",
    )


class AppraisalQuoteSchema(BaseModel):
    """Structured output schema returned by the luxury resale valuation agent."""

    brand: str = Field(..., description="Luxury brand appraised.")
    model_name: str = Field(..., description="Handbag model name.")
    condition: str = Field(..., description="Verified condition grade.")
    estimated_payout_usd: float = Field(..., ge=0, description="Recommended seller payout in USD.")
    authenticity_notes: str = Field(..., description="Summary of authentication requirements.")
