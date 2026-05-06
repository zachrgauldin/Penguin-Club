"""Signal collector orchestrator.

One collector per Lavon source (see configs/pilot_lavon.yml under signals.sources):
  lavon_council, lavon_pz, lavon_staff, lavon_elections,
  collin_county, tceq_docket, ntmwd, wylie_isd, community_isd, txdot, nctcog

Each collector:
  1. Hits its configured URLs.
  2. Parses new items (HTML/PDF agendas, dockets, board minutes).
  3. Dedupes via signals.dedupe_key.
  4. Sonnet 4.6 scores impact_score 0..5 against the active pilot config + instruments.
  5. Writes signals + signal_pilot_links rows.
  6. Logs a collector_runs row regardless of outcome.

Sub-commands:
  scan         — run all collectors that are due
  scan-source  — run a single named collector
  digest-daily — render the daily Word digest
  digest-weekly — render the weekly synthesis (Opus 4.7)
"""
from __future__ import annotations

import argparse


def cmd_scan(args: argparse.Namespace) -> int:
    print("[scan] TODO: dispatch all due collectors per pilot config cadence.")
    return 0


def cmd_scan_source(args: argparse.Namespace) -> int:
    print(f"[scan-source] source={args.source} — TODO: invoke single collector.")
    return 0


def cmd_digest_daily(args: argparse.Namespace) -> int:
    print("[digest-daily] TODO: render templates/digest/lavon_daily.docx and insert lavon_digests row.")
    return 0


def cmd_digest_weekly(args: argparse.Namespace) -> int:
    print("[digest-weekly] TODO: Opus 4.7 synthesis into templates/digest/lavon.docx.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="signal_collectors")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scan").set_defaults(func=cmd_scan)

    p_src = sub.add_parser("scan-source")
    p_src.add_argument("--source", required=True)
    p_src.set_defaults(func=cmd_scan_source)

    sub.add_parser("digest-daily").set_defaults(func=cmd_digest_daily)
    sub.add_parser("digest-weekly").set_defaults(func=cmd_digest_weekly)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
