"""Word-doc deliverable generator for Agent 2 Structuring proposals.

Produces a ready-to-circulate review packet for bond counsel + municipal
advisor + PID administrator. Every proposal carries a "COUNSEL MUST OPINE"
banner and per-advisor sign-off lines for accept / hedge / decline + notes,
which the operator transcribes back into `pf_positions.*_view` columns
once advisors respond.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Pt, RGBColor

from services.common.config import REPO_ROOT
from services.reimbursement_api.schemas import StructuringProposalSet


FAMILY_ORDER = [
    ("soft_cost_capture", "Soft-cost capture"),
    ("stacking_layout", "Stacking layout"),
    ("grant_on_commercial", "Grants on retained commercial (380 / 381)"),
    ("timing_escalator", "Timing & escalator structure"),
]


def _add_banner(doc: Document, text: str, *, color: tuple[int, int, int] = (192, 0, 0)) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor(*color)


def _add_signoff_block(doc: Document, advisor_label: str) -> None:
    p = doc.add_paragraph()
    run = p.add_run(f"{advisor_label}:  [ ] accept  [ ] hedge  [ ] decline")
    run.font.size = Pt(10)
    notes = doc.add_paragraph()
    notes_run = notes.add_run("Notes: _______________________________________________________________")
    notes_run.font.size = Pt(10)


def write_structuring_docx(
    *,
    ctx: dict[str, Any],
    proposal_set: StructuringProposalSet,
    generated_at: datetime,
    out_dir: Path | None = None,
) -> Path:
    deal = ctx["deal"]
    out_dir = out_dir or (REPO_ROOT / "templates" / "deliverables")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (
        f"{deal['slug']}_structuring_{generated_at.strftime('%Y%m%d_%H%M')}.docx"
    )

    doc = Document()

    title = doc.add_heading(
        f"Structuring Proposals — {deal['name']}", level=0
    )
    doc.add_paragraph(
        f"For: Bond counsel, municipal advisor, PID administrator\n"
        f"Generated: {generated_at.strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"Deal: {deal['name']} ({deal['jurisdiction']}, {deal['county']} County, {deal['state']})"
    )

    _add_banner(
        doc,
        "COUNSEL MUST OPINE — Every proposal below is a draft for advisor review. "
        "Bond counsel decides what language goes in the bond order; the municipal "
        "advisor decides what structures the market will accept; the PID administrator "
        "decides what assessment methodology is operationally defensible.",
    )

    doc.add_heading("Executive summary", level=1)
    doc.add_paragraph(proposal_set.summary)

    grouped: dict[str, list] = {fam: [] for fam, _ in FAMILY_ORDER}
    for p in proposal_set.proposals:
        grouped.setdefault(p.family, []).append(p)

    proposal_idx = 0
    for family_key, family_label in FAMILY_ORDER:
        if not grouped.get(family_key):
            continue
        doc.add_heading(family_label, level=1)
        for prop in grouped[family_key]:
            proposal_idx += 1
            doc.add_heading(f"{proposal_idx}. {prop.title}", level=2)

            meta_para = doc.add_paragraph()
            meta_para.add_run("Family: ").bold = True
            meta_para.add_run(prop.family + "\n")
            meta_para.add_run("Instruments: ").bold = True
            meta_para.add_run(", ".join(prop.instrument_kinds) + "\n")
            meta_para.add_run("Estimated dollars at stake: ").bold = True
            meta_para.add_run(f"${prop.estimated_dollars_at_stake:,.0f}\n")
            meta_para.add_run("Eligibility rules stretched: ").bold = True
            meta_para.add_run(", ".join(prop.eligibility_rules_stretched) + "\n")
            if prop.accepted_positions_cited:
                meta_para.add_run("Prior accepted positions cited: ").bold = True
                meta_para.add_run(", ".join(prop.accepted_positions_cited))
            else:
                meta_para.add_run("Prior accepted positions cited: ").bold = True
                meta_para.add_run("(none — this is novel)")

            doc.add_heading("Proposal", level=3)
            doc.add_paragraph(prop.proposal)

            doc.add_heading("Risk & defensibility notes", level=3)
            doc.add_paragraph(prop.risk_notes)

            doc.add_heading("Advisor sign-off", level=3)
            _add_signoff_block(doc, "Bond counsel")
            _add_signoff_block(doc, "Municipal advisor")
            _add_signoff_block(doc, "PID administrator")
            doc.add_paragraph()

    doc.save(out_path)
    return out_path
