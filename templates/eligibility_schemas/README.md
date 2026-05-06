# Eligibility Schemas

YAML is the version-controlled source of truth. The reimbursement service loads each `<instrument>.yml` into the `eligibility_rules` table, one row per `categories.*` entry.

`advisor_signoff` is the gate: until bond counsel / municipal advisor / PID administrator marks `accepted` (and the `eligibility_rules.advisor_signoff = TRUE` row exists), Capture mode treats the rule as **draft only** and surfaces flagged classifications for human review.

Frontier values (`eligible: TBD`) are Structuring-mode proposals — they generate `pf_positions` rows for advisor review and never auto-classify ledger lines.

```
categories:
  <bucket>:
    description: ...
    eligible: true|false|TBD
    advisor_signoff: pending|accepted|hedged|declined
    statute_ref: ...
    cap_pct: null            # optional cap, e.g. 5.0 for 5%
    notes: ...
```
