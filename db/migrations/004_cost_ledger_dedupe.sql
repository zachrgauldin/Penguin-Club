-- Idempotent cost-ledger imports: dedupe by (deal_id, raw_row_hash).
-- The hash is computed by services.reimbursement_api.ledger_loader from
-- posted_on + vendor + invoice_number + description + amount + gl_account
-- so re-importing the same export is a no-op.

ALTER TABLE cost_ledger
    ALTER COLUMN raw_row_hash SET NOT NULL;

ALTER TABLE cost_ledger
    ADD CONSTRAINT cost_ledger_dedupe UNIQUE (deal_id, raw_row_hash);
