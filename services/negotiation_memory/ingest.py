"""Ingest a single executed agreement into the firm negotiation memory.

Sonnet 4.6 reads the document and identifies negotiated sections — the
parts of the agreement that diverged from a standard form. Each finding
becomes a `negotiated_positions` row with section_title, firm position,
counterparty position, outcome, and tags.

For V1, run on executed PSAs / lot-purchase / takedown / dev / reimbursement
agreements one at a time. Pair with redline-history input later (Wave 2.5)
when the operator's redline corpus is more accessible.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.common.anthropic_client import SONNET, client
from services.common.db import cursor
from services.negotiation_memory.schemas import (
    DocKind,
    NegotiatedPosition,
    NegotiationExtraction,
)


SYSTEM_PROMPT = """You are reading an executed agreement to populate a firm's negotiation memory. Your job is to identify the sections that were ACTUALLY NEGOTIATED — places where the firm took a non-default position or where the final language diverges from a standard form.

Hard rules:

1. ONLY EXTRACT NEGOTIATED SECTIONS. Skip boilerplate, statute references, and recitations. If a section reads as standard market language with no party-specific tuning, do NOT extract it.
2. SECTION_TITLE IS A REUSABLE LABEL. Use sparse, canonical names (e.g. 'Earnest Money', 'Indemnification cap', 'Lot escalator') so future queries can group across documents. Do NOT use full clause titles or hierarchical IDs.
3. STATE FIRM POSITION IN SUBSTANCE, NOT WORDS. 'EM goes hard at 90 days post-effective with $50K non-refundable' beats quoting the clause verbatim.
4. SOURCE-LINK. Every position MUST include source_ref pointing back to the document.
5. TAGS ARE THE QUERY HANDLE. Use sparse, reusable tags. The most useful queries hit one tag and one counterparty_tier — pick tags that will be reusable across documents.
6. CONFIDENCE BELOW 0.7 IS THE THRESHOLD FOR HUMAN REVIEW. If you're not certain a section was meaningfully negotiated, set confidence ≤ 0.7 and note why in rationale.
7. DOC_KIND. The closest match from the schema's DocKind enum, based on the document's content (not the filename).
8. COUNTERPARTY_TIER. For builder agreements, classify as luxury / national_public / regional_production. For seller/city/MUD agreements, use seller / city / mud / tirz_board accordingly.
"""


@dataclass
class IngestResult:
    contract_id: str | None
    n_positions: int
    doc_kind: str
    counterparty: str | None
    counterparty_tier: str | None
    cache_read_tokens: int
    cache_creation_tokens: int


def _build_document_block(file_path: Path) -> dict[str, Any]:
    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(file_path.read_bytes()).decode("utf-8"),
            },
        }
    if suffix in {".txt", ".md"}:
        return {"type": "text", "text": file_path.read_text(encoding="utf-8")}
    if suffix == ".docx":
        from docx import Document  # lazy import

        doc = Document(str(file_path))
        return {"type": "text", "text": "\n".join(p.text for p in doc.paragraphs if p.text.strip())}
    raise ValueError(f"Unsupported file type {suffix!r}; convert to PDF/docx/txt.")


def _resolve_deal_id(deal_slug: str | None) -> str | None:
    if not deal_slug:
        return None
    with cursor() as cur:
        cur.execute("SELECT id FROM deals WHERE slug = %s", (deal_slug,))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"Deal {deal_slug!r} not found.")
    return row["id"]


def _persist_positions(
    *,
    extraction: NegotiationExtraction,
    deal_id: str | None,
    contract_id: str | None,
    source_uri: str,
) -> int:
    n = 0
    with cursor() as cur:
        for p in extraction.positions:
            cur.execute(
                """
                INSERT INTO negotiated_positions (
                    contract_id, deal_id, doc_kind, counterparty, counterparty_tier,
                    section_title, firm_position, counterparty_position,
                    final_outcome, final_text, rationale, source_doc_uri,
                    source_ref, tags, confidence, model_id
                )
                VALUES (
                    %s, %s, %s::negotiation_doc_kind, %s, %s,
                    %s, %s, %s,
                    %s::negotiation_outcome, %s, %s, %s,
                    %s, %s, %s, %s
                )
                """,
                (
                    contract_id,
                    deal_id,
                    extraction.doc_kind,
                    extraction.counterparty,
                    extraction.counterparty_tier,
                    p.section_title,
                    p.firm_position,
                    p.counterparty_position,
                    p.final_outcome,
                    p.final_text,
                    p.rationale,
                    source_uri,
                    p.source_ref,
                    p.tags,
                    p.confidence,
                    SONNET,
                ),
            )
            n += 1
    return n


def _find_existing_contract(source_uri: str) -> str | None:
    """Link to a previously-extracted contract row when the URIs match."""
    with cursor() as cur:
        cur.execute("SELECT id FROM contracts WHERE document_uri = %s", (source_uri,))
        row = cur.fetchone()
    return row["id"] if row else None


def ingest_document(
    *,
    file_path: Path,
    deal_slug: str | None = None,
    doc_kind_hint: DocKind | None = None,
) -> IngestResult:
    deal_id = _resolve_deal_id(deal_slug)
    contract_id = _find_existing_contract(str(file_path))

    user_content: list[dict[str, Any]] = [
        _build_document_block(file_path),
        {
            "type": "text",
            "text": (
                f"Filename: {file_path.name}\n"
                f"Doc-kind hint (verify from contents): {doc_kind_hint or 'unknown'}\n\n"
                "Extract every negotiated position from this executed agreement. "
                "Set doc_kind based on the document's content. Only include sections "
                "that were meaningfully negotiated; skip boilerplate."
            ),
        },
    ]

    a = client()
    response = a.messages.parse(
        model=SONNET,
        max_tokens=8000,
        thinking={"type": "disabled"},
        system=[
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": user_content}],
        output_format=NegotiationExtraction,
    )
    extraction: NegotiationExtraction = response.parsed_output

    n_persisted = _persist_positions(
        extraction=extraction,
        deal_id=deal_id,
        contract_id=contract_id,
        source_uri=str(file_path),
    )

    return IngestResult(
        contract_id=contract_id,
        n_positions=n_persisted,
        doc_kind=extraction.doc_kind,
        counterparty=extraction.counterparty,
        counterparty_tier=extraction.counterparty_tier,
        cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
    )
