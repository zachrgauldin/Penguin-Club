"""Loaders for the firm-specific data Agent 2 needs in its prompt prefix.

Eligibility schemas come from version-controlled YAML; the accepted-position
library comes from Postgres `pf_positions` rows where all three advisors
(bond counsel + municipal advisor + PID administrator) marked `accepted`.

Both go into the cached prompt prefix so subsequent Structuring runs hit
the cache instead of re-paying for the same context.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from services.common.config import REPO_ROOT, pilot_config


@dataclass(frozen=True)
class InstrumentSchema:
    kind: str
    name: str
    statute_ref: str
    raw_yaml: str


def load_eligibility_schemas(deal_slug: str | None = None) -> list[InstrumentSchema]:
    """Load every per-instrument eligibility schema for the active pilot.

    Returns one InstrumentSchema per declared instrument in the pilot config.
    `raw_yaml` preserves the original document so the LLM sees the operator's
    YAML verbatim — comments, ordering, and notes included.
    """
    cfg = pilot_config()
    if deal_slug and cfg["deal"]["slug"] != deal_slug:
        raise ValueError(
            f"Pilot config is bound to deal={cfg['deal']['slug']!r}, not {deal_slug!r}"
        )

    schemas: list[InstrumentSchema] = []
    for inst in cfg["instruments"]:
        path = Path(inst["eligibility_schema"])
        if not path.is_absolute():
            path = REPO_ROOT / path
        raw = path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(raw)
        schemas.append(
            InstrumentSchema(
                kind=parsed["instrument"]["kind"],
                name=parsed["instrument"]["name"],
                statute_ref=parsed["instrument"].get("statute_ref", ""),
                raw_yaml=raw,
            )
        )
    return schemas


@dataclass(frozen=True)
class AcceptedPosition:
    title: str
    family: str
    proposal: str
    estimated_dollars: float | None
    incorporated_into: str | None


def load_accepted_positions(deal_slug: str) -> list[AcceptedPosition]:
    """Load the firm's accepted-position library for a deal.

    A position is 'accepted' only when bond counsel, municipal advisor, and
    PID administrator all marked `accepted`. Anything less is still a draft
    and does NOT belong in the cached prefix — it gets reviewed not relied on.

    Returns [] if no prior positions exist (typical at pilot inception).
    """
    from services.common.db import cursor

    sql = """
        SELECT p.title, p.family, p.proposal, p.estimated_dollars, p.incorporated_into
        FROM pf_positions p
        JOIN deals d ON d.id = p.deal_id
        WHERE d.slug = %s
          AND p.bond_counsel_view = 'accepted'
          AND p.municipal_advisor_view = 'accepted'
          AND p.pid_admin_view = 'accepted'
        ORDER BY p.created_at ASC
    """
    with cursor() as cur:
        cur.execute(sql, (deal_slug,))
        rows = cur.fetchall()

    return [
        AcceptedPosition(
            title=r["title"],
            family=r["family"],
            proposal=r["proposal"],
            estimated_dollars=(float(r["estimated_dollars"]) if r["estimated_dollars"] is not None else None),
            incorporated_into=r["incorporated_into"],
        )
        for r in rows
    ]


def load_active_deal_context() -> dict[str, Any]:
    """Active-deal context the user-message prompt needs.

    Returns the deal row + per-instrument capacity remaining, joined to the
    pilot config so the LLM can see both the canonical DB state and the
    operator's bindings (advisors, sources, output paths).
    """
    from services.common.db import cursor

    cfg = pilot_config()
    slug = cfg["deal"]["slug"]

    deal_sql = "SELECT id, slug, name, jurisdiction, county, state, status, stage_notes FROM deals WHERE slug = %s"
    inst_sql = """
        SELECT kind::text, name, status, authorized_amount, issued_amount, capacity_remaining, notes
        FROM instruments
        WHERE deal_id = %s
        ORDER BY kind::text
    """
    with cursor() as cur:
        cur.execute(deal_sql, (slug,))
        deal = cur.fetchone()
        if not deal:
            raise RuntimeError(
                f"Deal {slug!r} not found in DB. Run `python -m services.reimbursement_api seed` first."
            )
        cur.execute(inst_sql, (deal["id"],))
        instruments = cur.fetchall()

    return {
        "config": cfg,
        "deal": dict(deal),
        "instruments": [dict(r) for r in instruments],
    }
