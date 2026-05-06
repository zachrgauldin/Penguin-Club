"""Persist a dual-extraction result to Postgres.

Writes:
  - one row to `contracts`
  - one row per DateAgreement to `dates`
  - one row per ObligationAgreement to `obligations`
  - 0 or 1 row to `takedown_schedules` (when present in pass A)

Idempotency: if a contract with the same `document_uri` already exists for
the deal, its existing rows are left in place and a new contract row with a
suffix is inserted. This is intentional — never silently mutate prior
extractions, because they may already be acknowledged by the principal.
"""
from __future__ import annotations

from dataclasses import dataclass

from services.common.db import cursor
from services.sharepoint_watcher.extraction import (
    DateAgreement,
    ExtractionResult,
    ObligationAgreement,
)


@dataclass
class PersistedExtraction:
    contract_id: str
    deal_id: str | None
    n_dates: int
    n_obligations: int
    has_takedown: bool
    parse_status: str


def _resolve_deal_id(deal_slug: str | None) -> str | None:
    if not deal_slug:
        return None
    with cursor() as cur:
        cur.execute("SELECT id FROM deals WHERE slug = %s", (deal_slug,))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"Deal {deal_slug!r} not found in DB. Run "
            f"`python -m services.reimbursement_api seed` first."
        )
    return row["id"]


def _insert_contract(
    cur,
    *,
    deal_id: str | None,
    document_uri: str,
    sharepoint_item_id: str | None,
    extraction: ExtractionResult,
) -> str:
    pa = extraction.pass_a
    cur.execute(
        """
        INSERT INTO contracts (
            deal_id, kind, counterparty, counterparty_tier, title,
            document_uri, sharepoint_item_id, effective_date,
            parsed_at, parse_status
        )
        VALUES (
            %s, %s::contract_kind, %s, %s, %s,
            %s, %s, %s,
            NOW(), %s
        )
        RETURNING id
        """,
        (
            deal_id,
            pa.contract_kind,
            pa.counterparty,
            pa.counterparty_tier,
            pa.title,
            document_uri,
            sharepoint_item_id,
            pa.effective_date,
            extraction.parse_status,
        ),
    )
    return cur.fetchone()["id"]


def _insert_dates(cur, contract_id: str, rows: list[DateAgreement]) -> int:
    n = 0
    for r in rows:
        cur.execute(
            """
            INSERT INTO dates (
                contract_id, kind, label,
                extraction_a_value, extraction_a_source, extraction_a_model,
                extraction_b_value, extraction_b_source, extraction_b_model,
                agreed, value, source_ref,
                is_critical, confidence
            )
            VALUES (
                %s, %s::date_kind, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s
            )
            """,
            (
                contract_id, r.kind, r.label,
                r.extraction_a_value, r.extraction_a_source, r.extraction_a_model,
                r.extraction_b_value, r.extraction_b_source, r.extraction_b_model,
                r.agreed, r.value, r.source_ref,
                r.is_critical, r.confidence,
            ),
        )
        n += 1
    return n


def _insert_obligations(
    cur, contract_id: str, rows: list[ObligationAgreement]
) -> int:
    n = 0
    for r in rows:
        cur.execute(
            """
            INSERT INTO obligations (
                contract_id, kind, label, amount, unit, formula, source_ref, confidence
            )
            VALUES (%s, %s::obligation_kind, %s, %s, %s, %s, %s, %s)
            """,
            (
                contract_id, r.kind, r.label, r.amount, r.unit, r.formula,
                r.source_ref, r.confidence,
            ),
        )
        n += 1
    return n


def _insert_takedown(
    cur, contract_id: str, deal_id: str | None, extraction: ExtractionResult
) -> bool:
    ts = extraction.pass_a.takedown_schedule
    if ts is None:
        return False
    cur.execute(
        """
        INSERT INTO takedown_schedules (
            contract_id, deal_id, builder, builder_tier, section,
            lot_count, base_lot_price, escalator_pct, escalator_basis,
            option_fee, cadence,
            first_takedown_on, last_takedown_on, velocity_per_qtr,
            default_triggers
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s,
            %s
        )
        """,
        (
            contract_id, deal_id, ts.builder, ts.builder_tier, ts.section,
            ts.lot_count, ts.base_lot_price, ts.escalator_pct, ts.escalator_basis,
            ts.option_fee, ts.cadence,
            ts.first_takedown_on, ts.last_takedown_on, ts.velocity_per_qtr,
            ts.default_triggers,
        ),
    )
    return True


def persist_extraction(
    *,
    extraction: ExtractionResult,
    document_uri: str,
    deal_slug: str | None = None,
    sharepoint_item_id: str | None = None,
) -> PersistedExtraction:
    deal_id = _resolve_deal_id(deal_slug)
    with cursor() as cur:
        contract_id = _insert_contract(
            cur,
            deal_id=deal_id,
            document_uri=document_uri,
            sharepoint_item_id=sharepoint_item_id,
            extraction=extraction,
        )
        n_dates = _insert_dates(cur, contract_id, extraction.date_agreements)
        n_obligations = _insert_obligations(cur, contract_id, extraction.obligation_rows)
        has_takedown = _insert_takedown(cur, contract_id, deal_id, extraction)

    return PersistedExtraction(
        contract_id=contract_id,
        deal_id=deal_id,
        n_dates=n_dates,
        n_obligations=n_obligations,
        has_takedown=has_takedown,
        parse_status=extraction.parse_status,
    )
