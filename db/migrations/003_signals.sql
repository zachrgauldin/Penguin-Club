-- Lavon political/entitlement signals: typed rows, source-linked, time-stamped.

CREATE TYPE signal_kind AS ENUM (
    'council_action',
    'pz_action',
    'planner_change',
    'mud_filing',
    'tceq_hearing',
    'ntmwd_action',
    'isd_action',
    'corridor_action',
    'county_action',
    'election_filing',
    'other'
);

CREATE TYPE signal_source AS ENUM (
    'lavon_council',
    'lavon_pz',
    'lavon_staff',
    'lavon_elections',
    'collin_county',
    'tceq_docket',
    'ntmwd',
    'wylie_isd',
    'community_isd',
    'txdot',
    'nctcog',
    'other'
);

CREATE TABLE IF NOT EXISTS signals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind                signal_kind NOT NULL,
    source              signal_source NOT NULL,
    occurred_on         DATE,
    retrieved_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    title               TEXT NOT NULL,
    summary             TEXT,
    source_url          TEXT NOT NULL,
    raw_payload         JSONB,
    impact_score        SMALLINT CHECK (impact_score BETWEEN 0 AND 5),
    impact_rationale    TEXT,
    model_id            TEXT,
    dedupe_key          TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS signals_kind_idx ON signals(kind, occurred_on DESC);
CREATE INDEX IF NOT EXISTS signals_source_idx ON signals(source, occurred_on DESC);
CREATE INDEX IF NOT EXISTS signals_impact_idx ON signals(impact_score DESC, occurred_on DESC);

-- Many-to-many between signals and the deals/instruments they touch.
CREATE TABLE IF NOT EXISTS signal_pilot_links (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_id           UUID NOT NULL REFERENCES signals(id) ON DELETE CASCADE,
    deal_id             UUID REFERENCES deals(id) ON DELETE CASCADE,
    instrument_id       UUID REFERENCES instruments(id) ON DELETE CASCADE,
    relevance_score     SMALLINT CHECK (relevance_score BETWEEN 0 AND 5),
    rationale           TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (deal_id IS NOT NULL OR instrument_id IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS spl_signal_idx ON signal_pilot_links(signal_id);
CREATE INDEX IF NOT EXISTS spl_deal_idx ON signal_pilot_links(deal_id);

-- One row per scheduled collector run, for auditing freshness.
CREATE TABLE IF NOT EXISTS collector_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source              signal_source NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    status              TEXT CHECK (status IN ('running','ok','failed')),
    new_signals         INTEGER DEFAULT 0,
    error               TEXT
);

CREATE INDEX IF NOT EXISTS collector_runs_source_idx ON collector_runs(source, started_at DESC);

-- Daily digest log; weekly digest builds from the same `signals` table.
CREATE TABLE IF NOT EXISTS lavon_digests (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cadence             TEXT NOT NULL CHECK (cadence IN ('daily','weekly')),
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    digest_uri          TEXT,
    signal_count        INTEGER DEFAULT 0,
    high_impact_count   INTEGER DEFAULT 0,
    sent_at             TIMESTAMPTZ,
    UNIQUE (cadence, period_start, period_end)
);
