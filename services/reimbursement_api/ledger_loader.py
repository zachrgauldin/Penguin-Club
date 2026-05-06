"""Cost-ledger import: CSV / XLSX -> `cost_ledger`.

Idempotent: each row hashes to a `raw_row_hash` based on its content +
deal slug. Re-importing the same file is a no-op. Re-importing with one
row changed inserts the changed row as a new ledger entry rather than
mutating the prior row, so prior classifications stay intact.

Expected columns (case-insensitive, extras ignored):
  posted_on        — ISO date or any pandas-parseable date string
  vendor           — string
  invoice_number   — string (may be empty)
  description      — string (required)
  amount           — number, USD
  gl_account       — string (may be empty)
  backup_uri       — URI to invoice PDF / scan (may be empty)
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from services.common.db import cursor


REQUIRED_COLS = {"posted_on", "description", "amount"}


def _normalize_header(s: str) -> str:
    return s.strip().lower().replace(" ", "_")


def _parse_amount(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    s = str(raw).strip().replace(",", "").replace("$", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _parse_date(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    s = str(raw).strip()
    return s


def _hash_row(deal_slug: str, row: dict[str, Any]) -> str:
    payload = (
        f"{deal_slug}|"
        f"{row.get('posted_on') or ''}|"
        f"{row.get('vendor') or ''}|"
        f"{row.get('invoice_number') or ''}|"
        f"{row.get('description') or ''}|"
        f"{row.get('amount') or ''}|"
        f"{row.get('gl_account') or ''}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iter_csv(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return
        norm_field_map = {fn: _normalize_header(fn) for fn in reader.fieldnames}
        for row in reader:
            yield {norm_field_map[k]: v for k, v in row.items() if k in norm_field_map}


def _iter_xlsx(path: Path) -> Iterable[dict[str, Any]]:
    from openpyxl import load_workbook  # lazy import

    wb = load_workbook(filename=str(path), read_only=True, data_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    headers_raw = next(rows, None)
    if not headers_raw:
        return
    headers = [_normalize_header(h or "") for h in headers_raw]
    for row in rows:
        if all(c is None or c == "" for c in row):
            continue
        yield {headers[i]: row[i] for i in range(min(len(headers), len(row)))}


@dataclass
class LedgerImport:
    path: str
    deal_id: str
    rows_seen: int
    rows_inserted: int
    rows_skipped_dupe: int
    rows_skipped_invalid: int


def import_ledger(*, path: Path, deal_slug: str) -> LedgerImport:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        rows_iter = _iter_csv(path)
    elif suffix in {".xlsx", ".xlsm"}:
        rows_iter = _iter_xlsx(path)
    else:
        raise ValueError(f"Unsupported ledger format {suffix!r}; use CSV or XLSX.")

    seen = inserted = dupe = invalid = 0
    deal_id: str | None = None

    with cursor() as cur:
        cur.execute("SELECT id FROM deals WHERE slug = %s", (deal_slug,))
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(
                f"Deal {deal_slug!r} not found. "
                "Run `python -m services.reimbursement_api seed` first."
            )
        deal_id = row["id"]

        for raw in rows_iter:
            seen += 1
            posted_on = _parse_date(raw.get("posted_on"))
            description = (raw.get("description") or "").strip()
            amount = _parse_amount(raw.get("amount"))

            if not posted_on or not description or amount is None:
                invalid += 1
                continue

            row_hash = _hash_row(deal_slug, {
                "posted_on": posted_on,
                "vendor": raw.get("vendor") or "",
                "invoice_number": raw.get("invoice_number") or "",
                "description": description,
                "amount": str(amount),
                "gl_account": raw.get("gl_account") or "",
            })

            cur.execute(
                """
                INSERT INTO cost_ledger (
                    deal_id, posted_on, vendor, invoice_number,
                    description, amount, gl_account, backup_uri, raw_row_hash
                )
                VALUES (%s, %s::date, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (deal_id, raw_row_hash) DO NOTHING
                """,
                (
                    deal_id,
                    posted_on,
                    raw.get("vendor"),
                    raw.get("invoice_number"),
                    description,
                    amount,
                    raw.get("gl_account"),
                    raw.get("backup_uri"),
                    row_hash,
                ),
            )
            if cur.rowcount == 0:
                dupe += 1
            else:
                inserted += 1

    return LedgerImport(
        path=str(path),
        deal_id=deal_id,
        rows_seen=seen,
        rows_inserted=inserted,
        rows_skipped_dupe=dupe,
        rows_skipped_invalid=invalid,
    )
