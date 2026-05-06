"""Streamlit dashboard for the three Wave-1 agents.

Run with: streamlit run services/chat_ui/app.py

Read-only against Postgres for the live state of the firm. Action
buttons (run classify, run digest, run weekly-audit) wrap the
service-side commands so an analyst doesn't need to leave the UI.
The principal's "live one-page deal dashboard" wish-list item maps to
the Reimbursement → Registry sub-tab.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import streamlit as st

from services.common.config import pilot_config
from services.common.db import cursor


st.set_page_config(page_title="Penguin-Club", layout="wide")


# ---------------- DB helpers (cached) ----------------

@st.cache_data(ttl=15)
def list_deals() -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute("SELECT id, slug, name, jurisdiction, county, status FROM deals ORDER BY name")
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=15)
def deal_by_slug(slug: str) -> dict[str, Any] | None:
    with cursor() as cur:
        cur.execute(
            "SELECT id, slug, name, jurisdiction, county, state, status, stage_notes "
            "FROM deals WHERE slug = %s",
            (slug,),
        )
        r = cur.fetchone()
        return dict(r) if r else None


@st.cache_data(ttl=15)
def instruments_for(deal_id: str) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, kind::text AS kind, name, status,
                   authorized_amount, issued_amount, capacity_remaining,
                   COALESCE(
                       (SELECT SUM(eligible_amount) FROM ledger_classifications lc
                        WHERE lc.instrument_id = i.id
                          AND lc.advisor_review IN ('pending','approved')),
                       0
                   ) AS classified_eligible
            FROM instruments i
            WHERE deal_id = %s
            ORDER BY kind
            """,
            (deal_id,),
        )
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=15)
def positions_for(deal_id: str) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, family, title, estimated_dollars,
                   bond_counsel_view, municipal_advisor_view, pid_admin_view,
                   incorporated_into, risk_notes, created_at
            FROM pf_positions
            WHERE deal_id = %s
            ORDER BY created_at DESC
            """,
            (deal_id,),
        )
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=15)
def reimbursements_for(deal_id: str) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT r.id, r.packet_number, r.status, r.requested_amount,
                   r.approved_amount, r.paid_amount, r.submitted_on, r.paid_on,
                   r.packet_uri, i.kind::text AS instrument_kind, i.name AS instrument_name
            FROM reimbursements r
            JOIN instruments i ON i.id = r.instrument_id
            WHERE i.deal_id = %s
            ORDER BY r.submitted_on DESC NULLS FIRST, r.packet_number DESC
            """,
            (deal_id,),
        )
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=15)
def classification_summary(deal_id: str) -> dict[str, Any]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM cost_ledger cl WHERE cl.deal_id = %s) AS total_lines,
              (SELECT COUNT(*) FROM cost_ledger cl
                WHERE cl.deal_id = %s
                  AND NOT EXISTS (SELECT 1 FROM ledger_classifications lc WHERE lc.cost_ledger_id = cl.id)
              ) AS pending_lines
            """,
            (deal_id, deal_id),
        )
        return dict(cur.fetchone())


@st.cache_data(ttl=15)
def upcoming_dates(deal_id: str, horizon_days: int = 60) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.kind::text AS kind, d.label, d.value, d.source_ref,
                   d.is_critical, d.agreed, d.human_acked, d.confidence,
                   c.title AS contract_title, c.kind::text AS contract_kind, c.document_uri
            FROM dates d
            JOIN contracts c ON c.id = d.contract_id
            WHERE c.deal_id = %s
              AND d.value IS NOT NULL
              AND d.value >= CURRENT_DATE
              AND d.value <= CURRENT_DATE + (%s || ' days')::interval
            ORDER BY d.value ASC, d.is_critical DESC
            """,
            (deal_id, horizon_days),
        )
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=15)
def weekly_audit_state() -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT week_starting, flagged_count, low_confidence_count,
                   unparseable_count, digest_uri, principal_acked, principal_acked_at
            FROM miss_audits
            ORDER BY week_starting DESC
            LIMIT 8
            """
        )
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=15)
def takedown_for(deal_id: str) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, builder, builder_tier, section,
                   lot_count, base_lot_price, escalator_pct, velocity_per_qtr,
                   first_takedown_on, last_takedown_on
            FROM takedown_schedules
            WHERE deal_id = %s
            ORDER BY first_takedown_on ASC NULLS LAST, builder ASC
            """,
            (deal_id,),
        )
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=15)
def signals_recent(limit: int = 200) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT s.id, s.kind::text AS kind, s.source::text AS source,
                   s.title, s.summary, s.source_url, s.occurred_on,
                   s.retrieved_at, s.impact_score, s.impact_rationale
            FROM signals s
            ORDER BY s.retrieved_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=15)
def digests_recent() -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT cadence, period_start, period_end, signal_count,
                   high_impact_count, digest_uri, sent_at
            FROM lavon_digests
            ORDER BY sent_at DESC NULLS LAST, period_end DESC
            LIMIT 12
            """
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------- Layout ----------------

cfg = pilot_config()
st.title("Penguin-Club")

deals = list_deals()
if not deals:
    st.warning(
        "No deals in the database yet. Run "
        "`python -m services.reimbursement_api seed` to load the pilot config."
    )
    st.stop()

slugs = [d["slug"] for d in deals]
default_idx = slugs.index(cfg["deal"]["slug"]) if cfg["deal"]["slug"] in slugs else 0

with st.sidebar:
    st.subheader("Deal")
    slug = st.selectbox("Deal", slugs, index=default_idx, label_visibility="collapsed")
    deal = deal_by_slug(slug)
    st.caption(
        f"{deal['jurisdiction']}, {deal['county']} County, {deal['state']}\n\n"
        f"Status: {deal['status']}"
    )
    st.divider()
    st.caption("Cached views auto-refresh every 15s. Use the menu (⋮ → Rerun) to force.")

tabs = st.tabs(["Reimbursement", "Contracts", "Lavon-watch"])

# ---------------- Reimbursement ----------------

with tabs[0]:
    inst_rows = instruments_for(deal["id"])
    pos_rows = positions_for(deal["id"])
    reim_rows = reimbursements_for(deal["id"])
    cls = classification_summary(deal["id"])

    st.subheader("Registry — capacity")
    if inst_rows:
        df = pd.DataFrame(inst_rows)[
            ["kind", "name", "status",
             "authorized_amount", "issued_amount",
             "capacity_remaining", "classified_eligible"]
        ]
        df.columns = ["kind", "name", "status",
                      "authorized", "issued", "capacity remaining", "classified (pend+app)"]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No instruments — run `seed`.")

    col1, col2 = st.columns(2)
    col1.metric("Cost-ledger lines", cls["total_lines"])
    col2.metric("Pending classification", cls["pending_lines"])

    st.subheader("Open structuring proposals")
    open_pos = [
        p for p in pos_rows
        if "pending" in (
            p["bond_counsel_view"], p["municipal_advisor_view"], p["pid_admin_view"]
        )
    ]
    if not open_pos:
        st.success("Every position has all three advisor views recorded.")
    else:
        for p in open_pos[:20]:
            with st.expander(
                f"[{p['family']}] {p['title']} — "
                f"${(p['estimated_dollars'] or 0):,.0f}"
            ):
                st.write(
                    f"**Bond counsel:** {p['bond_counsel_view']}  "
                    f"**Municipal advisor:** {p['municipal_advisor_view']}  "
                    f"**PID admin:** {p['pid_admin_view']}"
                )
                if p["incorporated_into"]:
                    st.caption(f"Incorporated into: {p['incorporated_into']}")
                if p["risk_notes"]:
                    st.markdown("**Risk notes:** " + p["risk_notes"])

    st.subheader("Packet history")
    if reim_rows:
        df = pd.DataFrame(reim_rows)[
            ["instrument_kind", "packet_number", "status",
             "requested_amount", "approved_amount", "paid_amount",
             "submitted_on", "paid_on", "packet_uri"]
        ]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No packets generated yet. Run `package` once classifications are in.")

# ---------------- Contracts ----------------

with tabs[1]:
    st.subheader("Critical dates — next 60 days")
    horizon = st.slider("Days ahead", min_value=14, max_value=180, value=60, step=14)
    dates_rows = upcoming_dates(deal["id"], horizon_days=horizon)
    if not dates_rows:
        st.success(f"No agreed dates in the next {horizon} days — backfill more contracts or extend the horizon.")
    else:
        for r in dates_rows:
            critical = "🔴" if r["is_critical"] else "•"
            acked = "✅" if r["human_acked"] else "⚠️ unacked"
            agreed = "✅" if r["agreed"] else "⚠️ not agreed"
            with st.expander(
                f"{critical} {r['value']} — {r['kind']} — {r['label']}  ({acked} / {agreed})"
            ):
                st.markdown(
                    f"- **Contract:** {r['contract_title']} ({r['contract_kind']})\n"
                    f"- **Source:** {r.get('source_ref') or '(none)'}\n"
                    f"- **Document:** {r['document_uri']}\n"
                    f"- **Confidence:** {r.get('confidence') or 'n/a'}"
                )

    st.subheader("Takedown schedules")
    td_rows = takedown_for(deal["id"])
    if td_rows:
        df = pd.DataFrame(td_rows)[
            ["builder", "builder_tier", "section",
             "lot_count", "base_lot_price", "escalator_pct",
             "velocity_per_qtr", "first_takedown_on", "last_takedown_on"]
        ]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No takedown schedules — extract a builder lot purchase or takedown agreement to populate.")

    st.subheader("Weekly miss-audit history")
    audit_rows = weekly_audit_state()
    if audit_rows:
        df = pd.DataFrame(audit_rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No weekly miss-audits yet. Run `python -m services.sharepoint_watcher weekly-audit`.")

# ---------------- Lavon-watch ----------------

with tabs[2]:
    sig_rows = signals_recent()
    digest_rows = digests_recent()

    st.subheader("Recent signals")
    if not sig_rows:
        st.info("No signals ingested yet. Run `python -m services.signal_collectors ingest --url ... --source ...`.")
    else:
        min_impact = st.slider("Minimum impact score", 0, 5, 0)
        filtered = [s for s in sig_rows if s["impact_score"] >= min_impact]
        if not filtered:
            st.caption(f"No signals at impact ≥ {min_impact}.")
        else:
            df = pd.DataFrame(filtered)[
                ["impact_score", "kind", "source", "title",
                 "occurred_on", "retrieved_at", "source_url"]
            ]
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.caption("Click a signal title in `signals` to drill down.")
            for s in filtered[:15]:
                if s["impact_score"] >= 4:
                    with st.expander(f"[{s['impact_score']}] {s['title']}"):
                        st.markdown(
                            f"- **Source:** {s['source']}\n"
                            f"- **Kind:** {s['kind']}\n"
                            f"- **Occurred:** {s['occurred_on']}\n"
                            f"- **URL:** {s['source_url']}\n\n"
                            f"{s['summary']}\n\n"
                            f"**Impact rationale:** {s['impact_rationale']}"
                        )

    st.subheader("Digest history")
    if digest_rows:
        df = pd.DataFrame(digest_rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No digests rendered yet.")

    st.subheader("Ask")
    question = st.text_input(
        "Ask a question against the signals corpus",
        placeholder="e.g. What's the council's posture on our MUD?",
    )
    if st.button("Ask") and question.strip():
        with st.spinner("Sonnet 4.6 reading the corpus..."):
            from services.signal_collectors.ask import ask as run_ask

            result = run_ask(question.strip())
        st.success(result["answer"])
        st.caption(f"Consulted {result['n_signals_consulted']} signals from the corpus.")
