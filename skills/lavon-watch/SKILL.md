---
name: lavon-watch
description: Use for any surveillance of the Lavon, TX pilot's political and entitlement risk landscape — City of Lavon council/P&Z, planner/staff changes, election filings, Collin County commissioners, TCEQ MUD docket, NTMWD board, Wylie ISD, Community ISD, TxDOT/NCTCOG corridor actions on Hwy 78 / FM 6 / Outer Loop. Hyper-local; not a regional radar. Triggered by `/lavon scan`, `/lavon digest`, `/lavon ask`.
---

# Lavon-Watch Skill

Hyper-local surveillance for the Lavon pilot. Three failure modes the firm has actually paid for: **council turnover during a deal**, **city planner / staff change**, **MUD creation / TCEQ timing**.

## Sources monitored

Bound in `configs/pilot_lavon.yml` under `signals.sources`. Each maps to a collector under `services/signal_collectors/`:

| Source | Collector | Cadence |
|---|---|---|
| City of Lavon council + P&Z agendas/packets/minutes | `lavon_council`, `lavon_pz` | daily |
| Lavon planner / staff page + LinkedIn | `lavon_staff` | daily |
| Lavon city election filings + contributions | `lavon_elections` | daily during filing windows, weekly otherwise |
| Collin County commissioners' court | `collin_county` | daily |
| TCEQ MUD docket (filings, hearings, bond auths) | `tceq_docket` | daily |
| NTMWD board agendas + CCN actions | `ntmwd` | weekly |
| Wylie ISD + Community ISD | `wylie_isd`, `community_isd` | weekly |
| TxDOT / NCTCOG (Hwy 78, FM 6, Outer Loop) | `txdot`, `nctcog` | weekly |

## Sub-commands

### `/lavon scan`

Runs every collector that's due, dedupes by `dedupe_key`, scores each new signal:
- `impact_score 0..5` produced by Sonnet 4.6 with the pilot config + active instruments cached as prompt prefix
- writes rows to `signals` and `signal_pilot_links`
- if any `impact_score >= 4` lands, drops a Teams ping into the pilot channel

### `/lavon digest`

Builds the daily and weekly digests:
- daily: list of all new signals from the last 24h, ranked by impact, into `templates/digest/lavon_daily.docx`
- weekly: synthesis using Opus 4.7 — *"what changed about our political/entitlement posture this week?"* — into `templates/digest/lavon.docx`

Both write a `lavon_digests` row.

### `/lavon ask <question>`

Q&A over the corpus of `signals` rows + their `raw_payload`. Loads matched signals into context, answers with citations to `source_url`.

## Models

- **Sonnet 4.6** — default scoring + collector parsing
- **Opus 4.7** — weekly synthesis
- **Haiku 4.5** — source classification, dedupe, freshness routing

## Acceptance bars

- 60-day backtest: every council action, P&Z item, MUD filing, planner change, and corridor action affecting the pilot from the past 60 days surfaces with source links and impact scoring
- Forward: **zero** surprise events that the principal first hears from a third party
