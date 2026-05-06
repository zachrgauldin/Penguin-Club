-- Contracts: PSAs, lot purchases, dev/reimbursement agreements, takedowns.
-- Dual-extraction agreement is enforced in `dates`: extraction_a + extraction_b
-- must agree on `value` and `source_ref` before `agreed = TRUE`.

CREATE TYPE contract_kind AS ENUM (
    'psa',
    'loi',
    'lot_purchase',
    'takedown',
    'dev_agreement',
    'reimbursement_agreement',
    'other'
);

CREATE TABLE IF NOT EXISTS contracts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deal_id             UUID REFERENCES deals(id) ON DELETE SET NULL,
    kind                contract_kind NOT NULL,
    counterparty        TEXT NOT NULL,
    counterparty_tier   TEXT CHECK (counterparty_tier IN ('luxury','national_public','regional_production','seller','city','mud','tirz_board','other')),
    title               TEXT NOT NULL,
    document_uri        TEXT NOT NULL,
    sharepoint_item_id  TEXT,
    effective_date      DATE,
    parsed_at           TIMESTAMPTZ,
    parse_status        TEXT NOT NULL DEFAULT 'pending' CHECK (parse_status IN ('pending','parsing','parsed','needs_human','failed')),
    parse_error         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS contracts_deal_idx ON contracts(deal_id);
CREATE INDEX IF NOT EXISTS contracts_status_idx ON contracts(parse_status);

CREATE TYPE date_kind AS ENUM (
    'effective',
    'feasibility_end',
    'em_go_hard',
    'extension_window_start',
    'extension_window_end',
    'closing',
    'takedown',
    'option_exercise',
    'post_closing_obligation',
    'expiration',
    'other'
);

-- Critical dates flow through the dual-extraction pipeline.
-- `value`/`source_ref` are canonical only after both extractions agree
-- AND `human_acked = TRUE` (for dates flagged as critical).
CREATE TABLE IF NOT EXISTS dates (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id         UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    kind                date_kind NOT NULL,
    label               TEXT,
    extraction_a_value  DATE,
    extraction_a_source TEXT,
    extraction_a_model  TEXT,
    extraction_b_value  DATE,
    extraction_b_source TEXT,
    extraction_b_model  TEXT,
    agreed              BOOLEAN NOT NULL DEFAULT FALSE,
    value               DATE,
    source_ref          TEXT,
    is_critical         BOOLEAN NOT NULL DEFAULT FALSE,
    human_acked         BOOLEAN NOT NULL DEFAULT FALSE,
    human_acked_at      TIMESTAMPTZ,
    human_acked_by      TEXT,
    confidence          NUMERIC(3,2),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS dates_contract_idx ON dates(contract_id);
CREATE INDEX IF NOT EXISTS dates_value_idx ON dates(value) WHERE agreed = TRUE;
CREATE INDEX IF NOT EXISTS dates_critical_unacked_idx ON dates(value)
    WHERE is_critical = TRUE AND (agreed = FALSE OR human_acked = FALSE);

CREATE TYPE obligation_kind AS ENUM (
    'earnest_money',
    'extension_fee',
    'escrow_cap',
    'indemnity_cap',
    'liquidated_damages',
    'lot_price',
    'lot_escalator',
    'option_fee',
    'lot_premium',
    'other'
);

CREATE TABLE IF NOT EXISTS obligations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id         UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    kind                obligation_kind NOT NULL,
    label               TEXT,
    amount              NUMERIC(14,2),
    unit                TEXT,
    formula             TEXT,
    source_ref          TEXT,
    confidence          NUMERIC(3,2),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS obligations_contract_idx ON obligations(contract_id);

CREATE TABLE IF NOT EXISTS takedown_schedules (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id         UUID NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    deal_id             UUID REFERENCES deals(id) ON DELETE SET NULL,
    builder             TEXT NOT NULL,
    builder_tier        TEXT CHECK (builder_tier IN ('luxury','national_public','regional_production')),
    section             TEXT,
    lot_count           INTEGER,
    base_lot_price      NUMERIC(14,2),
    escalator_pct       NUMERIC(5,4),
    escalator_basis     TEXT,
    option_fee          NUMERIC(14,2),
    cadence             TEXT,
    first_takedown_on   DATE,
    last_takedown_on    DATE,
    velocity_per_qtr    NUMERIC(8,2),
    default_triggers    TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS takedown_deal_idx ON takedown_schedules(deal_id);

-- Weekly miss-audit log: the digest that goes to the principal every Sunday.
CREATE TABLE IF NOT EXISTS miss_audits (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    week_starting       DATE NOT NULL,
    flagged_count       INTEGER NOT NULL DEFAULT 0,
    low_confidence_count INTEGER NOT NULL DEFAULT 0,
    unparseable_count   INTEGER NOT NULL DEFAULT 0,
    digest_uri          TEXT,
    principal_acked     BOOLEAN NOT NULL DEFAULT FALSE,
    principal_acked_at  TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (week_starting)
);
