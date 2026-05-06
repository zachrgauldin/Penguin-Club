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


def cmd_classify(args: argparse.Namespace) -> int:
    print("[classify] TODO: Sonnet 4.6 classification with cached schemas. Not yet implemented.", file=sys.stderr)
    return 1


def cmd_package(args: argparse.Namespace) -> int:
    print(f"[package] instrument={args.instrument} TODO: packet generation. Not yet implemented.", file=sys.stderr)
    return 1


def cmd_registry(args: argparse.Namespace) -> int:
    print("[registry] TODO: per-instrument capacity + position summary. Not yet implemented.", file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="reimbursement_api")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed", help="Upsert deal/instruments/eligibility_rules from pilot config").set_defaults(func=cmd_seed)
    sub.add_parser("structuring", help="Generate frontier structuring proposals").set_defaults(func=cmd_structuring)
    sub.add_parser("classify").set_defaults(func=cmd_classify)
    p_pkg = sub.add_parser("package")
    p_pkg.add_argument("--instrument", required=True)
    p_pkg.set_defaults(func=cmd_package)
    sub.add_parser("registry").set_defaults(func=cmd_registry)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
