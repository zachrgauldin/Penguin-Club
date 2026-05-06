"""Builder takedown structuring optimizer CLI.

  propose --deal lavon-pilot --section "Section 3" --tier national_public --lot-count 120
"""
from __future__ import annotations

import argparse
import json


def cmd_propose(args: argparse.Namespace) -> int:
    from services.takedown_optimizer.optimizer import propose

    result = propose(
        deal_slug=args.deal,
        section=args.section,
        target_tier=args.tier,
        target_lot_count=args.lot_count,
        discount_rate=args.discount_rate,
        n_proposals=args.n,
    )

    payload = {
        "deal": result.deal_slug,
        "section": result.section,
        "tier": result.target_tier,
        "lot_count": result.target_lot_count,
        "discount_rate": result.discount_rate,
        "summary": result.structure_set.summary,
        "n_proposals": len(result.structures_with_npv),
        "word_path": result.word_path,
        "cache_read_tokens": result.cache_read_tokens,
        "cache_creation_tokens": result.cache_creation_tokens,
        "proposals": [
            {
                "label": r.structure.label,
                "base_lot_price": r.structure.base_lot_price,
                "escalator_pct": r.structure.escalator_pct,
                "escalator_basis": r.structure.escalator_basis,
                "option_fee": r.structure.option_fee,
                "velocity_per_qtr": r.structure.velocity_per_qtr,
                "total_revenue": r.total_revenue,
                "npv": r.npv,
                "avg_price_per_lot": r.avg_price_per_lot,
                "quarters": r.quarters,
            }
            for r in result.structures_with_npv
        ],
    }
    print(json.dumps(payload, indent=2, default=str))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="takedown_optimizer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("propose", help="Propose alternative takedown structures for a deal section")
    p.add_argument("--deal", required=True)
    p.add_argument("--section", required=True)
    p.add_argument(
        "--tier",
        required=True,
        choices=["luxury", "national_public", "regional_production"],
    )
    p.add_argument("--lot-count", type=int, required=True)
    p.add_argument("--discount-rate", type=float, default=0.12)
    p.add_argument("--n", type=int, default=4, help="Number of structures to propose (default 4)")
    p.set_defaults(func=cmd_propose)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
