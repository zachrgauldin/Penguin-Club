---
name: contracts
description: Use for any work on PSAs, LOIs, builder lot purchase agreements, takedown agreements, dev/reimbursement agreements — extracting critical dates and dollar obligations, projecting takedown cash flow, generating the weekly miss-audit, answering one-page deal-status queries. Critical dates run through dual-extraction agreement (Sonnet pass + Opus verify); never auto-canonicalized without agreement. Missed dates are the firm's defined kill switch — guardrails are non-negotiable. Triggered by `/contracts extract`, `/contracts calendar`, `/contracts takedown-forecast`, `/contracts weekly-audit`.
---

# Contracts Skill

PSA / lot-purchase / takedown date and obligation tracker. Missed dates are the kill switch — every guardrail below is non-negotiable.

## Kill-switch guardrails (always on)

- **Dual-extraction agreement.** Every critical date (closing, EM go-hard, takedown deadlines, extension windows) is extracted twice. Pass A: Sonnet 4.6 with the firm's form library cached. Pass B: Opus 4.7 verifying from the raw document. Both must agree on `value` AND `source_ref`. If they disagree, `agreed = FALSE`, and the date is flagged human-verify.
- **Source-link required.** Every extracted date and obligation includes page + section reference in `source_ref`. Calendar entry hyperlinks back to the source clause.
- **Human ack on critical dates.** `is_critical = TRUE` dates require `human_acked = TRUE` before they propagate to Outlook. Critical kinds: `closing`, `em_go_hard`, `takedown`.
- **Weekly miss-audit.** Sunday digest to the principal: every flagged date, every low-confidence date, every contract that failed parse. Principal acknowledges each line; the row writes to `miss_audits`.

## Sub-commands

### `/contracts extract`

For a contract file (path or `sharepoint_item_id`):
1. Insert/upsert into `contracts` with `parse_status = 'parsing'`.
2. Run dual extraction pipeline producing rows in `dates` and `obligations`.
3. For each date row: populate `extraction_a_*` and `extraction_b_*`. Set `agreed = TRUE` and copy to `value`/`source_ref` only if both agree.
4. For takedown agreements, also produce a `takedown_schedules` row.
5. Set `parse_status = 'parsed'` (or `'needs_human'` if any critical date disagreed).

### `/contracts calendar`

Push agreed + acked dates into Outlook calendar. Each event:
- title: `{deal} — {contract.title} — {date.kind}`
- body: `source_ref` deeplink + `contract.document_uri`
- reminders at 60/30/14/7/1 days before

### `/contracts takedown-forecast`

Per-deal cash-flow projection from `takedown_schedules`. Joins `velocity_per_qtr` × `(base_lot_price × (1 + escalator_pct)^k)` per quarter, segments by `builder_tier`. Writes a Word/Excel deliverable to the deal folder.

### `/contracts weekly-audit`

Sunday job. Builds the miss-audit digest:
- every `dates` row created in the last 7 days where `agreed = FALSE`
- every `dates` row with `confidence < 0.85`
- every `contracts` row with `parse_status IN ('needs_human','failed')`
- every critical date with `human_acked = FALSE`

Writes the Word digest to `templates/digest/weekly_audit.docx`, drops it in the principal's OneDrive review folder, and inserts a `miss_audits` row.

## Models

- **Sonnet 4.6** — pass A extraction with the firm's form library + redline-history cached as prompt prefix
- **Opus 4.7** — pass B verification on every critical date
- **Haiku 4.5** — file-type routing (which `contract_kind`?) and OCR triage

## Inputs expected on SharePoint

`/Deals/<Deal>/Contracts/` and subfolders. The watcher fires on file create/update.

## Acceptance bars

- 12-month backfill: **100% recall** on `closing` and `em_go_hard` dates (zero-tolerance — kill switch)
- ≥90% recall on `extension_*` and `takedown` dates
- Every extraction source-linked
- Takedown-forecast cash flow within 5% of actuals on completed sections
