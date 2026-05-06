"""Dual-extraction pipeline for Agent 3.

Pass A: Sonnet 4.6 with the firm's standard form library cached as a
prompt-prefix anchor. Pass B: Opus 4.7 working independently from the
same source document. The two extractions are compared in code; a date
is canonical only when both passes match on `value` AND `source_ref`
overlaps. Critical dates without agreement land flagged for human review.

This is the kill-switch surface for the firm — guardrails are non-negotiable.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.common.anthropic_client import OPUS, SONNET, client
from services.common.config import REPO_ROOT
from services.sharepoint_watcher.schemas import (
    CRITICAL_DATE_KINDS,
    ContractExtraction,
    ExtractedDate,
    ExtractedObligation,
)


SYSTEM_PROMPT_BASE = """You are a contracts extraction agent for a Texas land developer with a low-volume, high-quality MPC practice. Your job is to extract every critical date, dollar obligation, and (for builder lot-purchase or takedown agreements) the per-builder takedown schedule from a single contract document.

Hard rules:

1. SOURCE-LINK EVERYTHING. Every date and obligation MUST include a `source_ref` pointing back to the document. Use 'p. N, §X.Y' for paginated PDFs and '§X.Y' or paragraph descriptors for documents without stable pagination. If you cannot cite a source, do not extract the field.
2. CRITICAL DATES ARE LOAD-BEARING. Closing, earnest-money go-hard, and takedown deadlines are the firm's kill-switch dates — missing one would terminate trust in the system. When uncertain about a critical date, mark `is_critical: true` and lower the `confidence`; never silently drop one.
3. DO NOT INFER. Extract what the document says. If the document grants extension rights but does not specify the exact extension window, do NOT compute the window — extract what's written and flag the ambiguity in `label`.
4. BUILDER LOT-PURCHASE / TAKEDOWN AGREEMENTS. When `contract_kind` is `lot_purchase` or `takedown` AND the contract specifies a takedown schedule, populate `takedown_schedule`. Builder tier:
   - `luxury` — Toll, Drees, Coventry, Britton, Shaddock, Belclaire
   - `national_public` — DR Horton, Lennar, Pulte, NVR, KB
   - `regional_production` — Trophy, Highland, History Maker, Bloomfield
5. RETURN STRUCTURED JSON. Every field is required unless the schema marks it optional. Empty arrays are valid; do not invent rows.
"""

SYSTEM_PROMPT_PASS_A = (
    SYSTEM_PROMPT_BASE
    + "\n\nThis is pass A (primary extraction). The firm's standard form library is provided below "
    "as a calibration anchor — counterparty redlines deviate from these forms, which is what you're "
    "extracting. Use the forms to recognize standard clauses and to catch missing-from-counterparty edits.\n"
)

SYSTEM_PROMPT_PASS_B = (
    SYSTEM_PROMPT_BASE
    + "\n\nThis is pass B (independent verification). Work directly from the document. Do NOT defer to "
    "any prior extraction — the operator depends on this pass disagreeing with pass A when pass A is "
    "wrong. Be especially rigorous on critical dates (closing, EM-go-hard, takedown).\n"
)


_FIRM_FORM_DIRS: dict[str, list[str]] = {
    "psa": ["templates/firm_psa"],
    "loi": ["templates/firm_psa"],
    "lot_purchase": ["templates/firm_lot_purchase"],
    "takedown": ["templates/firm_lot_purchase"],
    "dev_agreement": ["templates/firm_dev_agreement"],
    "reimbursement_agreement": ["templates/firm_dev_agreement"],
    "other": [],
}


def _load_firm_forms_for_kind(kind_hint: str | None) -> str:
    """Concatenate every text-form template for the given kind hint.

    Operator drops .txt / .md form excerpts (or full forms) into
    templates/firm_<kind>/. Empty until populated; absence just means
    the cached prefix is shorter, not broken.
    """
    if not kind_hint:
        return ""
    dirs = _FIRM_FORM_DIRS.get(kind_hint, [])
    parts: list[str] = []
    for rel in dirs:
        d = REPO_ROOT / rel
        if not d.exists():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix.lower() in {".txt", ".md"}:
                parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")
    return "\n\n".join(parts)


def _build_document_block(file_path: Path) -> dict[str, Any]:
    """Build the content block for the contract file. Supports PDF (base64) and text."""
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        data = base64.standard_b64encode(file_path.read_bytes()).decode("utf-8")
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": data},
        }
    if suffix in {".txt", ".md"}:
        return {"type": "text", "text": file_path.read_text(encoding="utf-8")}
    if suffix == ".docx":
        from docx import Document  # lazy import

        doc = Document(str(file_path))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        return {"type": "text", "text": text}
    raise ValueError(
        f"Unsupported contract file type {suffix!r}. "
        f"Convert to PDF or .txt before extracting."
    )


def _build_system_blocks(
    *,
    pass_label: str,
    kind_hint: str | None,
) -> list[dict[str, Any]]:
    base = SYSTEM_PROMPT_PASS_A if pass_label == "A" else SYSTEM_PROMPT_PASS_B
    forms = _load_firm_forms_for_kind(kind_hint)

    blocks: list[dict[str, Any]] = [{"type": "text", "text": base}]
    if forms:
        blocks.append(
            {
                "type": "text",
                "text": f"[FIRM FORM LIBRARY — {kind_hint}]\n{forms}",
                "cache_control": {"type": "ephemeral"},
            }
        )
    else:
        blocks[-1]["cache_control"] = {"type": "ephemeral"}
    return blocks


def _user_message(file_path: Path, kind_hint: str | None) -> list[dict[str, Any]]:
    instruction = (
        f"Extract every critical date, dollar obligation, and (if applicable) the takedown schedule "
        f"from this contract.\n\n"
        f"Filename: {file_path.name}\n"
        f"Kind hint (may be wrong, verify from the document): {kind_hint or 'unknown'}\n\n"
        f"Return the structured ContractExtraction. Mark `is_critical: true` for closing, EM-go-hard, "
        f"and takedown deadlines. Source-link every date and obligation."
    )
    return [_build_document_block(file_path), {"type": "text", "text": instruction}]


def _ensure_critical_flags(extraction: ContractExtraction) -> ContractExtraction:
    """Force the kill-switch invariant: closing/EM-go-hard/takedown are always critical."""
    for d in extraction.dates:
        if d.kind in CRITICAL_DATE_KINDS:
            d.is_critical = True
    return extraction


def extract_pass(
    *,
    file_path: Path,
    pass_label: str,
    model: str,
    kind_hint: str | None,
) -> ContractExtraction:
    a = client()
    response = a.messages.parse(
        model=model,
        max_tokens=8000,
        thinking={"type": "adaptive"} if model == OPUS else {"type": "disabled"},
        system=_build_system_blocks(pass_label=pass_label, kind_hint=kind_hint),
        messages=[{"role": "user", "content": _user_message(file_path, kind_hint)}],
        output_format=ContractExtraction,
    )
    return _ensure_critical_flags(response.parsed_output)


@dataclass
class DateAgreement:
    kind: str
    label: str
    extraction_a_value: Any
    extraction_a_source: str | None
    extraction_a_model: str | None
    extraction_b_value: Any
    extraction_b_source: str | None
    extraction_b_model: str | None
    agreed: bool
    value: Any
    source_ref: str | None
    is_critical: bool
    confidence: float | None


@dataclass
class ObligationAgreement:
    kind: str
    label: str
    amount: float | None
    unit: str | None
    formula: str | None
    source_ref: str | None
    confidence: float | None


def _normalize_source(s: str | None) -> str:
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _source_overlap(a: str | None, b: str | None) -> bool:
    """Lenient source-ref overlap: page numbers and section markers must coincide."""
    na, nb = _normalize_source(a), _normalize_source(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    a_nums = set(re.findall(r"\d+", a or ""))
    b_nums = set(re.findall(r"\d+", b or ""))
    return bool(a_nums & b_nums) and (na in nb or nb in na or len(na) >= 4 and na[:4] in nb)


def match_dates(a: ContractExtraction, b: ContractExtraction) -> list[DateAgreement]:
    """Pair dates from A and B by (kind, value); produce one DateAgreement per row.

    Strategy: for each date in A, find the first unmatched date in B with the same
    kind AND value. If matched, source_ref overlap decides agreement. Unmatched
    rows on either side land with `agreed = False` and the unmatched side blank.
    """
    rows: list[DateAgreement] = []
    used_b: set[int] = set()
    for da in a.dates:
        partner_idx = None
        for j, db in enumerate(b.dates):
            if j in used_b:
                continue
            if db.kind == da.kind and db.value == da.value:
                partner_idx = j
                break
        if partner_idx is not None:
            db = b.dates[partner_idx]
            used_b.add(partner_idx)
            agreed = _source_overlap(da.source_ref, db.source_ref)
            rows.append(
                DateAgreement(
                    kind=da.kind,
                    label=da.label,
                    extraction_a_value=da.value,
                    extraction_a_source=da.source_ref,
                    extraction_a_model=SONNET,
                    extraction_b_value=db.value,
                    extraction_b_source=db.source_ref,
                    extraction_b_model=OPUS,
                    agreed=agreed,
                    value=da.value if agreed else None,
                    source_ref=da.source_ref if agreed else None,
                    is_critical=da.is_critical or db.is_critical,
                    confidence=min(da.confidence, db.confidence),
                )
            )
        else:
            rows.append(
                DateAgreement(
                    kind=da.kind,
                    label=da.label,
                    extraction_a_value=da.value,
                    extraction_a_source=da.source_ref,
                    extraction_a_model=SONNET,
                    extraction_b_value=None,
                    extraction_b_source=None,
                    extraction_b_model=None,
                    agreed=False,
                    value=None,
                    source_ref=None,
                    is_critical=da.is_critical,
                    confidence=da.confidence,
                )
            )
    for j, db in enumerate(b.dates):
        if j in used_b:
            continue
        rows.append(
            DateAgreement(
                kind=db.kind,
                label=db.label,
                extraction_a_value=None,
                extraction_a_source=None,
                extraction_a_model=None,
                extraction_b_value=db.value,
                extraction_b_source=db.source_ref,
                extraction_b_model=OPUS,
                agreed=False,
                value=None,
                source_ref=None,
                is_critical=db.is_critical,
                confidence=db.confidence,
            )
        )
    return rows


def merge_obligations(
    a: list[ExtractedObligation],
    b: list[ExtractedObligation],
) -> list[ObligationAgreement]:
    """V1: union of obligations from both passes. Operator review surfaces conflicts.

    Obligations are higher-cost-of-disagreement than dates but lower kill-switch
    risk; treating them as a single union keeps the operator surface lean. The
    weekly miss-audit will surface low-confidence obligations for human review.
    """
    merged: list[ObligationAgreement] = []
    for o in a + b:
        merged.append(
            ObligationAgreement(
                kind=o.kind,
                label=o.label,
                amount=o.amount,
                unit=o.unit,
                formula=o.formula,
                source_ref=o.source_ref,
                confidence=o.confidence,
            )
        )
    return merged


@dataclass
class ExtractionResult:
    pass_a: ContractExtraction
    pass_b: ContractExtraction
    date_agreements: list[DateAgreement]
    obligation_rows: list[ObligationAgreement]
    parse_status: str  # 'parsed' | 'needs_human'


def extract_contract(file_path: Path, kind_hint: str | None = None) -> ExtractionResult:
    pass_a = extract_pass(
        file_path=file_path, pass_label="A", model=SONNET, kind_hint=kind_hint
    )
    pass_b = extract_pass(
        file_path=file_path, pass_label="B", model=OPUS, kind_hint=kind_hint
    )
    date_rows = match_dates(pass_a, pass_b)
    obligation_rows = merge_obligations(pass_a.obligations, pass_b.obligations)

    needs_human = any(
        r.is_critical and not r.agreed for r in date_rows
    ) or any(r.kind in CRITICAL_DATE_KINDS and not r.agreed for r in date_rows)
    parse_status = "needs_human" if needs_human else "parsed"

    return ExtractionResult(
        pass_a=pass_a,
        pass_b=pass_b,
        date_agreements=date_rows,
        obligation_rows=obligation_rows,
        parse_status=parse_status,
    )
