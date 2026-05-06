"""Weekly miss-audit — the second guardrail on the kill switch.

Every Sunday: gather every flagged date, low-confidence date, and
unparseable contract from the last 7 days, render a Word digest into
the principal-review folder, and insert a `miss_audits` row that the
principal acknowledges line-by-line.

This is non-negotiable for trust: the operator's defined kill condition
is a missed key date. If the dual-extraction guardrail fails silently,
the weekly audit is the second chance to surface the miss.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Pt, RGBColor

from services.common.config import REPO_ROOT
from services.common.db import cursor


@dataclass
class WeekBucket:
    flagged_dates: list[dict[str, Any]]
    low_confidence_dates: list[dict[str, Any]]
    unparseable_contracts: list[dict[str, Any]]
    critical_unacked: list[dict[str, Any]]


def _gather(week_starting: date) -> WeekBucket:
    week_end = week_starting + timedelta(days=7)
    with cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.kind::text, d.label, d.value, d.source_ref,
                   d.extraction_a_value, d.extraction_b_value, d.agreed, d.is_critical,
                   c.title, c.document_uri
            FROM dates d
            JOIN contracts c ON c.id = d.contract_id
            WHERE d.created_at >= %s AND d.created_at < %s
              AND d.agreed = FALSE
            ORDER BY d.is_critical DESC, d.created_at ASC
            """,
            (week_starting, week_end),
        )
        flagged = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT d.id, d.kind::text, d.label, d.value, d.confidence,
                   c.title, c.document_uri
            FROM dates d
            JOIN contracts c ON c.id = d.contract_id
            WHERE d.created_at >= %s AND d.created_at < %s
              AND d.confidence IS NOT NULL AND d.confidence < 0.85
              AND d.agreed = TRUE
            ORDER BY d.confidence ASC
            """,
            (week_starting, week_end),
        )
        low_conf = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT id, title, document_uri, parse_status, parse_error, created_at
            FROM contracts
            WHERE parse_status IN ('needs_human', 'failed')
              AND created_at >= %s AND created_at < %s
            ORDER BY created_at ASC
            """,
            (week_starting, week_end),
        )
        unparseable = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT d.id, d.kind::text, d.label, d.value, d.source_ref,
                   c.title, c.document_uri
            FROM dates d
            JOIN contracts c ON c.id = d.contract_id
            WHERE d.is_critical = TRUE
              AND d.agreed = TRUE
              AND d.human_acked = FALSE
            ORDER BY d.value ASC NULLS LAST
            """,
        )
        critical_unacked = [dict(r) for r in cur.fetchall()]

    return WeekBucket(
        flagged_dates=flagged,
        low_confidence_dates=low_conf,
        unparseable_contracts=unparseable,
        critical_unacked=critical_unacked,
    )


def _add_banner(doc: Document, text: str) -> None:
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.bold = True
    run.font.size = Pt(11)
    run.font.color.rgb = RGBColor(192, 0, 0)


def _ack_line(doc: Document) -> None:
    p = doc.add_paragraph()
    r = p.add_run("Principal ack: [ ] reviewed [ ] resolved   Notes: ____________________")
    r.font.size = Pt(10)


def _render_digest(week_starting: date, bucket: WeekBucket, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"weekly_audit_{week_starting.strftime('%Y%m%d')}.docx"

    doc = Document()
    doc.add_heading(f"Weekly miss-audit — week of {week_starting:%Y-%m-%d}", level=0)
    _add_banner(
        doc,
        "MISSED-DATE KILL SWITCH — review every line. Any flagged or low-confidence "
        "date here is one the dual-extraction guardrail did not canonicalize. The "
        "principal's review is the firm's second-line defense.",
    )

    doc.add_heading("Critical dates flagged this week", level=1)
    if bucket.flagged_dates:
        for r in bucket.flagged_dates:
            critical = " [CRITICAL]" if r["is_critical"] else ""
            doc.add_paragraph(
                f"• {r['kind']} — {r['label']}{critical}\n"
                f"  Pass A: {r['extraction_a_value']}    Pass B: {r['extraction_b_value']}\n"
                f"  Source: {r.get('source_ref') or '(disagreement)'} \n"
                f"  Contract: {r['title']} ({r['document_uri']})"
            )
            _ack_line(doc)
    else:
        doc.add_paragraph("(none)")

    doc.add_heading("Low-confidence dates this week", level=1)
    if bucket.low_confidence_dates:
        for r in bucket.low_confidence_dates:
            doc.add_paragraph(
                f"• {r['kind']} — {r['label']} — {r['value']} "
                f"(confidence {r['confidence']:.2f})\n"
                f"  Contract: {r['title']} ({r['document_uri']})"
            )
            _ack_line(doc)
    else:
        doc.add_paragraph("(none)")

    doc.add_heading("Contracts that failed to parse", level=1)
    if bucket.unparseable_contracts:
        for r in bucket.unparseable_contracts:
            doc.add_paragraph(
                f"• {r['title']} — {r['parse_status']}\n"
                f"  URI: {r['document_uri']}\n"
                f"  Error: {r.get('parse_error') or '(none captured)'}"
            )
            _ack_line(doc)
    else:
        doc.add_paragraph("(none)")

    doc.add_heading("Critical dates awaiting principal ack", level=1)
    if bucket.critical_unacked:
        for r in bucket.critical_unacked:
            doc.add_paragraph(
                f"• {r['kind']} — {r['label']} — {r['value']}\n"
                f"  Source: {r['source_ref']}\n"
                f"  Contract: {r['title']} ({r['document_uri']})"
            )
            _ack_line(doc)
    else:
        doc.add_paragraph("(none)")

    doc.save(out_path)
    return out_path


def run_weekly_audit(week_starting: date | None = None) -> dict[str, Any]:
    if week_starting is None:
        today = datetime.utcnow().date()
        week_starting = today - timedelta(days=today.weekday() + 1)

    bucket = _gather(week_starting)
    out_dir = REPO_ROOT / "templates" / "deliverables" / "weekly_audits"
    digest_path = _render_digest(week_starting, bucket, out_dir)

    flagged_count = len(bucket.flagged_dates)
    low_conf_count = len(bucket.low_confidence_dates)
    unparseable_count = len(bucket.unparseable_contracts)

    with cursor() as cur:
        cur.execute(
            """
            INSERT INTO miss_audits (
                week_starting, flagged_count, low_confidence_count,
                unparseable_count, digest_uri
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (week_starting) DO UPDATE SET
                flagged_count = EXCLUDED.flagged_count,
                low_confidence_count = EXCLUDED.low_confidence_count,
                unparseable_count = EXCLUDED.unparseable_count,
                digest_uri = EXCLUDED.digest_uri
            RETURNING id
            """,
            (
                week_starting,
                flagged_count,
                low_conf_count,
                unparseable_count,
                str(digest_path),
            ),
        )
        audit_id = cur.fetchone()["id"]

    return {
        "audit_id": audit_id,
        "week_starting": str(week_starting),
        "flagged_count": flagged_count,
        "low_confidence_count": low_conf_count,
        "unparseable_count": unparseable_count,
        "critical_unacked_count": len(bucket.critical_unacked),
        "digest": str(digest_path),
    }
