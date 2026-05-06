"""Reimbursement service entry point.

Routes:
- structuring: surface frontier proposals across the four families, persist to pf_positions
- classify: walk new cost_ledger rows, write per-instrument ledger_classifications
- package: assemble the next reimbursement packet for an instrument
- registry: per-deal one-pager

Each route is a thin wrapper that:
1. Loads pilot config + active eligibility schemas (cached prompt prefix)
2. Routes the right model (Opus for structuring, Sonnet for classify, Haiku for triage)
3. Writes structured output back to Postgres via services.common.db
"""
from __future__ import annotations

import argparse

from services.common.config import pilot_config


def cmd_structuring(args: argparse.Namespace) -> int:
    cfg = pilot_config()
    print(f"[structuring] deal={cfg['deal']['slug']} — TODO: implement Opus 4.7 proposal generation.")
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    cfg = pilot_config()
    print(f"[classify] deal={cfg['deal']['slug']} — TODO: implement Sonnet 4.6 classification with cached schemas.")
    return 0


def cmd_package(args: argparse.Namespace) -> int:
    print(f"[package] instrument={args.instrument} — TODO: implement packet generation.")
    return 0


def cmd_registry(args: argparse.Namespace) -> int:
    cfg = pilot_config()
    print(f"[registry] deal={cfg['deal']['slug']} — TODO: render per-instrument capacity + position summary.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="reimbursement_api")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("structuring").set_defaults(func=cmd_structuring)
    sub.add_parser("classify").set_defaults(func=cmd_classify)

    p_pkg = sub.add_parser("package")
    p_pkg.add_argument("--instrument", required=True)
    p_pkg.set_defaults(func=cmd_package)

    sub.add_parser("registry").set_defaults(func=cmd_registry)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
