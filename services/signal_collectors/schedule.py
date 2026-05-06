"""Signal-collector scheduler.

Reads `signals.sources` from the pilot config — each source has a cadence
and a list of URLs — and runs `ingest_url` against everything that's due
relative to the most recent successful collector_runs row for that source.

This is the simplest possible scheduler: no per-site HTML scrapers, no
agenda-link diffing, no parallelism. The operator confirms one URL at a
time in the pilot config; this runs them all on the right cadence; the
existing dedupe_key keeps the signals table clean across re-ingests.

Wire to cron once the URLs are confirmed:
  0 7 * * * cd /opt/penguin && python -m services.signal_collectors run-schedule
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.common.config import pilot_config
from services.common.db import cursor
from services.signal_collectors.ingest import ingest_url
from services.signal_collectors.schemas import SignalSource


CADENCE_THRESHOLDS_SECONDS: dict[str, int] = {
    "daily": 23 * 3600,
    "daily_in_filing_window": 23 * 3600,
    "weekly": 6 * 86400,
    "monthly": 28 * 86400,
}


def _last_successful_run(source: str) -> datetime | None:
    with cursor() as cur:
        cur.execute(
            """
            SELECT MAX(started_at) AS last_run
            FROM collector_runs
            WHERE source = %s::signal_source AND status = 'ok'
            """,
            (source,),
        )
        row = cur.fetchone()
    return row["last_run"] if row and row.get("last_run") else None


def _is_due(source: str, cadence: str, force: bool) -> bool:
    if force:
        return True
    threshold = CADENCE_THRESHOLDS_SECONDS.get(cadence, CADENCE_THRESHOLDS_SECONDS["weekly"])
    last = _last_successful_run(source)
    if last is None:
        return True
    age = (datetime.now(timezone.utc) - last).total_seconds()
    return age >= threshold


def run_schedule(
    *, only_source: str | None = None, force: bool = False
) -> dict[str, Any]:
    cfg = pilot_config()
    sources = (cfg.get("signals") or {}).get("sources") or {}
    results: list[dict[str, Any]] = []

    for source, body in sources.items():
        if only_source and source != only_source:
            continue
        cadence = body.get("cadence", "daily")
        urls = body.get("urls") or []
        if not urls:
            results.append({"source": source, "skipped": "no_urls"})
            continue
        if not _is_due(source, cadence, force):
            results.append({"source": source, "skipped": "not_due"})
            continue

        for url in urls:
            if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                results.append({"source": source, "url": url, "skipped": "invalid_url"})
                continue
            try:
                result = ingest_url(url=url, source=source)
                results.append(
                    {
                        "source": source,
                        "url": url,
                        "status": "ok",
                        "new_signals": result.persisted.new_signals,
                        "duplicate_signals": result.persisted.duplicate_signals,
                        "high_impact_signals": result.persisted.high_impact_signals,
                    }
                )
            except Exception as e:
                results.append(
                    {"source": source, "url": url, "status": "error", "error": str(e)}
                )

    return {"results": results, "n_runs": len(results)}
