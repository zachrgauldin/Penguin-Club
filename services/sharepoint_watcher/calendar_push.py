"""Push agreed + acked critical dates to Outlook calendar.

Pulls every dates row where agreed=TRUE AND human_acked=TRUE AND
outlook_event_id IS NULL, creates an all-day event in the configured
shared calendar, and stores the returned eventId so re-runs are
idempotent. Re-pushing requires either --force or the operator
clearing outlook_event_id on the row.

V1 reminder model: a single 1-day-before reminder. Multi-tier
reminders (60/30/14/7/1 days) need a daily forward-rollcall job
or per-tier duplicate events; out of scope for V1.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from services.common.config import pilot_config
from services.common.db import cursor
from services.sharepoint_watcher.graph_client import GraphClient


@dataclass
class CalendarPushResult:
    calendar_user: str
    candidates: int
    pushed: int
    skipped: int
    failed: int
    errors: list[dict[str, Any]]


def _resolve_calendar_user() -> str:
    cfg = pilot_config()
    user = (cfg.get("outputs") or {}).get("outlook_calendar")
    if not user or "TODO" in user:
        raise RuntimeError(
            "pilot config outputs.outlook_calendar not configured. "
            "Set the shared mailbox / user UPN in configs/pilot_lavon.yml."
        )
    return user


def _gather_unpushed_dates(*, force: bool) -> list[dict[str, Any]]:
    if force:
        sql = """
            SELECT d.id, d.kind::text AS kind, d.label, d.value, d.source_ref,
                   d.outlook_event_id,
                   c.title AS contract_title, c.document_uri,
                   c.kind::text AS contract_kind
            FROM dates d
            JOIN contracts c ON c.id = d.contract_id
            WHERE d.agreed = TRUE
              AND d.human_acked = TRUE
              AND d.value IS NOT NULL
              AND d.value >= CURRENT_DATE
            ORDER BY d.value ASC
        """
    else:
        sql = """
            SELECT d.id, d.kind::text AS kind, d.label, d.value, d.source_ref,
                   d.outlook_event_id,
                   c.title AS contract_title, c.document_uri,
                   c.kind::text AS contract_kind
            FROM dates d
            JOIN contracts c ON c.id = d.contract_id
            WHERE d.agreed = TRUE
              AND d.human_acked = TRUE
              AND d.outlook_event_id IS NULL
              AND d.value IS NOT NULL
              AND d.value >= CURRENT_DATE
            ORDER BY d.value ASC
        """
    with cursor() as cur:
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def _build_event_body(date_row: dict[str, Any]) -> dict[str, Any]:
    value: date = date_row["value"]
    end_value = value + timedelta(days=1)

    body_lines = [
        f"<b>Contract:</b> {date_row['contract_title']} ({date_row['contract_kind']})",
        f"<b>Source:</b> {date_row.get('source_ref') or '(none)'}",
        f"<b>Document:</b> <a href=\"{date_row['document_uri']}\">{date_row['document_uri']}</a>",
        "<br/><i>Auto-pushed from Penguin-Club. Update or delete the underlying date to refresh.</i>",
    ]

    return {
        "subject": f"[{date_row['kind']}] {date_row['label']}",
        "body": {
            "contentType": "HTML",
            "content": "<br/>".join(body_lines),
        },
        "start": {"dateTime": value.isoformat() + "T00:00:00", "timeZone": "America/Chicago"},
        "end": {"dateTime": end_value.isoformat() + "T00:00:00", "timeZone": "America/Chicago"},
        "isAllDay": True,
        "isReminderOn": True,
        "reminderMinutesBeforeStart": 1440,
        "categories": ["Penguin-Club", date_row["kind"]],
    }


def _record_event_id(*, date_id: str, event_id: str) -> None:
    with cursor() as cur:
        cur.execute(
            """
            UPDATE dates
            SET outlook_event_id = %s,
                outlook_pushed_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
            """,
            (event_id, date_id),
        )


def push_calendar(*, force: bool = False) -> CalendarPushResult:
    user = _resolve_calendar_user()
    candidates = _gather_unpushed_dates(force=force)
    pushed = skipped = failed = 0
    errors: list[dict[str, Any]] = []

    if not candidates:
        return CalendarPushResult(
            calendar_user=user, candidates=0, pushed=0, skipped=0, failed=0, errors=[]
        )

    with GraphClient() as client:
        for row in candidates:
            try:
                event = client.post(
                    f"/users/{user}/calendar/events",
                    _build_event_body(row),
                )
                event_id = event.get("id")
                if not event_id:
                    failed += 1
                    errors.append({"date_id": row["id"], "error": "no eventId in response"})
                    continue
                _record_event_id(date_id=row["id"], event_id=event_id)
                pushed += 1
            except Exception as e:
                failed += 1
                errors.append({"date_id": row["id"], "error": str(e)})

    return CalendarPushResult(
        calendar_user=user,
        candidates=len(candidates),
        pushed=pushed,
        skipped=skipped,
        failed=failed,
        errors=errors,
    )
