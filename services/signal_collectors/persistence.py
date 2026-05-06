"""Persist NormalizedScan candidates to `signals` + `signal_pilot_links`.

Dedupe is enforced by the unique `dedupe_key`. Re-ingesting the same URL
is a no-op for unchanged items; new items added to an agenda land as new
rows. `collector_runs` records every run for freshness auditing.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from services.common.anthropic_client import SONNET
from services.common.db import cursor
from services.signal_collectors.normalize import NormalizeResult
from services.signal_collectors.schemas import CandidateSignal, SignalSource


def _dedupe_key(source_url: str, title: str, occurred_on: date | None) -> str:
    norm_title = re.sub(r"[^a-z0-9]+", "", title.lower())[:80]
    payload = f"{source_url}|{norm_title}|{occurred_on or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


@dataclass
class PersistedSignal:
    signal_id: str
    inserted: bool
    dedupe_key: str
    impact_score: int
    n_links: int


@dataclass
class PersistedScan:
    collector_run_id: str
    new_signals: int
    duplicate_signals: int
    high_impact_signals: int
    persisted: list[PersistedSignal]


def _start_run(cur, source: SignalSource) -> str:
    cur.execute(
        """
        INSERT INTO collector_runs (source, status)
        VALUES (%s::signal_source, 'running')
        RETURNING id
        """,
        (source,),
    )
    return cur.fetchone()["id"]


def _finish_run(cur, run_id: str, new_count: int, error: str | None) -> None:
    cur.execute(
        """
        UPDATE collector_runs
        SET finished_at = NOW(),
            status = %s,
            new_signals = %s,
            error = %s
        WHERE id = %s
        """,
        ("ok" if error is None else "failed", new_count, error, run_id),
    )


def _upsert_signal(
    cur,
    *,
    source: SignalSource,
    candidate: CandidateSignal,
    source_url: str,
    raw_payload: dict[str, Any],
) -> tuple[str, bool]:
    key = _dedupe_key(source_url, candidate.title, candidate.occurred_on)
    cur.execute(
        """
        INSERT INTO signals (
            kind, source, occurred_on, title, summary,
            source_url, raw_payload, impact_score, impact_rationale,
            model_id, dedupe_key
        )
        VALUES (
            %s::signal_kind, %s::signal_source, %s, %s, %s,
            %s, %s::jsonb, %s, %s,
            %s, %s
        )
        ON CONFLICT (dedupe_key) DO NOTHING
        RETURNING id
        """,
        (
            candidate.kind,
            source,
            candidate.occurred_on,
            candidate.title,
            candidate.summary,
            source_url,
            json.dumps(raw_payload, default=str),
            candidate.impact_score,
            candidate.impact_rationale,
            SONNET,
            key,
        ),
    )
    row = cur.fetchone()
    if row is not None:
        return row["id"], True

    cur.execute("SELECT id FROM signals WHERE dedupe_key = %s", (key,))
    return cur.fetchone()["id"], False


def _link_to_pilot(
    cur,
    *,
    signal_id: str,
    deal_id: str,
    candidate: CandidateSignal,
    instruments_by_kind: dict[str, dict[str, Any]],
) -> int:
    n = 0
    if not candidate.affected_instruments:
        cur.execute(
            """
            INSERT INTO signal_pilot_links (signal_id, deal_id, relevance_score, rationale)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (signal_id, deal_id, candidate.impact_score, candidate.impact_rationale),
        )
        n += cur.rowcount or 0
        return n

    for kind in candidate.affected_instruments:
        inst = instruments_by_kind.get(kind)
        if inst is None:
            continue
        cur.execute(
            """
            INSERT INTO signal_pilot_links (
                signal_id, deal_id, instrument_id, relevance_score, rationale
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                signal_id,
                deal_id,
                inst["id"],
                candidate.impact_score,
                candidate.impact_rationale,
            ),
        )
        n += cur.rowcount or 0
    return n


def persist_scan(
    *,
    source: SignalSource,
    result: NormalizeResult,
) -> PersistedScan:
    persisted: list[PersistedSignal] = []
    new_count = 0
    dup_count = 0
    high_impact = 0

    with cursor() as cur:
        run_id = _start_run(cur, source)

        for cand in result.scan.candidates:
            try:
                signal_id, inserted = _upsert_signal(
                    cur,
                    source=source,
                    candidate=cand,
                    source_url=result.scan.source_url,
                    raw_payload={
                        "candidate": cand.model_dump(),
                    },
                )
                if inserted:
                    new_count += 1
                else:
                    dup_count += 1

                n_links = _link_to_pilot(
                    cur,
                    signal_id=signal_id,
                    deal_id=result.deal_id,
                    candidate=cand,
                    instruments_by_kind=result.instruments_by_kind,
                )

                if cand.impact_score >= 4:
                    high_impact += 1

                persisted.append(
                    PersistedSignal(
                        signal_id=signal_id,
                        inserted=inserted,
                        dedupe_key=_dedupe_key(
                            result.scan.source_url, cand.title, cand.occurred_on
                        ),
                        impact_score=cand.impact_score,
                        n_links=n_links,
                    )
                )
            except Exception as e:
                _finish_run(cur, run_id, new_count, str(e))
                raise

        _finish_run(cur, run_id, new_count, None)

    return PersistedScan(
        collector_run_id=run_id,
        new_signals=new_count,
        duplicate_signals=dup_count,
        high_impact_signals=high_impact,
        persisted=persisted,
    )
