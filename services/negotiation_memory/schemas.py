"""Pydantic schemas for the firm negotiation memory."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DocKind = Literal[
    "psa",
    "loi",
    "lot_purchase",
    "takedown",
    "dev_agreement",
    "reimbursement_agreement",
    "bond_instrument",
    "other",
]


Outcome = Literal["accepted", "rejected", "hedged", "compromised", "ambiguous"]


class NegotiatedPosition(BaseModel):
    section_title: str = Field(
        ...,
        description=(
            "Short canonical name for the negotiated section. Use sparse, reusable "
            "labels — 'Earnest Money', 'Indemnification cap', 'Lot escalator', "
            "'Takedown velocity', 'Post-closing access' — not full clause text."
        ),
    )
    firm_position: str = Field(
        ...,
        description=(
            "What the firm proposed or pushed for in this section. State the "
            "substance, not the verbatim language."
        ),
    )
    counterparty_position: str | None = Field(
        None,
        description="What the counterparty pushed back with, when discernible.",
    )
    final_outcome: Outcome = Field(
        ...,
        description=(
            "How the negotiation landed: accepted (firm position prevailed), "
            "rejected (firm position dropped), hedged (partial concession with "
            "preserved option), compromised (middle landing), ambiguous (unclear)."
        ),
    )
    final_text: str | None = Field(
        None,
        description="Brief excerpt of the final agreement language, if available.",
    )
    rationale: str | None = Field(
        None,
        description="Why the firm took this position; why it landed where it did.",
    )
    source_ref: str | None = Field(
        None,
        description="Page + section reference, e.g. 'p. 8, §3.2'.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description=(
            "Searchable tags. Reuse sparse vocabulary: 'EM-go-hard', "
            "'extension-fee', 'indemnity-cap', 'lot-price', 'lot-escalator', "
            "'takedown-velocity', 'option-fee', 'post-closing-access', "
            "'tax-proration', 'survival', 'choice-of-law'."
        ),
    )
    confidence: float = Field(..., ge=0.0, le=1.0)


class NegotiationExtraction(BaseModel):
    doc_kind: DocKind
    counterparty: str | None
    counterparty_tier: str | None = Field(
        None,
        description=(
            "Builder tier or counterparty class: 'luxury', 'national_public', "
            "'regional_production', 'seller', 'city', 'mud', 'tirz_board', etc."
        ),
    )
    positions: list[NegotiatedPosition] = Field(default_factory=list)
