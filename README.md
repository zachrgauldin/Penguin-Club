# Penguin-Club

Internal automation platform for a Dallas-area MPC developer. Three Wave-1 agents bound to the **Lavon, TX** pilot deal:

1. **Reimbursement** (`skills/reimbursement`) — public-finance instrument co-author + cost-ledger classifier + packet generator. Stacks PID + MUD + TIRZ + 380/381 inside the Lavon pilot. Validated by bond counsel + municipal advisor + PID administrator.
2. **Contracts** (`skills/contracts`) — PSA / lot-purchase / takedown date and obligation tracker with **dual-extraction agreement** + weekly miss-audit. Missed dates are the firm's defined kill switch.
3. **Lavon-watch** (`skills/lavon-watch`) — hyper-local entitlement and political risk surveillance for the City of Lavon, Collin County, TCEQ MUD docket, NTMWD, Wylie/Community ISDs, TxDOT corridor actions, and election filings.

## Architecture rule

Firm-specific knowledge — eligibility rules, accepted PF positions, form templates, signal sources, jurisdiction config — lives in **`configs/`, `templates/`, and Postgres rows**, never hard-coded in agent prompt code. This is what keeps SaaS-spinout optionality cheap.

## Layout

```
skills/                Claude Code skills (analyst-driven)
services/              Anthropic SDK Python services (unattended jobs)
  reimbursement_api/   PF classifier + structuring engine
  sharepoint_watcher/  contract ingest + dual-extraction pipeline
  signal_collectors/   one collector per Lavon source
  chat_ui/             Streamlit internal UI
db/migrations/         Postgres schema (pf_core, contracts, signals)
db/seeds/              prior reimbursement packets, accepted positions, takedown actuals
templates/             Word/Excel forms; eligibility YAML
configs/               pilot bindings (pilot_lavon.yml)
Inbound/               drop zone for source docs (gitignored)
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
psql "$DATABASE_URL" -f db/migrations/001_pf_core.sql
psql "$DATABASE_URL" -f db/migrations/002_contracts.sql
psql "$DATABASE_URL" -f db/migrations/003_signals.sql
```

Required env vars (see `.env.example`):
- `ANTHROPIC_API_KEY`
- `DATABASE_URL`
- `MS_GRAPH_TENANT_ID` / `MS_GRAPH_CLIENT_ID` / `MS_GRAPH_CLIENT_SECRET`

## Strategy doc

Full plan: `/root/.claude/plans/i-m-a-land-developer-recursive-snail.md`.
