"""SharePoint watcher / contracts agent entry point.

Wave-1 commands implemented:
  extract        — dual-extract a single contract file (PDF / docx / txt)
  backfill       — extract every contract under a directory
  weekly-audit   — Sunday miss-audit digest (kill-switch second line)

Wave-1 commands stubbed (require Microsoft Graph + Outlook integration):
  watch              — long-running poller against the contracts drive
  takedown-forecast  — per-builder cash flow projection
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path


def cmd_extract(args: argparse.Namespace) -> int:
    from services.sharepoint_watcher.extraction import extract_contract
    from services.sharepoint_watcher.persistence import persist_extraction

    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    extraction = extract_contract(path, kind_hint=args.kind_hint)
    persisted = persist_extraction(
        extraction=extraction,
        document_uri=str(path),
        deal_slug=args.deal,
    )

    summary = {
        "file": str(path),
        "contract_id": persisted.contract_id,
        "deal_id": persisted.deal_id,
        "parse_status": persisted.parse_status,
        "n_dates": persisted.n_dates,
        "n_obligations": persisted.n_obligations,
        "has_takedown": persisted.has_takedown,
        "pass_a_kind": extraction.pass_a.contract_kind,
        "pass_b_kind": extraction.pass_b.contract_kind,
        "agreement_rate": (
            sum(1 for r in extraction.date_agreements if r.agreed)
            / max(len(extraction.date_agreements), 1)
        ),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if persisted.parse_status == "parsed" else 3


def cmd_backfill(args: argparse.Namespace) -> int:
    from services.sharepoint_watcher.extraction import extract_contract
    from services.sharepoint_watcher.persistence import persist_extraction

    root = Path(args.dir).expanduser().resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 2

    suffixes = {".pdf", ".docx", ".txt", ".md"}
    files = sorted(p for p in root.rglob("*") if p.suffix.lower() in suffixes)
    print(f"[backfill] found {len(files)} contract files under {root}", file=sys.stderr)

    results: list[dict] = []
    for i, p in enumerate(files, 1):
        print(f"[backfill] ({i}/{len(files)}) {p.name}", file=sys.stderr)
        try:
            extraction = extract_contract(p, kind_hint=args.kind_hint)
            persisted = persist_extraction(
                extraction=extraction, document_uri=str(p), deal_slug=args.deal
            )
            results.append(
                {
                    "file": str(p),
                    "contract_id": persisted.contract_id,
                    "parse_status": persisted.parse_status,
                    "n_dates": persisted.n_dates,
                    "needs_human": persisted.parse_status != "parsed",
                }
            )
        except Exception as e:
            results.append({"file": str(p), "error": str(e)})

    print(json.dumps({"backfilled": len(results), "results": results}, indent=2, default=str))
    return 0


def cmd_weekly_audit(args: argparse.Namespace) -> int:
    from services.sharepoint_watcher.weekly_audit import run_weekly_audit

    week_starting = date.fromisoformat(args.week_starting) if args.week_starting else None
    summary = run_weekly_audit(week_starting=week_starting)
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    from services.sharepoint_watcher.watcher import watch_once

    result = watch_once(force=args.force, kind_hint=args.kind_hint)
    print(json.dumps(result.__dict__, indent=2, default=str))
    return 0 if result.files_failed == 0 else 3


def cmd_takedown_forecast(args: argparse.Namespace) -> int:
    from services.sharepoint_watcher.takedown_forecast import render_takedown_forecast

    result = render_takedown_forecast(
        deal_slug=args.deal,
        horizon_quarters=args.horizon_quarters,
    )
    payload = {
        "deal_slug": result.deal_slug,
        "horizon_quarters": result.horizon_quarters,
        "n_schedules": len(result.schedules),
        "by_tier_totals": result.by_tier_totals,
        "word_path": result.word_path,
        "totals": {
            "lots": sum(s.total_lots for s in result.schedules),
            "revenue": sum(s.total_revenue for s in result.schedules),
        },
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


def cmd_ack_date(args: argparse.Namespace) -> int:
    """Mark a critical date acknowledged by the principal."""
    from services.common.db import cursor

    with cursor() as cur:
        cur.execute(
            """
            UPDATE dates
            SET human_acked = TRUE,
                human_acked_at = NOW(),
                human_acked_by = %s,
                notes = COALESCE(notes, '') || CASE WHEN %s IS NULL THEN '' ELSE E'\n' || %s END,
                updated_at = NOW()
            WHERE id = %s
            RETURNING id, kind::text AS kind, value, is_critical, agreed, human_acked
            """,
            (args.by, args.notes, args.notes, args.date_id),
        )
        row = cur.fetchone()
    if row is None:
        print(f"No dates row with id={args.date_id}", file=sys.stderr)
        return 2
    print(json.dumps(dict(row), indent=2, default=str))
    return 0


def cmd_ack_audit(args: argparse.Namespace) -> int:
    """Mark a weekly miss-audit acknowledged by the principal."""
    from datetime import date

    from services.common.db import cursor

    week = date.fromisoformat(args.week_starting)
    with cursor() as cur:
        cur.execute(
            """
            UPDATE miss_audits
            SET principal_acked = TRUE,
                principal_acked_at = NOW()
            WHERE week_starting = %s
            RETURNING id, week_starting, flagged_count, low_confidence_count,
                      unparseable_count, principal_acked
            """,
            (week,),
        )
        row = cur.fetchone()
    if row is None:
        print(f"No miss_audits row for week_starting={args.week_starting}", file=sys.stderr)
        return 2
    print(json.dumps(dict(row), indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="sharepoint_watcher")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ex = sub.add_parser("extract", help="Dual-extract a single contract file")
    p_ex.add_argument("--path", required=True)
    p_ex.add_argument("--deal", help="Deal slug (e.g. lavon-pilot)")
    p_ex.add_argument(
        "--kind-hint",
        choices=[
            "psa",
            "loi",
            "lot_purchase",
            "takedown",
            "dev_agreement",
            "reimbursement_agreement",
            "other",
        ],
        help="Optional contract-kind hint to load the right firm form library",
    )
    p_ex.set_defaults(func=cmd_extract)

    p_bf = sub.add_parser("backfill", help="Extract every contract under a directory")
    p_bf.add_argument("--dir", required=True)
    p_bf.add_argument("--deal")
    p_bf.add_argument("--kind-hint")
    p_bf.set_defaults(func=cmd_backfill)

    p_wa = sub.add_parser("weekly-audit", help="Generate the Sunday miss-audit digest")
    p_wa.add_argument(
        "--week-starting",
        help="ISO date for the Sunday-aligned week start (default: most recent Sunday)",
    )
    p_wa.set_defaults(func=cmd_weekly_audit)

    p_w = sub.add_parser(
        "watch",
        help="Walk the SharePoint contracts folder and ingest new files",
    )
    p_w.add_argument("--force", action="store_true",
                     help="Re-extract files already in the contracts table")
    p_w.add_argument(
        "--kind-hint",
        choices=[
            "psa", "loi", "lot_purchase", "takedown",
            "dev_agreement", "reimbursement_agreement", "other",
        ],
        help="Optional contract-kind hint applied to every file in this run",
    )
    p_w.set_defaults(func=cmd_watch)

    p_tf = sub.add_parser("takedown-forecast", help="Per-builder cash-flow projection")
    p_tf.add_argument("--deal", required=True)
    p_tf.add_argument("--horizon-quarters", type=int, default=16)
    p_tf.set_defaults(func=cmd_takedown_forecast)

    p_ad = sub.add_parser("ack-date", help="Mark a critical date acknowledged by the principal")
    p_ad.add_argument("--date-id", required=True)
    p_ad.add_argument("--by", default=None, help="Email or initials of the acker")
    p_ad.add_argument("--notes", default=None)
    p_ad.set_defaults(func=cmd_ack_date)

    p_aa = sub.add_parser("ack-audit", help="Mark a weekly miss-audit acknowledged by the principal")
    p_aa.add_argument("--week-starting", required=True, help="ISO date for the audit week start")
    p_aa.set_defaults(func=cmd_ack_audit)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
