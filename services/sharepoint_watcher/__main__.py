"""SharePoint watcher entry point.

Watches /Deals/<Deal>/Contracts/ via Microsoft Graph delta queries.
On each new/updated file:
  1. Insert/upsert into contracts.
  2. Run dual-extraction pipeline (Sonnet 4.6 pass A + Opus 4.7 pass B verify)
     producing rows in dates and obligations.
  3. Set agreed = TRUE only when extraction_a_value AND extraction_a_source
     match extraction_b_value AND extraction_b_source.
  4. Emit Outlook calendar events for agreed + acked dates.

Sub-commands:
  watch         — long-running poller against the contracts drive
  weekly-audit  — Sunday miss-audit digest job
  backfill      — reprocess the last N months of contracts
"""
from __future__ import annotations

import argparse


def cmd_watch(args: argparse.Namespace) -> int:
    print("[watch] TODO: implement Graph delta poller + dual-extraction pipeline.")
    return 0


def cmd_weekly_audit(args: argparse.Namespace) -> int:
    print("[weekly-audit] TODO: build Sunday digest from dates + contracts; insert miss_audits row.")
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    print(f"[backfill] months={args.months} — TODO: reprocess executed contracts.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="sharepoint_watcher")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("watch").set_defaults(func=cmd_watch)
    sub.add_parser("weekly-audit").set_defaults(func=cmd_weekly_audit)

    p_bf = sub.add_parser("backfill")
    p_bf.add_argument("--months", type=int, default=12)
    p_bf.set_defaults(func=cmd_backfill)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
