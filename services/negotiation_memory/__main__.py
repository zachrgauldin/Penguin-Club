"""Negotiation memory CLI.

  ingest    — extract negotiated positions from a single executed agreement
  backfill  — recurse a directory and ingest every PDF/docx/txt
  ask       — Sonnet 4.6 synthesis over the firm's negotiation history
  list      — structured SQL filter (no LLM)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_ingest(args: argparse.Namespace) -> int:
    from services.negotiation_memory.ingest import ingest_document

    path = Path(args.path).expanduser().resolve()
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    result = ingest_document(
        file_path=path, deal_slug=args.deal, doc_kind_hint=args.kind_hint
    )
    print(json.dumps(result.__dict__, indent=2, default=str))
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    from services.negotiation_memory.ingest import ingest_document

    root = Path(args.dir).expanduser().resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 2

    suffixes = {".pdf", ".docx", ".txt", ".md"}
    files = sorted(p for p in root.rglob("*") if p.suffix.lower() in suffixes)
    print(f"[backfill] found {len(files)} files under {root}", file=sys.stderr)

    results: list[dict] = []
    for i, p in enumerate(files, 1):
        print(f"[backfill] ({i}/{len(files)}) {p.name}", file=sys.stderr)
        try:
            r = ingest_document(file_path=p, deal_slug=args.deal, doc_kind_hint=args.kind_hint)
            results.append({"file": str(p), "n_positions": r.n_positions, "doc_kind": r.doc_kind})
        except Exception as e:
            results.append({"file": str(p), "error": str(e)})
    print(json.dumps({"backfilled": len(results), "results": results}, indent=2))
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from services.negotiation_memory.query import synthesize

    result = synthesize(
        args.question,
        tag=args.tag,
        section=args.section,
        counterparty_tier=args.tier,
        doc_kind=args.doc_kind,
        outcome=args.outcome,
    )
    print(json.dumps({
        "question": args.question,
        "n_positions_consulted": result.n_positions_consulted,
        "answer": result.answer,
    }, indent=2, default=str))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    from services.negotiation_memory.query import filter_positions

    rows = filter_positions(
        tag=args.tag,
        section=args.section,
        counterparty_tier=args.tier,
        doc_kind=args.doc_kind,
        outcome=args.outcome,
        limit=args.limit,
    )
    print(json.dumps({"n": len(rows), "rows": rows}, indent=2, default=str))
    return 0


VALID_DOC_KINDS = (
    "psa", "loi", "lot_purchase", "takedown",
    "dev_agreement", "reimbursement_agreement", "bond_instrument", "other",
)
VALID_OUTCOMES = ("accepted", "rejected", "hedged", "compromised", "ambiguous")


def main() -> int:
    parser = argparse.ArgumentParser(prog="negotiation_memory")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_in = sub.add_parser("ingest", help="Extract negotiated positions from one document")
    p_in.add_argument("--path", required=True)
    p_in.add_argument("--deal")
    p_in.add_argument("--kind-hint", choices=VALID_DOC_KINDS)
    p_in.set_defaults(func=cmd_ingest)

    p_bf = sub.add_parser("backfill", help="Recurse a directory and ingest every doc")
    p_bf.add_argument("--dir", required=True)
    p_bf.add_argument("--deal")
    p_bf.add_argument("--kind-hint", choices=VALID_DOC_KINDS)
    p_bf.set_defaults(func=cmd_backfill)

    p_ask = sub.add_parser("ask", help="Synthesize an answer from the corpus")
    p_ask.add_argument("question")
    p_ask.add_argument("--tag")
    p_ask.add_argument("--section")
    p_ask.add_argument("--tier")
    p_ask.add_argument("--doc-kind", choices=VALID_DOC_KINDS)
    p_ask.add_argument("--outcome", choices=VALID_OUTCOMES)
    p_ask.set_defaults(func=cmd_ask)

    p_ls = sub.add_parser("list", help="Filtered SQL listing (no LLM)")
    p_ls.add_argument("--tag")
    p_ls.add_argument("--section")
    p_ls.add_argument("--tier")
    p_ls.add_argument("--doc-kind", choices=VALID_DOC_KINDS)
    p_ls.add_argument("--outcome", choices=VALID_OUTCOMES)
    p_ls.add_argument("--limit", type=int, default=80)
    p_ls.set_defaults(func=cmd_list)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
