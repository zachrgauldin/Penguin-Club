"""Pydantic schemas for builder takedown structuring proposals."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


BuilderTier = Literal["luxury", "national_public", "regional_production"]


class TakedownStructure(BaseModel):
    label: str = Field(
        ...,
        description=(
            "Short tag for this structure: e.g. 'High base / low escalator', "
            "'Velocity-front-loaded', 'Tight option / flexible velocity'."
        ),
    )
    base_lot_price: float = Field(..., description="USD per lot at first takedown.")
    escalator_pct: float = Field(
        ...,
        description=(
            "Per-period escalator as a decimal (e.g. 0.04 = 4%). "
            "Applied per the escalator_basis below."
        ),
    )
    escalator_basis: Literal["quarterly", "annual"]
    option_fee: float | None = Field(
        None, description="Up-front option fee in USD, if applicable."
    )
    velocity_per_qtr: float = Field(
        ..., description="Lots taken down per quarter (steady-state)."
    )
    cadence: str = Field(
        ...,
        description="Plain-English cadence like 'monthly draws of 5 lots, 15/qtr'.",
    )
    minimum_takedown_per_qtr: int | None = Field(
        None, description="Floor on quarterly takedown to avoid default."
    )
    default_triggers: str = Field(
        ...,
        description=(
            "Specific events that trigger default and the firm's remedy "
            "(option-fee forfeiture, lot reversion, etc.)."
        ),
    )
    rationale: str = Field(
        ...,
        description=(
            "Why this structure fits the target tier and section. Cite prior "
            "accepted positions or takedown_schedules in the firm's corpus by "
            "their pattern (not by ID)."
        ),
    )
    risk_notes: str = Field(
        ...,
        description=(
            "Defensibility, market, and execution risk. What could go wrong, "
            "and what protections in the structure mitigate it."
        ),
    )


class StructureSet(BaseModel):
    deal_slug: str
    section: str
    target_tier: BuilderTier
    target_lot_count: int
    summary: str = Field(
        ...,
        description=(
            "Tradeoff overview across the proposals: price-vs-velocity dial, "
            "risk-vs-revenue dial, the structure most consistent with the firm's "
            "prior accepted positions for this tier."
        ),
    )
    proposals: list[TakedownStructure]
