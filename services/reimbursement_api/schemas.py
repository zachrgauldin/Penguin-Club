"""Pydantic schemas for Agent 2's structured outputs.

Used as the response format for `client.messages.parse()` so Opus 4.7 returns
validated, typed Structuring proposals instead of freeform JSON. Schema fields
map 1:1 to the `pf_positions` table columns the structuring writer persists.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


PFInstrumentKind = Literal["pid", "mud", "tirz", "380", "381"]

StructuringFamily = Literal[
    "soft_cost_capture",
    "stacking_layout",
    "grant_on_commercial",
    "timing_escalator",
]


class StructuringProposal(BaseModel):
    family: StructuringFamily
    title: str = Field(..., description="One-line proposal title.")
    instrument_kinds: list[PFInstrumentKind] = Field(
        ...,
        description="Instruments this proposal touches.",
    )
    eligibility_rules_stretched: list[str] = Field(
        ...,
        description=(
            "Eligibility category paths this proposal stretches or relies on, "
            "in dotted form like 'pid.indirect.developer_carry_interest' or "
            "'mud.hard_cost.roads_30pct_cap'."
        ),
    )
    accepted_positions_cited: list[str] = Field(
        default_factory=list,
        description=(
            "Titles of prior accepted firm positions (from the accepted-position "
            "library) that support this proposal. Empty if no prior precedent."
        ),
    )
    estimated_dollars_at_stake: float = Field(
        ...,
        description=(
            "Rough order-of-magnitude dollar value of this proposal to the deal. "
            "Use 0 if the proposal is structural (no direct dollar value)."
        ),
    )
    proposal: str = Field(
        ...,
        description=(
            "The proposal itself, 2-4 paragraphs. Be specific about bond order "
            "language, project plan amendments, dev/reimbursement agreement terms, "
            "or assessment methodology. Counsel must opine on every structural element."
        ),
    )
    risk_notes: str = Field(
        ...,
        description=(
            "Audit, compliance, political, and defensibility risk. How the firm "
            "would defend this position years later in a diligence review or audit."
        ),
    )


class StructuringProposalSet(BaseModel):
    deal_slug: str = Field(..., description="Slug of the active deal these proposals are for.")
    summary: str = Field(
        ...,
        description=(
            "Executive summary across all proposals: total dollars at stake, top "
            "families to focus on, biggest open risk for advisor review. 2 paragraphs."
        ),
    )
    proposals: list[StructuringProposal]
