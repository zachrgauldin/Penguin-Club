-- Public-finance core: deals, instruments, bond orders, cost ledger,
-- reimbursements, eligibility rules, structuring positions.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS deals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug            TEXT UNIQUE NOT NULL,
    name            TEXT NOT NULL,
    jurisdiction    TEXT NOT NULL,
    county          TEXT NOT NULL,
    state           TEXT NOT NULL DEFAULT 'TX',
    status          TEXT NOT NULL CHECK (status IN ('prospect','under_contract','entitling','horizontal','vertical','built_out','sold')),
    stage_notes     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TYPE pf_instrument_kind AS ENUM ('pid','mud','tirz','380','381');

CREATE TABLE IF NOT EXISTS instruments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deal_id             UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    kind                pf_instrument_kind NOT NULL,
    name                TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('proposed','drafting','authorized','active','closed')),
    authorized_amount   NUMERIC(14,2),
    issued_amount       NUMERIC(14,2) DEFAULT 0,
    capacity_remaining  NUMERIC(14,2),
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (deal_id, kind, name)
);

CREATE TABLE IF NOT EXISTS bond_orders (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id       UUID NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    series              TEXT NOT NULL,
    adopted_on          DATE,
    par_amount          NUMERIC(14,2),
    project_plan_uri    TEXT,
    bond_order_uri      TEXT,
    engineers_report_uri TEXT,
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (instrument_id, series)
);

-- Eligibility rules are advisor-approved YAML loaded into Postgres.
-- Column `category` matches the bucketed taxonomy (e.g. hard_cost.streets,
-- soft_cost.engineering, indirect.financing, non_eligible.marketing).
CREATE TABLE IF NOT EXISTS eligibility_rules (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id       UUID NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    category            TEXT NOT NULL,
    rule_yaml           TEXT NOT NULL,
    advisor             TEXT NOT NULL CHECK (advisor IN ('bond_counsel','municipal_advisor','pid_admin','internal_draft')),
    advisor_signoff     BOOLEAN NOT NULL DEFAULT FALSE,
    advisor_signoff_at  TIMESTAMPTZ,
    advisor_signoff_by  TEXT,
    version             INTEGER NOT NULL DEFAULT 1,
    superseded_by       UUID REFERENCES eligibility_rules(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cost_ledger (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deal_id             UUID NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
    posted_on           DATE NOT NULL,
    vendor              TEXT,
    invoice_number      TEXT,
    description         TEXT NOT NULL,
    amount              NUMERIC(14,2) NOT NULL,
    gl_account          TEXT,
    backup_uri          TEXT,
    raw_row_hash        TEXT,
    imported_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS cost_ledger_deal_idx ON cost_ledger(deal_id, posted_on);

-- Classification of a ledger line into a specific instrument's category.
-- A single ledger line can be classified against multiple instruments
-- (e.g. a road cost split between MUD and PID); rows are 1-per-instrument.
CREATE TABLE IF NOT EXISTS ledger_classifications (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cost_ledger_id      UUID NOT NULL REFERENCES cost_ledger(id) ON DELETE CASCADE,
    instrument_id       UUID NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    category            TEXT NOT NULL,
    eligible_amount     NUMERIC(14,2) NOT NULL,
    confidence          NUMERIC(3,2),
    rationale           TEXT,
    model_id            TEXT,
    advisor_review      TEXT CHECK (advisor_review IN ('pending','approved','adjusted','rejected')) DEFAULT 'pending',
    advisor_notes       TEXT,
    classified_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ledger_class_cost_idx ON ledger_classifications(cost_ledger_id);
CREATE INDEX IF NOT EXISTS ledger_class_instrument_idx ON ledger_classifications(instrument_id);

CREATE TABLE IF NOT EXISTS reimbursements (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id       UUID NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    packet_number       TEXT NOT NULL,
    submitted_on        DATE,
    requested_amount    NUMERIC(14,2),
    approved_amount     NUMERIC(14,2),
    paid_amount         NUMERIC(14,2),
    paid_on             DATE,
    status              TEXT NOT NULL CHECK (status IN ('drafting','submitted','approved','partially_paid','paid','rejected')),
    packet_uri          TEXT,
    notes               TEXT,
    UNIQUE (instrument_id, packet_number)
);

-- Structuring proposals: every frontier idea Agent 2 surfaces, with
-- advisor signoffs. This is the firm's PF accepted-position memory and
-- the foundation of the audit-ready defensibility binder.
CREATE TABLE IF NOT EXISTS pf_positions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instrument_id       UUID REFERENCES instruments(id) ON DELETE SET NULL,
    deal_id             UUID REFERENCES deals(id) ON DELETE SET NULL,
    family              TEXT NOT NULL CHECK (family IN ('soft_cost_capture','stacking_layout','grant_on_commercial','timing_escalator','other')),
    title               TEXT NOT NULL,
    proposal            TEXT NOT NULL,
    estimated_dollars   NUMERIC(14,2),
    bond_counsel_view   TEXT CHECK (bond_counsel_view IN ('pending','accepted','hedged','declined')) DEFAULT 'pending',
    bond_counsel_notes  TEXT,
    municipal_advisor_view TEXT CHECK (municipal_advisor_view IN ('pending','accepted','hedged','declined')) DEFAULT 'pending',
    municipal_advisor_notes TEXT,
    pid_admin_view      TEXT CHECK (pid_admin_view IN ('pending','accepted','hedged','declined')) DEFAULT 'pending',
    pid_admin_notes     TEXT,
    incorporated_into   TEXT,
    risk_notes          TEXT,
    model_id            TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS pf_positions_deal_idx ON pf_positions(deal_id);
CREATE INDEX IF NOT EXISTS pf_positions_instrument_idx ON pf_positions(instrument_id);
