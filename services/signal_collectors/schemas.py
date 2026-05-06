"""Pydantic schemas for Agent 1's Lavon entitlement and political-risk signals.

Each ingest run produces a NormalizedScan; each CandidateSignal becomes one
row in `signals` (and 0..N rows in `signal_pilot_links` based on
`affected_instruments`). Fields map to the Postgres enums in
db/migrations/003_signals.sql — keep these in sync.
"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from services.reimbursement_api.schemas import PFInstrumentKind


SignalKind = Literal[
    "council_action",
    "pz_action",
    "planner_change",
    "mud_filing",
    "tceq_hearing",
    "ntmwd_action",
    "isd_action",
    "corridor_action",
    "county_action",
    "election_filing",
    "lege_bill",
    "agency_rulemaking",
    "industry_group_action",
    "other",
]


SignalSource = Literal[
    "lavon_council",
    "lavon_pz",
    "lavon_staff",
    "lavon_elections",
    "collin_county",
    "tceq_docket",
    "ntmwd",
    "wylie_isd",
    "community_isd",
    "txdot",
    "nctcog",
    "tx_lege",
    "tceq_rulemaking",
    "tx_ag",
    "tx_comptroller",
    "tab",
    "agc_tx",
    "uli",
    "naiop_reca",
    "other",
]


class CandidateSignal(BaseModel):
    kind: SignalKind
    occurred_on: date | None = Field(
        None, description="Date the action/event happened. Null if undated."
    )
    title: str = Field(..., description="One-line title.")
    summary: str = Field(
        ...,
        description=(
            "2-4 sentences capturing the substance: what happened, who's "
            "affected, and why it matters to a Lavon MPC developer."
        ),
    )
    impact_score: int = Field(
        ...,
        ge=0,
        le=5,
        description=(
            "0 = irrelevant/informational; "
            "1 = adjacent/low; "
            "2 = jurisdictional context; "
            "3 = touches our scope, manageable; "
            "4 = directly affects an active instrument or near-term entitlement; "
            "5 = critical-path event for the pilot (council vote, MUD confirmation, "
            "planner change, key election outcome)."
        ),
    )
    impact_rationale: str = Field(
        ...,
        description=(
            "1-3 sentences explaining the score WITH SPECIFIC reference to the "
            "active deal and instruments. Generic framings like 'this could "
            "affect the deal' are not acceptable."
        ),
    )
    affected_instruments: list[PFInstrumentKind] = Field(
        default_factory=list,
        description=(
            "Instruments directly touched by the signal. Empty if signal is "
            "purely jurisdictional/informational."
        ),
    )


class NormalizedScan(BaseModel):
    source_url: str
    candidates: list[CandidateSignal] = Field(default_factory=list)
