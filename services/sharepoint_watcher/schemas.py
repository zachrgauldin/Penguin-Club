"""Pydantic schemas for Agent 3's contract extractions.

Each pass (Sonnet 4.6 pass A + Opus 4.7 pass B) returns a ContractExtraction.
The agreement step compares the two and writes rows to `contracts`, `dates`,
`obligations`, and `takedown_schedules`. A critical date is canonical
(`agreed = TRUE`, `value` populated) only when both passes match on
`value` AND `source_ref` overlaps.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


ContractKind = Literal[
    "psa",
    "loi",
    "lot_purchase",
    "takedown",
    "dev_agreement",
    "reimbursement_agreement",
    "other",
]

DateKind = Literal[
    "effective",
    "feasibility_end",
    "em_go_hard",
    "extension_window_start",
    "extension_window_end",
    "closing",
    "takedown",
    "option_exercise",
    "post_closing_obligation",
    "expiration",
    "other",
]

ObligationKind = Literal[
    "earnest_money",
    "extension_fee",
    "escrow_cap",
    "indemnity_cap",
    "liquidated_damages",
    "lot_price",
    "lot_escalator",
    "option_fee",
    "lot_premium",
    "other",
]

CounterpartyTier = Literal[
    "luxury",
    "national_public",
    "regional_production",
    "seller",
    "city",
    "mud",
    "tirz_board",
    "other",
]

BuilderTier = Literal["luxury", "national_public", "regional_production"]

CRITICAL_DATE_KINDS: set[DateKind] = {"closing", "em_go_hard", "takedown"}


class ExtractedDate(BaseModel):
    kind: DateKind
    label: str = Field(..., description="Human-readable date name from the contract.")
    value: date
    source_ref: str = Field(
        ...,
        description=(
            "Page + section reference, e.g. 'p. 12, §4.3(b)' for paginated PDFs, "
            "or '§4.3(b)' for documents without stable pagination. Required."
        ),
    )
    is_critical: bool = Field(
        ...,
        description=(
            "True for closing, EM-go-hard, and takedown deadlines. These dates require "
            "dual-extraction agreement before they propagate to the operational calendar."
        ),
    )
    confidence: float = Field(..., ge=0.0, le=1.0)


class ExtractedObligation(BaseModel):
    kind: ObligationKind
    label: str
    amount: float | None = Field(None, description="Numeric value if applicable.")
    unit: str | None = Field(None, description="USD, USD per lot, percent, etc.")
    formula: str | None = Field(
        None,
        description="For escalators/computed obligations: e.g. '5% per annum compounded'.",
    )
    source_ref: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class ExtractedTakedownSchedule(BaseModel):
    builder: str
    builder_tier: BuilderTier | None
    section: str | None = Field(None, description="Phase/section identifier if specified.")
    lot_count: int | None
    base_lot_price: float | None
    escalator_pct: float | None = Field(
        None,
        description="Annual escalator as a decimal (0.05 for 5%).",
    )
    escalator_basis: str | None
    option_fee: float | None
    cadence: str | None = Field(
        None,
        description="e.g. '10 lots per quarter', 'monthly draw of 5 lots'.",
    )
    first_takedown_on: date | None
    last_takedown_on: date | None
    velocity_per_qtr: float | None
    default_triggers: str | None
    source_ref: str


class ContractExtraction(BaseModel):
    contract_kind: ContractKind
    counterparty: str = Field(..., description="Counterparty's full legal name as written in the contract.")
    counterparty_tier: CounterpartyTier | None
    title: str = Field(..., description="Short title summarizing the document.")
    effective_date: date | None
    dates: list[ExtractedDate] = Field(default_factory=list)
    obligations: list[ExtractedObligation] = Field(default_factory=list)
    takedown_schedule: ExtractedTakedownSchedule | None = Field(
        None,
        description=(
            "Populate ONLY when contract_kind is 'lot_purchase' or 'takedown' "
            "AND the document specifies a takedown schedule. Otherwise leave null."
        ),
    )
