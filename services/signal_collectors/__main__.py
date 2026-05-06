"""Lavon-watch entry point.

Wave-1 commands implemented:
  ingest          — fetch a URL or file, normalize via Sonnet 4.6, persist signals
  digest-daily    — render the daily Word digest
  digest-weekly   — Opus 4.7 weekly synthesis + Word digest
  ask             — Q&A over the signals corpus

Wave-1 commands stubbed (require per-source HTML scrapers + scheduling):
  scan          — run all due collectors per pilot config cadence
  scan-source   — invoke a single per-source collector
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


VALID_SOURCES = (
    # Lavon-local
    "lavon_council",
    "lavon_pz",
    "lavon_staff",
    "lavon_elections",
    "collin_county",
    "tceq_docket",
    "ntmwd",
    "wylie_isd",
    "community_isd",
    "txdot",
    "nctcog",
    # Texas-statewide lege/agency/industry
    "tx_lege",
    "tceq_rulemaking",
    "tx_ag",
    "tx_comptroller",
    "tab",
    "agc_tx",
    "uli",
    "naiop_reca",
    "other",
)


def cmd_ingest(args: argparse.Namespace) -> int:
    from services.signal_collectors.ingest import ingest_path, ingest_url

    if (args.url is None) == (args.path is None):
        print("Pass exactly one of --url or --path.", file=sys.stderr)
        return 2

    if args.url:
        result = ingest_url(url=args.url, source=args.source)
    else:
        result = ingest_path(path=Path(args.path).expanduser().resolve(), source=args.source)

    print(json.dumps(result.to_dict(), indent=2, default=str))
    return 0


def cmd_digest_daily(args: argparse.Namespace) -> int:
    from services.signal_collectors.digest import render_daily

    if args.day:
        day = date.fromisoformat(args.day)
        period_start = datetime.combine(day, datetime.min.time())
    else:
        period_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    period_end = period_start + timedelta(days=1)

    summary = render_daily(period_start=period_start, period_end=period_end)
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_digest_weekly(args: argparse.Namespace) -> int:
    from services.signal_collectors.digest import render_weekly

    if args.week_starting:
        week_starting = date.fromisoformat(args.week_starting)
    else:
        today = datetime.utcnow().date()
        week_starting = today - timedelta(days=today.weekday() + 1)

    summary = render_weekly(week_starting=week_starting)
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from services.signal_collectors.ask import ask

    summary = ask(args.question)
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    print(
        "[scan] TODO: per-source HTML scrapers + cadence scheduler. "
        "Use `ingest --url ...` against a confirmed URL until per-source scrapers ship.",
        file=sys.stderr,
    )
    return 1


def cmd_scan_source(args: argparse.Namespace) -> int:
    print(
        f"[scan-source] source={args.source} TODO: per-source scraper not implemented.",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="signal_collectors")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ing = sub.add_parser("ingest", help="Fetch a URL or local file, normalize, persist signals")
    p_ing.add_argument("--url")
    p_ing.add_argument("--path")
    p_ing.add_argument("--source", required=True, choices=VALID_SOURCES)
    p_ing.set_defaults(func=cmd_ingest)

    p_dd = sub.add_parser("digest-daily", help="Render the daily Lavon digest")
    p_dd.add_argument("--day", help="ISO date (default: today)")
    p_dd.set_defaults(func=cmd_digest_daily)

    p_dw = sub.add_parser("digest-weekly", help="Opus 4.7 weekly synthesis")
    p_dw.add_argument("--week-starting", help="ISO date for the Sunday-aligned week start")
    p_dw.set_defaults(func=cmd_digest_weekly)

    p_ask = sub.add_parser("ask", help="Q&A over the signals corpus")
    p_ask.add_argument("question")
    p_ask.set_defaults(func=cmd_ask)

    sub.add_parser("scan").set_defaults(func=cmd_scan)

    p_ss = sub.add_parser("scan-source")
    p_ss.add_argument("--source", required=True, choices=VALID_SOURCES)
    p_ss.set_defaults(func=cmd_scan_source)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
