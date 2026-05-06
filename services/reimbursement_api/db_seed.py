"""Idempotent seed: pilot YAML + eligibility-schema YAMLs -> Postgres rows.

Run with: `python -m services.reimbursement_api seed`

What it does:
  1. Upsert the pilot deal into `deals`.
  2. Upsert each instrument declared in pilot_lavon.yml into `instruments`.
  3. For each instrument, parse templates/eligibility_schemas/lavon/<kind>.yml
     and upsert one `eligibility_rules` row per `categories.*` entry. Anything
     left as `advisor_signoff: pending` lands with `advisor_signoff = FALSE`,
     so Capture mode treats it as draft until counsel signs off.

Idempotent: re-running won't duplicate rows. Categories that disappear from
YAML are NOT deleted from DB — that requires manual cleanup so we don't
accidentally drop advisor-approved history.
"""
from __future__ import annotations

import json
from typing import Any

import yaml

from services.common.config import REPO_ROOT, pilot_config
from services.common.db import cursor


def _upsert_deal(cur, cfg: dict[str, Any]) -> str:
    deal = cfg["deal"]
    cur.execute(
        """
        INSERT INTO deals (slug, name, jurisdiction, county, state, status, stage_notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (slug) DO UPDATE SET
            name = EXCLUDED.name,
            jurisdiction = EXCLUDED.jurisdiction,
            county = EXCLUDED.county,
            state = EXCLUDED.state,
            status = EXCLUDED.status,
            stage_notes = EXCLUDED.stage_notes,
            updated_at = NOW()
        RETURNING id
        """,
        (
            deal["slug"],
            deal["name"],
            deal["jurisdiction"],
            deal["county"],
            deal.get("state", "TX"),
            deal["status"],
            deal.get("stage_notes"),
        ),
    )
    return cur.fetchone()["id"]


def _upsert_instrument(cur, deal_id: str, inst: dict[str, Any]) -> str:
    cur.execute(
        """
        INSERT INTO instruments (deal_id, kind, name, status)
        VALUES (%s, %s::pf_instrument_kind, %s, %s)
        ON CONFLICT (deal_id, kind, name) DO UPDATE SET
            status = EXCLUDED.status,
            updated_at = NOW()
        RETURNING id
        """,
        (deal_id, inst["kind"], inst["name"], inst["status"]),
    )
    return cur.fetchone()["id"]


def _upsert_eligibility_rules(cur, instrument_id: str, schema_path: str) -> int:
    path = REPO_ROOT / schema_path if not schema_path.startswith("/") else schema_path
    with open(path, "r", encoding="utf-8") as f:
        schema = yaml.safe_load(f)

    advisor_map = {
        "pending": ("internal_draft", False),
        "accepted": ("bond_counsel", True),
        "hedged": ("bond_counsel", False),
        "declined": ("bond_counsel", False),
    }

    n = 0
    for category, body in (schema.get("categories") or {}).items():
        signoff_state = body.get("advisor_signoff", "pending")
        advisor, accepted = advisor_map.get(signoff_state, ("internal_draft", False))
        rule_yaml = yaml.safe_dump({category: body}, sort_keys=False)
        cur.execute(
            """
            INSERT INTO eligibility_rules (
                instrument_id, category, rule_yaml, advisor, advisor_signoff, version
            )
            SELECT %s, %s, %s, %s, %s, 1
            WHERE NOT EXISTS (
                SELECT 1 FROM eligibility_rules
                WHERE instrument_id = %s AND category = %s AND superseded_by IS NULL
            )
            """,
            (
                instrument_id,
                category,
                rule_yaml,
                advisor,
                accepted,
                instrument_id,
                category,
            ),
        )
        n += cur.rowcount or 0
    return n


def seed_pilot() -> dict[str, Any]:
    cfg = pilot_config()
    summary: dict[str, Any] = {
        "deal": cfg["deal"]["slug"],
        "instruments": [],
        "rules_inserted": 0,
    }

    with cursor() as cur:
        deal_id = _upsert_deal(cur, cfg)
        summary["deal_id"] = deal_id

        for inst in cfg["instruments"]:
            instrument_id = _upsert_instrument(cur, deal_id, inst)
            n_rules = _upsert_eligibility_rules(cur, instrument_id, inst["eligibility_schema"])
            summary["instruments"].append(
                {"kind": inst["kind"], "name": inst["name"], "id": instrument_id, "new_rules": n_rules}
            )
            summary["rules_inserted"] += n_rules

    return summary


if __name__ == "__main__":
    print(json.dumps(seed_pilot(), indent=2, default=str))
