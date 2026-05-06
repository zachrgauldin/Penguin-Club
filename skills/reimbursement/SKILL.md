---
name: reimbursement
description: Use for any work on stacked PID/MUD/TIRZ/380/381 instruments — drafting bond orders, project plans, dev/reimbursement agreements, assessment methodologies; classifying cost-ledger lines into eligible buckets; preparing reimbursement packets; surfacing frontier structuring proposals (soft-cost over-capture, instrument stacking, 380/381 grants on retained commercial, timing/escalator structure). All proposals route to bond counsel + municipal advisor + PID administrator for signoff before incorporation. Triggered by `/reimbursement structuring`, `/reimbursement classify`, `/reimbursement package`, `/reimbursement registry`.
---

# Reimbursement Skill

Co-author of stacked PID + MUD + TIRZ + 380/381 instruments. Three modes; never substitute for counsel.

## Operating principles

- **Counsel must opine.** Every output is a draft or a proposal. Bond counsel, the municipal advisor, and the PID administrator hold final say on language, eligibility, and structure.
- **Source-link everything.** Every classification cites the exact `eligibility_rules` row + bond-order section that supports it. Every Structuring proposal cites the rule it's stretching and the firm's prior accepted positions.
- **Defensibility is always on.** Every proposal and classification writes to `pf_positions` / `ledger_classifications` with model id, rationale, and advisor review state.
- **Pilot binding.** Default deal context is loaded from `configs/pilot_lavon.yml` unless a specific `--deal <slug>` is passed.

## Sub-commands

### `/reimbursement structuring`

Generates frontier structuring proposals across the four families and persists them to `pf_positions`:

1. **soft_cost_capture** — engineering, legal, financing/carry, mgmt fees, marketing eligibility shells
2. **stacking_layout** — sequenced PID + MUD + TIRZ + 380/381 layout with non-overlapping recoverable buckets
3. **grant_on_commercial** — 380/381 performance grants stacked on horizontal financing for outparcel/retail/BTR/MF
4. **timing_escalator** — interest/carry on outstanding reimbursable balances, escalating caps, structuring for later bond series

Each proposal:
- cites the active `eligibility_rules` rows it stretches
- estimates dollars at stake
- includes a "counsel must opine" banner
- gets routed to bond counsel + MA + PID admin via the deliverable doc

### `/reimbursement classify`

Walks new rows in `cost_ledger` for the active deal. For each line:
- routes via Haiku 4.5: hard_cost / soft_cost / indirect / non_eligible
- Sonnet 4.6 with prompt-cached eligibility schemas + accepted-position library produces per-instrument bucket classifications
- writes one row per instrument it lands in to `ledger_classifications` with confidence and rationale
- flags any line that contradicts a prior advisor-approved position for human review

### `/reimbursement package`

Assembles the next reimbursement packet for an instrument:
- pulls `ledger_classifications` with `advisor_review IN ('approved','pending')` for the target instrument
- generates the Word/Excel packet from `templates/reimbursement_packet/`
- produces a missing-backup punch list (lines without `backup_uri`)
- writes a row to `reimbursements` with status=drafting

### `/reimbursement registry`

Per-deal one-pager: per-instrument capacity remaining, requested / approved / paid / outstanding, packet history, top open Structuring proposals.

## Models

- **Opus 4.7** — Structuring mode reasoning across instruments + accepted positions
- **Sonnet 4.6** — Capture classification with prompt caching on the eligibility schemas
- **Haiku 4.5** — first-pass routing of ledger lines

## Inputs expected on `Inbound/`

- Pilot's bond order, engineer's report, project plan, dev/reimbursement agreements
- Drafts-in-progress for new stacked instruments
- 3–5 prior approved reimbursement packets (training corpus for advisor-validated rules)
- Live cost-ledger export (CSV/XLSX)
- Firm form library

## Acceptance bars

- ≥3 frontier proposals on the stacked Lavon instruments accepted by bond counsel + MA + PID admin and incorporated
- Capture mode: ≥95% bucket match against advisor-approved categorizations on the next packet, ≤20% rework, ≥1 missed-backup item caught
- Defensibility binder generated and reviewable by an outside diligence reader
