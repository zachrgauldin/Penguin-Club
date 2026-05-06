"""Reimbursement service entry point.

Wave-1 commands implemented:
  seed         — load pilot config + eligibility schemas into Postgres
  structuring  — generate frontier proposals (Opus 4.7), persist to pf_positions, emit Word doc

Wave-1 commands stubbed:
  classify     — Sonnet 4.6 cost-ledger classification
  package      — packet assembly
  registry     — per-deal one-pager
"""
from __future__ import annotations

import argparse
import json
import sys


def cmd_seed(args: argparse.Namespace) -> int:
    from services.reimbursement_api.db_seed import seed_pilot

    summary = seed_pilot()
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_structuring(args: argparse.Namespace) -> int:
    from services.reimbursement_api.structuring import run_structuring

    run = run_structuring()
    print(
        json.dumps(
            {
                "deal": run.proposal_set.deal_slug,
                "n_proposals": len(run.proposal_set.proposals),
                "summary": run.proposal_set.summary,
                "persisted_position_ids": run.persisted_position_ids,
                "deliverable": str(run.deliverable_path),
                "cache_read_tokens": run.cache_read_tokens,
                "cache_creation_tokens": run.cache_creation_tokens,
            },
            indent=2,
        )
    )
    return 0


def cmd_import_ledger(args: argparse.Namespace) -> int:
    from pathlib import Path

    from services.reimbursement_api.ledger_loader import import_ledger

    summary = import_ledger(
        path=Path(args.path).expanduser().resolve(),
        deal_slug=args.deal,
    )
    print(json.dumps(summary.__dict__, indent=2, default=str))
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    from services.reimbursement_api.classify import run_classify

    summary = run_classify(max_lines=args.max_lines)
    print(json.dumps(summary.__dict__, indent=2, default=str))
    return 0


def cmd_package(args: argparse.Namespace) -> int:
    from services.reimbursement_api.packet import assemble_packet

    summary = assemble_packet(
        deal_slug=args.deal,
        instrument_kind=args.instrument,
        packet_number=args.packet_number,
    )
    print(json.dumps(summary.__dict__, indent=2, default=str))
    return 0


def cmd_registry(args: argparse.Namespace) -> int:
    from services.reimbursement_api.registry import render_registry

    snap = render_registry(deal_slug=args.deal)
    print(json.dumps(snap.__dict__, indent=2, default=str))
    return 0


def cmd_signoff(args: argparse.Namespace) -> int:
    """Record an advisor view on a structuring proposal."""
    from services.common.db import cursor

    column_map = {
        "bond_counsel": ("bond_counsel_view", "bond_counsel_notes"),
        "municipal_advisor": ("municipal_advisor_view", "municipal_advisor_notes"),
        "pid_admin": ("pid_admin_view", "pid_admin_notes"),
    }
    view_col, notes_col = column_map[args.advisor]

    sql = f"""
        UPDATE pf_positions
        SET {view_col} = %s,
            {notes_col} = %s,
            updated_at = NOW()
        WHERE id = %s
        RETURNING id, title, family, {view_col}, {notes_col}
    """
    with cursor() as cur:
        cur.execute(sql, (args.view, args.notes, args.position_id))
        row = cur.fetchone()
    if row is None:
        print(f"No pf_positions row with id={args.position_id}", file=sys.stderr)
        return 2
    print(json.dumps(dict(row), indent=2, default=str))
    return 0


def cmd_review_classification(args: argparse.Namespace) -> int:
    """Mark a ledger_classifications row reviewed/adjusted/rejected by an advisor."""
    from services.common.db import cursor

    with cursor() as cur:
        cur.execute(
            """
            UPDATE ledger_classifications
            SET advisor_review = %s,
                advisor_notes = %s
            WHERE id = %s
            RETURNING id, advisor_review, eligible_amount, category
            """,
            (args.review, args.notes, args.classification_id),
        )
        row = cur.fetchone()
    if row is None:
        print(f"No ledger_classifications row with id={args.classification_id}", file=sys.stderr)
        return 2
    print(json.dumps(dict(row), indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="reimbursement_api")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed", help="Upsert deal/instruments/eligibility_rules from pilot config").set_defaults(func=cmd_seed)
    sub.add_parser("structuring", help="Generate frontier structuring proposals").set_defaults(func=cmd_structuring)

    p_il = sub.add_parser("import-ledger", help="Import a CSV/XLSX cost ledger into Postgres")
    p_il.add_argument("--path", required=True)
    p_il.add_argument("--deal", required=True)
    p_il.set_defaults(func=cmd_import_ledger)

    p_cls = sub.add_parser("classify", help="Capture mode: classify pending cost-ledger lines")
    p_cls.add_argument("--max-lines", type=int, default=None,
                       help="Cap on lines processed in this run (default: all pending)")
    p_cls.set_defaults(func=cmd_classify)

    p_pkg = sub.add_parser("package", help="Assemble a draft reimbursement packet")
    p_pkg.add_argument("--deal", required=True)
    p_pkg.add_argument("--instrument", required=True, choices=["pid", "mud", "tirz", "380", "381"])
    p_pkg.add_argument("--packet-number", default=None,
                       help="Identifier for this packet (default: timestamp)")
    p_pkg.set_defaults(func=cmd_package)

    p_reg = sub.add_parser("registry", help="Render the per-deal reimbursement registry one-pager")
    p_reg.add_argument("--deal", required=True)
    p_reg.set_defaults(func=cmd_registry)

    p_so = sub.add_parser("signoff", help="Record an advisor view on a structuring proposal")
    p_so.add_argument("--position-id", required=True)
    p_so.add_argument(
        "--advisor", required=True,
        choices=["bond_counsel", "municipal_advisor", "pid_admin"],
    )
    p_so.add_argument(
        "--view", required=True,
        choices=["pending", "accepted", "hedged", "declined"],
    )
    p_so.add_argument("--notes", default=None)
    p_so.set_defaults(func=cmd_signoff)

    p_rc = sub.add_parser(
        "review-classification",
        help="Mark a ledger_classifications row approved/adjusted/rejected",
    )
    p_rc.add_argument("--classification-id", required=True)
    p_rc.add_argument(
        "--review", required=True,
        choices=["pending", "approved", "adjusted", "rejected"],
    )
    p_rc.add_argument("--notes", default=None)
    p_rc.set_defaults(func=cmd_review_classification)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
