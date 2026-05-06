-- Track Outlook calendar event IDs per critical date so re-runs don't
-- duplicate events. Created when calendar_push.py POSTs an event; cleared
-- on date update so the next push refreshes the event.

ALTER TABLE dates
    ADD COLUMN IF NOT EXISTS outlook_event_id TEXT,
    ADD COLUMN IF NOT EXISTS outlook_pushed_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS dates_outlook_unpushed_idx
    ON dates(value)
    WHERE agreed = TRUE
      AND human_acked = TRUE
      AND outlook_event_id IS NULL;
