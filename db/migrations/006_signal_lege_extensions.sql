-- Extend signal_kind and signal_source enums for Wave-2 lege/agency/industry watchers.
-- The signals/persistence/digest/ask pipeline stays the same; only the kinds
-- and sources expand. Each ALTER TYPE ADD VALUE runs as its own statement
-- (Postgres requires this — they can't be batched in a single transaction).

ALTER TYPE signal_kind ADD VALUE IF NOT EXISTS 'lege_bill';
ALTER TYPE signal_kind ADD VALUE IF NOT EXISTS 'agency_rulemaking';
ALTER TYPE signal_kind ADD VALUE IF NOT EXISTS 'industry_group_action';

ALTER TYPE signal_source ADD VALUE IF NOT EXISTS 'tx_lege';
ALTER TYPE signal_source ADD VALUE IF NOT EXISTS 'tceq_rulemaking';
ALTER TYPE signal_source ADD VALUE IF NOT EXISTS 'tx_ag';
ALTER TYPE signal_source ADD VALUE IF NOT EXISTS 'tx_comptroller';
ALTER TYPE signal_source ADD VALUE IF NOT EXISTS 'tab';
ALTER TYPE signal_source ADD VALUE IF NOT EXISTS 'agc_tx';
ALTER TYPE signal_source ADD VALUE IF NOT EXISTS 'uli';
ALTER TYPE signal_source ADD VALUE IF NOT EXISTS 'naiop_reca';
