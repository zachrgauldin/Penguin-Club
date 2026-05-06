-- Firm negotiation memory.
-- Every accepted/rejected/hedged/compromised redline across the firm's
-- corpus of PSAs, LOIs, lot purchases, takedowns, dev/reimbursement
-- agreements, and bond/instrument paperwork. Drives every future agreement
-- Agents 2 and 3 touch.

CREATE TYPE negotiation_doc_kind AS ENUM (
    'psa',
    'loi',
    'lot_purchase',
    'takedown',
    'dev_agreement',
    'reimbursement_agreement',
    'bond_instrument',
    'other'
);

CREATE TYPE negotiation_outcome AS ENUM (
    'accepted',
    'rejected',
    'hedged',
    'compromised',
    'ambiguous'
);

CREATE TABLE IF NOT EXISTS negotiated_positions (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id          UUID REFERENCES contracts(id) ON DELETE SET NULL,
    deal_id              UUID REFERENCES deals(id) ON DELETE SET NULL,
    doc_kind             negotiation_doc_kind NOT NULL,
    counterparty         TEXT,
    counterparty_tier    TEXT,
    section_title        TEXT NOT NULL,
    firm_position        TEXT NOT NULL,
    counterparty_position TEXT,
    final_outcome        negotiation_outcome NOT NULL,
    final_text           TEXT,
    rationale            TEXT,
    source_doc_uri       TEXT NOT NULL,
    source_ref           TEXT,
    tags                 TEXT[] NOT NULL DEFAULT '{}',
    confidence           NUMERIC(3,2),
    model_id             TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS negotiated_positions_kind_idx
    ON negotiated_positions(doc_kind, final_outcome);
CREATE INDEX IF NOT EXISTS negotiated_positions_tier_idx
    ON negotiated_positions(counterparty_tier);
CREATE INDEX IF NOT EXISTS negotiated_positions_tags_idx
    ON negotiated_positions USING GIN (tags);
CREATE INDEX IF NOT EXISTS negotiated_positions_section_idx
    ON negotiated_positions(section_title);
