"""Agent 2 — Structuring mode.

Generates frontier structuring proposals across the four families on the
active pilot deal, using Opus 4.7 with adaptive thinking, the eligibility
schemas + accepted-position library cached as the system-prompt prefix,
and a Pydantic-validated JSON output.

Persists each proposal as a row in `pf_positions` and produces a Word
deliverable for bond counsel + municipal advisor + PID administrator review.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from services.common.anthropic_client import OPUS, client
from services.common.config import REPO_ROOT
from services.common.db import cursor

from services.reimbursement_api.loader import (
    AcceptedPosition,
    InstrumentSchema,
    load_accepted_positions,
    load_active_deal_context,
    load_eligibility_schemas,
)
from services.reimbursement_api.schemas import StructuringProposal, StructuringProposalSet


SYSTEM_PROMPT = """You are a public-finance instrument co-author for a high-quality MPC developer in Texas. Your job is to surface frontier structuring proposals across stacked PID + MUD + TIRZ + 380/381 instruments — wider eligibility shells, layered grants, timing/escalator structure — that the developer's bond counsel, municipal advisor, and PID administrator will then accept, hedge, or decline.

Hard rules:

1. COUNSEL MUST OPINE. Every proposal you generate is a draft for advisors to review. You do not opine on bond covenants, indenture interpretation, or the legal sufficiency of any structure. Bond counsel decides what language goes in the bond order; the municipal advisor decides what structures the market will accept; the PID administrator decides what assessment methodology is operationally defensible.
2. SOURCE-LINK EVERYTHING. Every proposal must cite the eligibility_rules categories it stretches (in dotted form like `pid.indirect.developer_carry_interest`) and any prior accepted positions in the firm's library that support it.
3. ESTIMATE DOLLARS AT STAKE. Every proposal must include a rough order-of-magnitude dollar estimate. If the proposal is purely structural (no direct dollar value), use 0 and explain in risk_notes.
4. DEFENSIBILITY FIRST. Be explicit about the audit, compliance, political, and reputational risk a proposal raises and how the firm would defend it years later in a diligence review or audit.
5. EXTEND ACCEPTED PRECEDENT BEFORE INVENTING NEW. If the accepted-position library contains a precedent that supports a proposal, cite it by title in `accepted_positions_cited` and lean on that defensibility.

You generate proposals across exactly four families. Pick the family that best fits each proposal; do not split one idea across families.

[soft_cost_capture]
Engineering, legal, financing/carry, management fees, marketing, and indirect development costs. Push the eligible cost shell wider than the firm's prior practice — within bond counsel's view of what statute and bond-order language can support. Examples: developer carry interest on outstanding reimbursable balances, project management fee allocable to PID-funded scope, narrow attribution of public-improvement marketing.

[stacking_layout]
Sequenced PID + MUD + TIRZ + 380/381 layout for this deal. Identify remaining capacity for each, the entitlement steps each needs, and how reimbursable buckets overlap so we don't double-claim or under-claim. Propose specific allocations of road costs (TCEQ 30% rule), parks/amenity, and public infrastructure between instruments. Identify which instrument is best positioned for which cost family.

[grant_on_commercial]
380/381 performance grants stacked on horizontal financing for outparcel/retail/BTR/MF. Identify the trigger metrics (CO, sales tax, ad valorem retention, jobs), the public-benefit narrative, and the back-end exit value uplift. Pair-able with the TIRZ project plan when appropriate.

[timing_escalator]
Interest/carry on outstanding reimbursable balances, escalating caps, structuring for later bond series (e.g. Series 2026A vs. 2027B), and interest-rate floor/ceiling mechanics. Propose specific rates, accrual bases, escalator indices, and series-by-series authorization windows that capture more dollars sooner.

The active deal, its full eligibility schemas for all five instruments, and the firm's accepted-position library are below. Generate 8–12 proposals across the four families. Concentrate effort where dollars and accepted-precedent support concentrate; don't pad.
"""


@dataclass
class StructuringRun:
    proposal_set: StructuringProposalSet
    persisted_position_ids: list[str]
    deliverable_path: Path
    cache_read_tokens: int
    cache_creation_tokens: int


def _build_system_blocks(
    schemas: list[InstrumentSchema],
    accepted: list[AcceptedPosition],
) -> list[dict[str, Any]]:
    """Assemble the cached system prompt: instructions + schemas + accepted library.

    Cache breakpoint goes on the LAST block so the SDK caches the entire prefix
    in one ephemeral entry. Any byte change in the prefix invalidates the cache,
    so the schemas and accepted-position library must be deterministic.
    """
    schema_dump = "\n\n".join(
        f"---\n# {s.name} ({s.kind}) — statute: {s.statute_ref}\n{s.raw_yaml}"
        for s in schemas
    )
    schemas_block = f"[ELIGIBILITY SCHEMAS]\n{schema_dump}"

    if accepted:
        accepted_dump = "\n\n".join(
            f"- title: {p.title}\n  family: {p.family}\n"
            f"  estimated_dollars: {p.estimated_dollars}\n"
            f"  incorporated_into: {p.incorporated_into}\n"
            f"  proposal: |\n    " + p.proposal.replace("\n", "\n    ")
            for p in accepted
        )
        accepted_block = f"[ACCEPTED-POSITION LIBRARY]\n{accepted_dump}"
    else:
        accepted_block = (
            "[ACCEPTED-POSITION LIBRARY]\n"
            "(empty — this is the firm's first cycle of advisor-validated positions on this deal)"
        )

    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text", "text": schemas_block},
        {"type": "text", "text": accepted_block, "cache_control": {"type": "ephemeral"}},
    ]


def _build_user_message(ctx: dict[str, Any]) -> str:
    deal = ctx["deal"]
    instruments = ctx["instruments"]

    inst_rows = "\n".join(
        f"- {i['kind']} — {i['name']} — status={i['status']} "
        f"— authorized={i['authorized_amount']} issued={i['issued_amount']} "
        f"capacity_remaining={i['capacity_remaining']}"
        for i in instruments
    )

    return (
        f"Active deal: {deal['name']} ({deal['jurisdiction']}, {deal['county']} County, {deal['state']})\n"
        f"Slug: {deal['slug']}\n"
        f"Stage: {deal['status']}\n"
        f"Stage notes: {deal.get('stage_notes') or '(none)'}\n\n"
        f"Active instruments:\n{inst_rows}\n\n"
        "Generate 8–12 structuring proposals across the four families "
        "(soft_cost_capture, stacking_layout, grant_on_commercial, timing_escalator). "
        "For each proposal:\n"
        "- Pick exactly one family.\n"
        "- Cite the eligibility_rules categories it stretches in dotted form.\n"
        "- Cite any prior accepted positions by title.\n"
        "- Give a rough dollar estimate (use 0 if structural-only).\n"
        "- Be specific about bond-order language, project plan amendments, "
        "dev/reimbursement agreement terms, or assessment methodology.\n"
        "- Include a defensibility section in risk_notes.\n\n"
        "Concentrate on the highest-leverage proposals; do not pad to a count target."
    )


def _persist_proposal(cur, deal_id: str, model_id: str, prop: StructuringProposal) -> str:
    cur.execute(
        """
        INSERT INTO pf_positions (
            deal_id, family, title, proposal, estimated_dollars,
            risk_notes, model_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            deal_id,
            prop.family,
            prop.title,
            prop.proposal
            + "\n\n--- eligibility rules stretched ---\n"
            + "\n".join(f"- {r}" for r in prop.eligibility_rules_stretched)
            + (
                "\n\n--- accepted positions cited ---\n"
                + "\n".join(f"- {r}" for r in prop.accepted_positions_cited)
                if prop.accepted_positions_cited
                else ""
            ),
            prop.estimated_dollars_at_stake,
            prop.risk_notes,
            model_id,
        ),
    )
    return cur.fetchone()["id"]


def run_structuring() -> StructuringRun:
    ctx = load_active_deal_context()
    schemas = load_eligibility_schemas(ctx["deal"]["slug"])
    accepted = load_accepted_positions(ctx["deal"]["slug"])

    system_blocks = _build_system_blocks(schemas, accepted)
    user_message = _build_user_message(ctx)

    a = client()
    response = a.messages.parse(
        model=OPUS,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=system_blocks,
        messages=[{"role": "user", "content": user_message}],
        output_format=StructuringProposalSet,
    )
    proposal_set: StructuringProposalSet = response.parsed_output

    position_ids: list[str] = []
    with cursor() as cur:
        for p in proposal_set.proposals:
            position_ids.append(_persist_proposal(cur, ctx["deal"]["id"], OPUS, p))

    from services.reimbursement_api.deliverables import write_structuring_docx

    deliverable_path = write_structuring_docx(
        ctx=ctx,
        proposal_set=proposal_set,
        generated_at=datetime.utcnow(),
    )

    return StructuringRun(
        proposal_set=proposal_set,
        persisted_position_ids=position_ids,
        deliverable_path=deliverable_path,
        cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
    )


if __name__ == "__main__":
    run = run_structuring()
    print(
        json.dumps(
            {
                "deal": run.proposal_set.deal_slug,
                "n_proposals": len(run.proposal_set.proposals),
                "persisted_ids": run.persisted_position_ids,
                "deliverable": str(run.deliverable_path),
                "cache_read_tokens": run.cache_read_tokens,
                "cache_creation_tokens": run.cache_creation_tokens,
            },
            indent=2,
        )
    )
