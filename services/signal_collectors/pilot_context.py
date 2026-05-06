"""Pilot context block for Agent 1's cached system prompt.

Loads the active deal, its instruments, and the firm's accepted-position
library, then renders a deterministic text block. Stable bytes are critical:
this block goes in the cached prompt prefix, and any byte change invalidates
the cache.
"""
from __future__ import annotations

from typing import Any

from services.common.config import pilot_config
from services.common.db import cursor


def load_pilot_context_text() -> dict[str, Any]:
    cfg = pilot_config()
    slug = cfg["deal"]["slug"]

    with cursor() as cur:
        cur.execute(
            "SELECT id, slug, name, jurisdiction, county, state, status, stage_notes "
            "FROM deals WHERE slug = %s",
            (slug,),
        )
        deal = cur.fetchone()
        if deal is None:
            raise RuntimeError(
                f"Deal {slug!r} not found in DB. "
                "Run `python -m services.reimbursement_api seed` first."
            )

        cur.execute(
            """
            SELECT id, kind::text, name, status, authorized_amount, capacity_remaining
            FROM instruments
            WHERE deal_id = %s
            ORDER BY kind::text
            """,
            (deal["id"],),
        )
        instruments = [dict(r) for r in cur.fetchall()]

        cur.execute(
            """
            SELECT title, family, estimated_dollars, incorporated_into
            FROM pf_positions
            WHERE deal_id = %s
              AND bond_counsel_view = 'accepted'
              AND municipal_advisor_view = 'accepted'
              AND pid_admin_view = 'accepted'
            ORDER BY created_at ASC
            """,
            (deal["id"],),
        )
        accepted_positions = [dict(r) for r in cur.fetchall()]

    instrument_lines = "\n".join(
        f"- {i['kind']} — {i['name']} — status={i['status']} "
        f"capacity_remaining={i['capacity_remaining']}"
        for i in instruments
    )
    if accepted_positions:
        position_lines = "\n".join(
            f"- {p['title']} (family={p['family']}, "
            f"~${(p['estimated_dollars'] or 0):,.0f}, "
            f"incorporated_into={p['incorporated_into'] or '(pending)'})"
            for p in accepted_positions
        )
    else:
        position_lines = "(no accepted positions yet)"

    block = (
        f"[PILOT CONTEXT]\n"
        f"Deal: {deal['name']}\n"
        f"Jurisdiction: {deal['jurisdiction']}, {deal['county']} County, {deal['state']}\n"
        f"Status: {deal['status']}\n"
        f"Stage notes: {deal.get('stage_notes') or '(none)'}\n\n"
        f"Active instruments:\n{instrument_lines}\n\n"
        f"Accepted PF positions (firm precedent):\n{position_lines}\n"
    )

    return {
        "deal_id": deal["id"],
        "deal_slug": deal["slug"],
        "instruments_by_kind": {i["kind"]: i for i in instruments},
        "context_text": block,
    }
