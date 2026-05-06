"""Builder takedown structuring optimizer.

Opus 4.7 proposes 3–5 alternative takedown structures for a target
deal/section/tier/lot-count, anchored to the firm's prior takedown
schedules and accepted negotiated positions. The LLM produces
structures; Python deterministically computes NPV per structure so
the principal can sort by expected revenue at a constant discount
rate.

Output: Word doc with the structure set + per-structure NPV table
+ the prior firm patterns that informed the proposals.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Pt, RGBColor

from services.common.anthropic_client import OPUS, client
from services.common.config import REPO_ROOT
from services.common.db import cursor
from services.takedown_optimizer.schemas import (
    BuilderTier,
    StructureSet,
    TakedownStructure,
)


SYSTEM_PROMPT = """You are a builder takedown structuring optimizer for a Texas MPC developer. The operator gives you a target deal section, a builder tier, and a lot count. Your job is to propose 3–5 ALTERNATIVE structures — different points on the price/velocity/risk dial — that the firm could defend in negotiation.

Hard rules:

1. ANCHOR TO FIRM PRECEDENT. The firm's prior takedown schedules and accepted negotiated positions are below. Every proposal must reference patterns the firm has already defended. Do not invent terms the firm has never seen accepted.
2. ALTERNATIVE STRUCTURES, NOT VARIATIONS OF ONE. Propose structures that span the dial: high-base/low-escalator vs. low-base/high-escalator; front-loaded velocity vs. steady; tight default-protection vs. flexible. The principal picks one to walk into negotiation; do not produce three nearly-identical proposals.
3. TIER-FIT. Luxury, national_public, and regional_production builders take down at very different velocities, accept different escalators, and respond to different default triggers. Each proposal must explicitly fit the target tier.
4. RATIONALE CITES PATTERNS. In rationale, point to a specific historical pattern from the corpus (e.g. "consistent with our 2024 Lennar takedown's quarterly 4% escalator and 12-lot velocity") — not specific document IDs, but the pattern.
5. RISK NOTES ARE LOAD-BEARING. Every structure has tradeoffs. Surface them: a higher base with a low escalator front-loads revenue but is brittle to absorption misses; a low base with a steep escalator is back-loaded but pressure-tests the builder's underwriting. Be specific.
6. NO NPV. Do NOT compute NPV in your output. The orchestrator computes NPV deterministically from your proposals.
"""


@dataclass
class StructureWithNPV:
    structure: TakedownStructure
    quarters: int
    total_lots: float
    total_revenue: float
    npv: float
    avg_price_per_lot: float


@dataclass
class OptimizerResult:
    deal_slug: str
    section: str
    target_tier: str
    target_lot_count: int
    discount_rate: float
    structure_set: StructureSet
    structures_with_npv: list[StructureWithNPV]
    word_path: str
    cache_read_tokens: int
    cache_creation_tokens: int


def _gather_corpus(deal_id: str | None, target_tier: BuilderTier) -> dict[str, Any]:
    with cursor() as cur:
        if deal_id:
            cur.execute(
                """
                SELECT builder, builder_tier, section, lot_count, base_lot_price,
                       escalator_pct, escalator_basis, option_fee, cadence,
                       velocity_per_qtr, default_triggers
                FROM takedown_schedules
                WHERE deal_id = %s
                ORDER BY first_takedown_on ASC NULLS LAST
                """,
                (deal_id,),
            )
        else:
            cur.execute(
                """
                SELECT builder, builder_tier, section, lot_count, base_lot_price,
                       escalator_pct, escalator_basis, option_fee, cadence,
                       velocity_per_qtr, default_triggers
                FROM takedown_schedules
                ORDER BY first_takedown_on ASC NULLS LAST
                """
            )
        prior_schedules = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT section_title, firm_position, counterparty_position,
                   final_outcome::text AS final_outcome, final_text, rationale, tags,
                   counterparty_tier
            FROM negotiated_positions
            WHERE counterparty_tier = %s
              AND tags && ARRAY['lot-price', 'lot-escalator', 'option-fee',
                                'takedown-velocity', 'EM-go-hard']
            ORDER BY created_at DESC
            LIMIT 30
            """,
            (target_tier,),
        )
        accepted_positions = [dict(r) for r in cur.fetchall()]

    return {
        "prior_schedules": prior_schedules,
        "accepted_positions": accepted_positions,
    }


def _format_corpus_block(
    corpus: dict[str, Any], target_tier: BuilderTier
) -> str:
    schedules = corpus["prior_schedules"]
    if not schedules:
        sched_block = "(no prior takedown schedules in DB — propose conservative structures)"
    else:
        sched_block = "\n".join(
            f"- builder={s['builder']} tier={s['builder_tier']} "
            f"base_lot_price={s.get('base_lot_price')} "
            f"escalator_pct={s.get('escalator_pct')} "
            f"escalator_basis={s.get('escalator_basis')} "
            f"velocity_per_qtr={s.get('velocity_per_qtr')} "
            f"option_fee={s.get('option_fee')} "
            f"cadence={s.get('cadence')}"
            for s in schedules
        )

    positions = corpus["accepted_positions"]
    if not positions:
        pos_block = (
            f"(no accepted negotiated_positions for tier={target_tier} on takedown tags — "
            "extract negotiated_positions from the firm's executed agreements)"
        )
    else:
        pos_block = "\n".join(
            f"- [{p['section_title']} / {p['final_outcome']}] "
            f"firm={p['firm_position']} | counterparty={p.get('counterparty_position') or '(n/a)'} "
            f"| tags={p.get('tags') or []}"
            for p in positions
        )

    return (
        f"[FIRM TAKEDOWN PRECEDENT]\n{sched_block}\n\n"
        f"[FIRM ACCEPTED NEGOTIATED POSITIONS — {target_tier}]\n{pos_block}"
    )


def _resolve_deal_id(deal_slug: str) -> str:
    with cursor() as cur:
        cur.execute("SELECT id FROM deals WHERE slug = %s", (deal_slug,))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"Deal {deal_slug!r} not found.")
    return row["id"]


def _compute_npv(
    *, structure: TakedownStructure, lot_count: int, discount_rate: float
) -> StructureWithNPV:
    if structure.escalator_basis == "quarterly":
        per_q_factor = 1.0 + (structure.escalator_pct or 0.0)
    else:
        per_q_factor = (1.0 + (structure.escalator_pct or 0.0)) ** 0.25

    velocity = max(structure.velocity_per_qtr, 0.0)
    if velocity <= 0:
        return StructureWithNPV(
            structure=structure,
            quarters=0,
            total_lots=0.0,
            total_revenue=0.0,
            npv=0.0,
            avg_price_per_lot=0.0,
        )

    quarters_needed = int(-(-lot_count // max(int(velocity), 1)))
    quarterly_discount = (1.0 + discount_rate) ** 0.25
    remaining = float(lot_count)
    npv = 0.0
    revenue = 0.0
    base = structure.base_lot_price
    qstep = 0
    while remaining > 0 and qstep < quarters_needed + 4:
        lots_q = min(velocity, remaining)
        price = base * (per_q_factor ** qstep)
        rev_q = lots_q * price
        revenue += rev_q
        npv += rev_q / (quarterly_discount ** (qstep + 1))
        remaining -= lots_q
        qstep += 1

    if structure.option_fee:
        npv += structure.option_fee
        revenue += structure.option_fee

    return StructureWithNPV(
        structure=structure,
        quarters=qstep,
        total_lots=float(lot_count),
        total_revenue=revenue,
        npv=npv,
        avg_price_per_lot=revenue / max(lot_count, 1),
    )


def _build_word(
    *,
    deal_slug: str,
    section: str,
    target_tier: BuilderTier,
    target_lot_count: int,
    discount_rate: float,
    set_: StructureSet,
    rated: list[StructureWithNPV],
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = (
        out_dir
        / f"{deal_slug}_takedown_optimizer_{target_tier}_{datetime.utcnow():%Y%m%d_%H%M}.docx"
    )

    doc = Document()
    doc.add_heading(
        f"Takedown structure proposals — {deal_slug} — {section}", level=0
    )
    doc.add_paragraph(
        f"Target tier: {target_tier}\n"
        f"Target lot count: {target_lot_count}\n"
        f"Discount rate: {discount_rate:.2%}\n"
        f"Generated: {datetime.utcnow():%Y-%m-%d %H:%M UTC}"
    )

    banner = doc.add_paragraph()
    run = banner.add_run(
        "PROPOSALS — pick one to walk into negotiation. NPV is computed at the "
        "discount rate above; structures are anchored to prior firm precedent."
    )
    run.bold = True
    run.font.color.rgb = RGBColor(192, 0, 0)

    doc.add_heading("Summary", level=1)
    doc.add_paragraph(set_.summary)

    doc.add_heading("Comparison table", level=1)
    table = doc.add_table(rows=1, cols=6)
    table.style = "Light List"
    h = table.rows[0].cells
    for i, label in enumerate(
        ["Structure", "Base lot price", "Escalator", "Velocity/qtr", "Total revenue", "NPV"]
    ):
        h[i].text = label
        for r in h[i].paragraphs[0].runs:
            r.bold = True
    for r in rated:
        row = table.add_row().cells
        row[0].text = r.structure.label
        row[1].text = f"${r.structure.base_lot_price:,.0f}"
        row[2].text = f"{r.structure.escalator_pct:.2%} {r.structure.escalator_basis}"
        row[3].text = f"{r.structure.velocity_per_qtr:,.1f}"
        row[4].text = f"${r.total_revenue:,.0f}"
        row[5].text = f"${r.npv:,.0f}"

    doc.add_heading("Per-structure detail", level=1)
    for r in rated:
        doc.add_heading(r.structure.label, level=2)
        doc.add_paragraph(
            f"Base lot price: ${r.structure.base_lot_price:,.0f}\n"
            f"Escalator: {r.structure.escalator_pct:.2%} ({r.structure.escalator_basis})\n"
            f"Option fee: "
            f"{('$' + format(r.structure.option_fee, ',.0f')) if r.structure.option_fee else '(none)'}\n"
            f"Velocity: {r.structure.velocity_per_qtr:,.1f} lots/qtr\n"
            f"Cadence: {r.structure.cadence}\n"
            f"Default triggers: {r.structure.default_triggers}\n\n"
            f"Total revenue (nominal): ${r.total_revenue:,.0f}\n"
            f"NPV @ {discount_rate:.2%}: ${r.npv:,.0f}\n"
            f"Quarters to clear {target_lot_count} lots: {r.quarters}\n"
            f"Avg price per lot: ${r.avg_price_per_lot:,.0f}"
        )
        doc.add_heading("Rationale", level=3)
        doc.add_paragraph(r.structure.rationale)
        doc.add_heading("Risk notes", level=3)
        doc.add_paragraph(r.structure.risk_notes)

    doc.save(out_path)
    return out_path


def propose(
    *,
    deal_slug: str,
    section: str,
    target_tier: BuilderTier,
    target_lot_count: int,
    discount_rate: float = 0.12,
    n_proposals: int = 4,
) -> OptimizerResult:
    deal_id = _resolve_deal_id(deal_slug)
    corpus = _gather_corpus(deal_id, target_tier)
    corpus_block = _format_corpus_block(corpus, target_tier)

    user_msg = (
        f"Target deal: {deal_slug}\n"
        f"Section: {section}\n"
        f"Tier: {target_tier}\n"
        f"Lot count: {target_lot_count}\n"
        f"Discount rate (computed deterministically by orchestrator): {discount_rate:.2%}\n\n"
        f"Propose {n_proposals} alternative structures spanning the price/velocity/risk dial. "
        f"Tier-fit, anchor every proposal to firm precedent, and surface tradeoffs."
    )

    a = client()
    response = a.messages.parse(
        model=OPUS,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        system=[
            {"type": "text", "text": SYSTEM_PROMPT},
            {"type": "text", "text": corpus_block, "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": user_msg}],
        output_format=StructureSet,
    )
    set_: StructureSet = response.parsed_output

    rated = [
        _compute_npv(structure=p, lot_count=target_lot_count, discount_rate=discount_rate)
        for p in set_.proposals
    ]

    out_dir = REPO_ROOT / "templates" / "deliverables" / "takedown_optimizer"
    word_path = _build_word(
        deal_slug=deal_slug,
        section=section,
        target_tier=target_tier,
        target_lot_count=target_lot_count,
        discount_rate=discount_rate,
        set_=set_,
        rated=rated,
        out_dir=out_dir,
    )

    return OptimizerResult(
        deal_slug=deal_slug,
        section=section,
        target_tier=target_tier,
        target_lot_count=target_lot_count,
        discount_rate=discount_rate,
        structure_set=set_,
        structures_with_npv=rated,
        word_path=str(word_path),
        cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
    )
