"""Agent 2 Capture mode — cost-ledger line classification.

Walks unclassified rows in `cost_ledger` for the active deal, sends
batches to Sonnet 4.6 with the eligibility schemas + accepted-position
library cached as the system-prompt prefix, and writes per-instrument
rows to `ledger_classifications`. A single ledger line can land in
multiple instruments (e.g. a road cost split MUD 30% / PID 70%).

Acceptance bar: ≥95% bucket match against advisor-approved
classifications on the next packet, ≤20% rework, ≥1 missed-backup item
caught. The first thing this surfaces is missing `backup_uri` rows —
those are the punch list.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from services.common.anthropic_client import SONNET, client
from services.common.db import cursor
from services.reimbursement_api.loader import (
    AcceptedPosition,
    InstrumentSchema,
    load_accepted_positions,
    load_active_deal_context,
    load_eligibility_schemas,
)
from services.reimbursement_api.schemas import PFInstrumentKind


CLASSIFY_BATCH_SIZE = 10


class InstrumentBucket(BaseModel):
    instrument_kind: PFInstrumentKind = Field(
        ...,
        description="Which instrument's eligibility shell this portion of the line goes into.",
    )
    category: str = Field(
        ...,
        description=(
            "Eligibility category in dotted form, matching the eligibility "
            "schemas (e.g. 'hard_cost.water_sewer', 'soft_cost.engineering', "
            "'indirect.developer_carry_interest')."
        ),
    )
    eligible_amount: float = Field(
        ...,
        description=(
            "Dollar amount of THIS ledger line that goes to THIS instrument's "
            "bucket. May be < line amount when splitting across instruments. "
            "Sum across buckets must equal the line amount when "
            "is_non_eligible is false."
        ),
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str = Field(
        ...,
        description=(
            "1-2 sentences citing the eligibility_rules category that supports "
            "this bucket assignment, plus any prior accepted positions if relevant."
        ),
    )


class LineClassification(BaseModel):
    line_index: int = Field(
        ...,
        description="Index of the ledger line in the request batch (0-based).",
    )
    is_non_eligible: bool = Field(
        ...,
        description="True if no portion of this line is reimbursable under any active instrument.",
    )
    bucket_assignments: list[InstrumentBucket] = Field(default_factory=list)
    missing_backup: bool = Field(
        ...,
        description=(
            "True when the description references invoice/work/vendor evidence the "
            "operator should attach (e.g. 'engineer's invoice', 'pay app #4') but "
            "no backup_uri was provided. Drives the missing-backup punch list."
        ),
    )
    flags: list[Literal["needs_advisor_review", "ambiguous_split", "outside_scope", "exotic_clause"]] = Field(
        default_factory=list,
        description="Hand-off signals for the human reviewer.",
    )
    notes: str | None = None


class ClassifyBatchResponse(BaseModel):
    classifications: list[LineClassification]


SYSTEM_PROMPT = """You are a public-finance reimbursement classifier for a Texas MPC developer's stacked PID + MUD + TIRZ + 380/381 instruments. For each cost-ledger line you receive, decide which instrument bucket(s) the dollars land in, citing the eligibility schemas and the firm's accepted-position library.

Hard rules:

1. ELIGIBILITY MUST CITE A RULE. Every bucket assignment must reference an eligibility_rules `category` from the schemas attached. If no rule supports a bucket, set is_non_eligible: true and explain in notes.
2. SUM-INTEGRITY. When is_non_eligible is false, the sum of `eligible_amount` across `bucket_assignments` must equal the line's `amount` to the cent. Do not silently drop dollars.
3. MULTI-INSTRUMENT SPLITS. Single ledger lines often split across instruments (TCEQ 30% road rule, parks shared MUD/PID, soft costs allocable across both). Make the split explicit, not approximate.
4. PRECEDENT BEFORE NOVELTY. If the firm's accepted-position library covers this kind of line, follow the precedent and cite it in rationale. Do NOT reinvent.
5. MISSING-BACKUP PUNCH LIST. Set missing_backup: true when the description references attached evidence (an invoice number, pay app, change order, soft-cost timesheet) but the row has no backup_uri. This is the punch list the operator chases before the packet ships.
6. FLAG, DON'T GUESS. Use `flags` for anything ambiguous, exotic, out-of-scope, or that should hit advisor review. Confidence below 0.85 should always carry an explanatory flag.
7. RETURN length matches input length and uses the line_index field to map back. Do not skip lines.
"""


@dataclass
class ClassifyResult:
    deal_slug: str
    n_lines_processed: int
    n_classifications_written: int
    n_non_eligible: int
    n_missing_backup: int
    n_low_confidence: int
    cache_read_tokens: int
    cache_creation_tokens: int


def _build_system_blocks(
    schemas: list[InstrumentSchema],
    accepted: list[AcceptedPosition],
) -> list[dict[str, Any]]:
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
        accepted_block = "[ACCEPTED-POSITION LIBRARY]\n(empty)"

    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text", "text": schemas_block},
        {"type": "text", "text": accepted_block, "cache_control": {"type": "ephemeral"}},
    ]


def _fetch_pending_lines(deal_id: str, limit: int) -> list[dict[str, Any]]:
    sql = """
        SELECT cl.id, cl.posted_on, cl.vendor, cl.invoice_number,
               cl.description, cl.amount, cl.gl_account, cl.backup_uri
        FROM cost_ledger cl
        WHERE cl.deal_id = %s
          AND NOT EXISTS (
              SELECT 1 FROM ledger_classifications lc
              WHERE lc.cost_ledger_id = cl.id
          )
        ORDER BY cl.posted_on ASC, cl.id ASC
        LIMIT %s
    """
    with cursor() as cur:
        cur.execute(sql, (deal_id, limit))
        return [dict(r) for r in cur.fetchall()]


def _resolve_instrument_ids(deal_id: str) -> dict[str, str]:
    with cursor() as cur:
        cur.execute(
            "SELECT id, kind::text FROM instruments WHERE deal_id = %s",
            (deal_id,),
        )
        return {r["kind"]: r["id"] for r in cur.fetchall()}


def _line_block(idx: int, line: dict[str, Any]) -> str:
    return (
        f"line_index: {idx}\n"
        f"  posted_on: {line['posted_on']}\n"
        f"  vendor: {line.get('vendor') or ''}\n"
        f"  invoice_number: {line.get('invoice_number') or ''}\n"
        f"  description: {line['description']}\n"
        f"  amount: {line['amount']}\n"
        f"  gl_account: {line.get('gl_account') or ''}\n"
        f"  backup_uri_present: {bool(line.get('backup_uri'))}"
    )


def _classify_batch(
    *,
    system_blocks: list[dict[str, Any]],
    batch: list[dict[str, Any]],
) -> tuple[ClassifyBatchResponse, int, int]:
    user_msg = (
        "Classify each line below. Return one classification per line, with "
        "matching line_index. Sum bucket eligible_amount = line amount when "
        "the line is eligible.\n\n"
        + "\n\n".join(_line_block(i, line) for i, line in enumerate(batch))
    )

    a = client()
    response = a.messages.parse(
        model=SONNET,
        max_tokens=8000,
        thinking={"type": "disabled"},
        system=system_blocks,
        messages=[{"role": "user", "content": user_msg}],
        output_format=ClassifyBatchResponse,
    )
    cache_read = getattr(response.usage, "cache_read_input_tokens", 0) or 0
    cache_creation = getattr(response.usage, "cache_creation_input_tokens", 0) or 0
    return response.parsed_output, cache_read, cache_creation


def _persist_classifications(
    *,
    cur,
    line: dict[str, Any],
    classification: LineClassification,
    instrument_ids: dict[str, str],
) -> int:
    if classification.is_non_eligible:
        cur.execute(
            """
            INSERT INTO ledger_classifications (
                cost_ledger_id, instrument_id, category, eligible_amount,
                confidence, rationale, model_id
            )
            SELECT %s, NULL, %s, 0, %s, %s, %s
            WHERE FALSE
            """,
            (line["id"], "non_eligible", 0.0, "non-eligible", SONNET),
        )
        return 0

    n = 0
    notes_extra: list[str] = []
    if classification.flags:
        notes_extra.append("flags: " + ", ".join(classification.flags))
    if classification.missing_backup:
        notes_extra.append("missing_backup: true")
    if classification.notes:
        notes_extra.append(classification.notes)
    rationale_suffix = (" | " + "; ".join(notes_extra)) if notes_extra else ""

    for bucket in classification.bucket_assignments:
        instrument_id = instrument_ids.get(bucket.instrument_kind)
        if instrument_id is None:
            continue
        cur.execute(
            """
            INSERT INTO ledger_classifications (
                cost_ledger_id, instrument_id, category, eligible_amount,
                confidence, rationale, model_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                line["id"],
                instrument_id,
                bucket.category,
                bucket.eligible_amount,
                bucket.confidence,
                bucket.rationale + rationale_suffix,
                SONNET,
            ),
        )
        n += 1
    return n


def run_classify(*, max_lines: int | None = None) -> ClassifyResult:
    ctx = load_active_deal_context()
    schemas = load_eligibility_schemas(ctx["deal"]["slug"])
    accepted = load_accepted_positions(ctx["deal"]["slug"])
    system_blocks = _build_system_blocks(schemas, accepted)
    instrument_ids = _resolve_instrument_ids(ctx["deal"]["id"])

    limit = max_lines if max_lines is not None else 1000
    pending = _fetch_pending_lines(ctx["deal"]["id"], limit)

    n_processed = 0
    n_written = 0
    n_non_eligible = 0
    n_missing_backup = 0
    n_low_confidence = 0
    cache_read_tot = 0
    cache_creation_tot = 0

    for start in range(0, len(pending), CLASSIFY_BATCH_SIZE):
        batch = pending[start : start + CLASSIFY_BATCH_SIZE]
        result, cache_read, cache_creation = _classify_batch(
            system_blocks=system_blocks, batch=batch
        )
        cache_read_tot += cache_read
        cache_creation_tot += cache_creation

        result_by_idx = {c.line_index: c for c in result.classifications}
        with cursor() as cur:
            for i, line in enumerate(batch):
                classification = result_by_idx.get(i)
                if classification is None:
                    continue
                n_processed += 1
                if classification.is_non_eligible:
                    n_non_eligible += 1
                if classification.missing_backup:
                    n_missing_backup += 1
                if any(b.confidence < 0.85 for b in classification.bucket_assignments):
                    n_low_confidence += 1
                n_written += _persist_classifications(
                    cur=cur,
                    line=line,
                    classification=classification,
                    instrument_ids=instrument_ids,
                )

    return ClassifyResult(
        deal_slug=ctx["deal"]["slug"],
        n_lines_processed=n_processed,
        n_classifications_written=n_written,
        n_non_eligible=n_non_eligible,
        n_missing_backup=n_missing_backup,
        n_low_confidence=n_low_confidence,
        cache_read_tokens=cache_read_tot,
        cache_creation_tokens=cache_creation_tot,
    )


if __name__ == "__main__":
    out = run_classify()
    print(json.dumps(out.__dict__, indent=2, default=str))
