"""Streamlit dashboard — Refinery night-shift console.

Three roles, one app:
  Principal  — live one-pager: capacity, dates, signals, open items.
  Analyst    — daily ops console: classification queue, unacked dates, miss-audit.
  Advisor    — proposal review portal: filter by advisor, sign off inline.

Theme baseline lives in .streamlit/config.toml; typography (Inter Tight +
IBM Plex Mono) and density tweaks are injected via the CSS block below.
"""
from __future__ import annotations

import dataclasses
import json
import threading
from datetime import date, datetime, timedelta
from typing import Any, Callable

import altair as alt
import pandas as pd
import streamlit as st

from services.common.config import pilot_config
from services.common.db import cursor


st.set_page_config(page_title="Penguin-Club", layout="wide", initial_sidebar_state="expanded")


# ---------------- Theme overrides ----------------

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

html, body, [class*="css"], .stApp, p, span, div, button, label {
    font-family: 'Inter Tight', system-ui, -apple-system, sans-serif !important;
    font-feature-settings: 'cv11', 'ss01';
    -webkit-font-smoothing: antialiased;
}

h1, h2, h3, h4, h5, h6 {
    font-family: 'Inter Tight', system-ui, sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
}

h1 { font-size: 1.5rem !important; }
h2 { font-size: 1.15rem !important; margin-top: 1.5rem !important; }
h3 { font-size: 1.0rem !important; }

[data-testid="stMetricValue"], [data-testid="stMetricDelta"] {
    font-family: 'IBM Plex Mono', 'JetBrains Mono', monospace !important;
    font-weight: 500 !important;
}

[data-testid="stMetricLabel"] {
    font-size: 0.72rem !important;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #7A8794 !important;
}

[data-testid="stMetricValue"] { font-size: 1.6rem !important; color: #E0E6ED; }

[data-testid="stDataFrame"] {
    font-family: 'IBM Plex Mono', monospace !important;
    font-size: 12.5px !important;
}

.stDataFrame table th { background-color: #131C24 !important; color: #7A8794 !important; }

.block-container { padding-top: 1.5rem !important; padding-bottom: 2rem !important; }

[data-testid="stSidebar"] { background-color: #0D1419 !important; }

.stExpander { border: 1px solid #1E2A33 !important; border-radius: 4px !important; }

.stButton > button {
    border: 1px solid #2D3F4D !important;
    background-color: transparent !important;
    color: #E0E6ED !important;
    font-weight: 500 !important;
    transition: border-color 120ms ease, background-color 120ms ease;
}

.stButton > button:hover {
    border-color: #4DA3FF !important;
    background-color: rgba(77,163,255,0.08) !important;
}

.pill {
    display: inline-block;
    padding: 1px 8px;
    border-radius: 3px;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}
.pill-critical { background: #E8C547; color: #0A1116; }
.pill-warn     { background: rgba(232,197,71,0.14); color: #E8C547; border: 1px solid rgba(232,197,71,0.4); }
.pill-info     { background: rgba(77,163,255,0.14); color: #4DA3FF; border: 1px solid rgba(77,163,255,0.4); }
.pill-ok       { background: rgba(98,196,140,0.14); color: #62C48C; border: 1px solid rgba(98,196,140,0.4); }
.pill-muted    { background: rgba(122,135,148,0.14); color: #7A8794; border: 1px solid rgba(122,135,148,0.3); }

.kv-row { display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid #1E2A33; }
.kv-key { color: #7A8794; font-size: 0.85rem; }
.kv-val { color: #E0E6ED; font-family: 'IBM Plex Mono', monospace; font-size: 0.85rem; }

.section-rule { height: 1px; background: #1E2A33; margin: 1rem 0 0.5rem 0; }

a { color: #4DA3FF !important; text-decoration: none !important; }
a:hover { text-decoration: underline !important; }
</style>
"""

st.markdown(CSS, unsafe_allow_html=True)


LIGHT_CSS = """
<style>
.stApp, .stApp > div { background-color: #FAFAFA !important; color: #1A1F26 !important; }
[data-testid="stSidebar"], [data-testid="stSidebar"] > div { background-color: #F0F2F5 !important; }
[data-testid="stSidebar"] *, .stApp p, .stApp span, .stApp div, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6 { color: #1A1F26 !important; }
[data-testid="stMetricValue"] { color: #1A1F26 !important; }
[data-testid="stMetricLabel"] { color: #6A737D !important; }
.stDataFrame table th { background-color: #E8ECF0 !important; color: #6A737D !important; }
.kv-key { color: #6A737D !important; }
.kv-val { color: #1A1F26 !important; }
.kv-row { border-bottom-color: #DBE0E6 !important; }
.section-rule { background: #DBE0E6 !important; }
.stExpander { border-color: #DBE0E6 !important; background: #FFFFFF !important; }
.stButton > button { border-color: #DBE0E6 !important; color: #1A1F26 !important; background: #FFFFFF !important; }
.stButton > button:hover { border-color: #2563EB !important; background: rgba(37,99,235,0.06) !important; }
.pill-warn   { background: rgba(184,84,26,0.1) !important; color: #B8541A !important; border: 1px solid rgba(184,84,26,0.4) !important; }
.pill-info   { background: rgba(37,99,235,0.08) !important; color: #2563EB !important; border: 1px solid rgba(37,99,235,0.3) !important; }
.pill-ok     { background: rgba(43,135,77,0.1) !important; color: #2B874D !important; border: 1px solid rgba(43,135,77,0.4) !important; }
.pill-muted  { background: rgba(106,115,125,0.08) !important; color: #6A737D !important; border: 1px solid rgba(106,115,125,0.3) !important; }
.pill-critical { background: #B8541A !important; color: #FFFFFF !important; }
a { color: #2563EB !important; }
</style>
"""


def pill(text: str, kind: str = "muted") -> str:
    return f'<span class="pill pill-{kind}">{text}</span>'


def impact_pill(score: int) -> str:
    if score >= 4:
        return pill(f"impact {score}", "warn")
    if score >= 2:
        return pill(f"impact {score}", "info")
    return pill(f"impact {score}", "muted")


def _result_to_jsonable(result: Any) -> Any:
    if dataclasses.is_dataclass(result):
        return dataclasses.asdict(result)
    if hasattr(result, "__dict__"):
        return {k: v for k, v in vars(result).items() if not k.startswith("_")}
    return result


class _AsyncJob:
    """Background-thread holder living in st.session_state.
    `done` is a threading.Event so the polling fragment can check
    completion without holding a lock."""

    def __init__(self, label: str, fn: Callable[..., Any], kwargs: dict[str, Any]) -> None:
        self.label = label
        self.started_at = datetime.utcnow()
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, args=(fn, kwargs), daemon=True)

    def _run(self, fn: Callable[..., Any], kwargs: dict[str, Any]) -> None:
        try:
            self.result = fn(**kwargs)
        except BaseException as e:
            self.error = e
        finally:
            self.done.set()

    def start(self) -> None:
        self._thread.start()


def _is_action_running() -> bool:
    job = st.session_state.get("async_job")
    return bool(job and not job.done.is_set())


def run_action_async(label: str, fn: Callable[..., Any], **kwargs: Any) -> None:
    """Render a button that launches `fn(**kwargs)` in a background thread.
    The render_async_status fragment polls every 3 seconds and surfaces
    completion. Only one action runs at a time — subsequent buttons
    disable while a job is in flight."""
    busy = _is_action_running()
    if st.button(
        label,
        key=f"action-{label}",
        disabled=busy,
        help="An action is already running" if busy else None,
    ):
        job = _AsyncJob(label, fn, kwargs)
        st.session_state["async_job"] = job
        job.start()
        st.rerun()


@st.fragment(run_every=3)
def render_async_status() -> None:
    """Polled status surface. Fragment scope — only this block re-runs
    on the timer, the rest of the page stays cached. On completion,
    we trigger a full app rerun to refresh every cached view."""
    job: _AsyncJob | None = st.session_state.get("async_job")
    if job is None:
        return

    if job.done.is_set():
        elapsed = (datetime.utcnow() - job.started_at).total_seconds()
        if job.error is not None:
            st.error(f"{job.label} failed after {elapsed:.0f}s: "
                     f"{type(job.error).__name__}: {job.error}")
        else:
            st.success(f"{job.label} complete · {elapsed:.0f}s")
            with st.expander("Result", expanded=False):
                payload = _result_to_jsonable(job.result)
                st.code(json.dumps(payload, indent=2, default=str), language="json")
        del st.session_state["async_job"]
        st.cache_data.clear()
        st.rerun(scope="app")
    else:
        elapsed = (datetime.utcnow() - job.started_at).total_seconds()
        st.markdown(
            f'<div style="border:1px solid #2D3F4D; border-left:3px solid #4DA3FF; '
            f'background:rgba(77,163,255,0.06); padding:10px 14px; border-radius:4px; '
            f'margin-bottom:0.5rem;">'
            f'<span style="font-weight:600;">⏳ {job.label}</span>'
            f'<span style="color:#7A8794; margin-left:8px; font-family:IBM Plex Mono, monospace; '
            f'font-size:0.78rem;">running · {elapsed:.0f}s</span>'
            f'<div style="color:#7A8794; font-size:0.82rem; margin-top:4px;">'
            f'Background thread. Other actions are disabled until this completes.'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


@st.cache_data(ttl=15)
def last_run_for_source(source: str) -> datetime | None:
    with cursor() as cur:
        cur.execute(
            """
            SELECT MAX(started_at) AS last_run
            FROM collector_runs
            WHERE source = %s::signal_source AND status = 'ok'
            """,
            (source,),
        )
        row = cur.fetchone()
    return row.get("last_run") if row else None


@st.cache_data(ttl=15)
def signals_last_24h(min_impact: int = 4) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, kind::text AS kind, source::text AS source, title, summary,
                   source_url, occurred_on, retrieved_at, impact_score, impact_rationale
            FROM signals
            WHERE retrieved_at >= NOW() - INTERVAL '24 hours'
              AND impact_score >= %s
            ORDER BY impact_score DESC, retrieved_at DESC
            """,
            (min_impact,),
        )
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=15)
def positions_added_last_24h(deal_id: str) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, family, title, estimated_dollars,
                   bond_counsel_view, municipal_advisor_view, pid_admin_view,
                   created_at
            FROM pf_positions
            WHERE deal_id = %s
              AND created_at >= NOW() - INTERVAL '24 hours'
              AND 'pending' IN (bond_counsel_view, municipal_advisor_view, pid_admin_view)
            ORDER BY estimated_dollars DESC NULLS LAST, created_at DESC
            """,
            (deal_id,),
        )
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=15)
def dates_acked_last_24h(deal_id: str) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.kind::text AS kind, d.label, d.value, d.human_acked_at,
                   c.title AS contract_title
            FROM dates d
            JOIN contracts c ON c.id = d.contract_id
            WHERE c.deal_id = %s
              AND d.human_acked = TRUE
              AND d.human_acked_at >= NOW() - INTERVAL '24 hours'
            ORDER BY d.human_acked_at DESC
            """,
            (deal_id,),
        )
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=60)
def signal_volume_14d() -> pd.DataFrame:
    with cursor() as cur:
        cur.execute(
            """
            SELECT date_trunc('day', retrieved_at)::date AS day,
                   COUNT(*) AS total,
                   SUM(CASE WHEN impact_score >= 4 THEN 1 ELSE 0 END) AS high_impact
            FROM signals
            WHERE retrieved_at >= NOW() - INTERVAL '14 days'
            GROUP BY 1
            ORDER BY 1 ASC
            """
        )
        rows = cur.fetchall()

    full_days = [
        (datetime.utcnow().date() - timedelta(days=k)) for k in range(13, -1, -1)
    ]
    by_day = {r["day"]: dict(r) for r in rows}
    return pd.DataFrame(
        [
            {
                "day": d,
                "total": int(by_day.get(d, {}).get("total", 0)),
                "high_impact": int(by_day.get(d, {}).get("high_impact", 0)),
            }
            for d in full_days
        ]
    )


@st.cache_data(ttl=15)
def latest_digest(cadence: str) -> dict[str, Any] | None:
    with cursor() as cur:
        cur.execute(
            """
            SELECT period_start, period_end, signal_count, high_impact_count,
                   digest_uri, sent_at
            FROM lavon_digests
            WHERE cadence = %s
            ORDER BY sent_at DESC NULLS LAST, period_end DESC
            LIMIT 1
            """,
            (cadence,),
        )
        row = cur.fetchone()
    return dict(row) if row else None


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
                   incorporated_into, risk_notes, proposal, created_at
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
              ) AS pending_lines,
              (SELECT COUNT(*) FROM ledger_classifications lc
                JOIN cost_ledger cl ON cl.id = lc.cost_ledger_id
                WHERE cl.deal_id = %s AND lc.advisor_review = 'pending') AS pending_review
            """,
            (deal_id, deal_id, deal_id),
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
def unacked_critical_dates(deal_id: str) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT d.id, d.kind::text AS kind, d.label, d.value, d.source_ref,
                   c.title AS contract_title, c.document_uri
            FROM dates d
            JOIN contracts c ON c.id = d.contract_id
            WHERE c.deal_id = %s
              AND d.is_critical = TRUE
              AND d.agreed = TRUE
              AND d.human_acked = FALSE
            ORDER BY d.value ASC NULLS LAST
            """,
            (deal_id,),
        )
        return [dict(r) for r in cur.fetchall()]


@st.cache_data(ttl=15)
def parse_failures(deal_id: str) -> list[dict[str, Any]]:
    with cursor() as cur:
        cur.execute(
            """
            SELECT id, title, document_uri, parse_status, parse_error, created_at
            FROM contracts
            WHERE deal_id = %s AND parse_status IN ('needs_human', 'failed')
            ORDER BY created_at DESC
            """,
            (deal_id,),
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


# ---------------- Sidebar ----------------

cfg = pilot_config()
deals = list_deals()
if not deals:
    st.title("Penguin-Club")
    st.warning(
        "No deals in the database yet. Run "
        "`python -m services.reimbursement_api seed` to load the pilot config."
    )
    st.stop()

slugs = [d["slug"] for d in deals]
default_idx = slugs.index(cfg["deal"]["slug"]) if cfg["deal"]["slug"] in slugs else 0

with st.sidebar:
    st.markdown("### PENGUIN — CLUB")
    st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)

    role = st.radio(
        "Role",
        ["Principal", "Analyst", "Advisor"],
        horizontal=True,
        label_visibility="collapsed",
    )
    st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)

    slug = st.selectbox("Deal", slugs, index=default_idx)
    deal = deal_by_slug(slug)
    st.markdown(
        f'<div class="kv-row"><span class="kv-key">jurisdiction</span>'
        f'<span class="kv-val">{deal["jurisdiction"]}</span></div>'
        f'<div class="kv-row"><span class="kv-key">county</span>'
        f'<span class="kv-val">{deal["county"]}, {deal["state"]}</span></div>'
        f'<div class="kv-row"><span class="kv-key">status</span>'
        f'<span class="kv-val">{deal["status"]}</span></div>',
        unsafe_allow_html=True,
    )

    if role == "Advisor":
        st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)
        advisor_role = st.radio(
            "As advisor",
            ["bond_counsel", "municipal_advisor", "pid_admin"],
        )

    st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)
    light_mode = st.toggle(
        "Light mode (presentation)",
        value=st.session_state.get("light_mode", False),
        key="light_mode",
        help="Flips the palette to Modern Minimal for screen-shares + projectors.",
    )
    st.caption("Cached views refresh every 15s.")

if light_mode:
    st.markdown(LIGHT_CSS, unsafe_allow_html=True)


# Render the async-status block once, near the top of the main column.
render_async_status()


# ---------------- Shared queries / pre-computes ----------------

inst_rows = instruments_for(deal["id"])
pos_rows = positions_for(deal["id"])
cls = classification_summary(deal["id"])
unacked_dates = unacked_critical_dates(deal["id"])
sig_rows = signals_recent()
high_impact_recent = [s for s in sig_rows if s["impact_score"] >= 4][:8]


def _capacity_total() -> float:
    return sum(float(i["capacity_remaining"] or 0) for i in inst_rows)


def _classified_total() -> float:
    return sum(float(i["classified_eligible"] or 0) for i in inst_rows)


# ---------------- Principal ----------------

if role == "Principal":
    st.markdown(f"# {deal['name']}")
    st.caption(f"Live one-pager · {datetime.utcnow():%Y-%m-%d %H:%M UTC}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Capacity remaining", f"${_capacity_total()/1_000_000:.2f}M")
    c2.metric("Classified (pend+app)", f"${_classified_total()/1_000_000:.2f}M")
    c3.metric("Pending classification", cls["pending_lines"])
    c4.metric("Unacked critical dates", len(unacked_dates))
    c5.metric("High-impact signals (recent)", len(high_impact_recent))

    sparkline_df = signal_volume_14d()
    if not sparkline_df.empty and sparkline_df["total"].sum() > 0:
        spark_grid = "#E8ECF0" if light_mode else "#1E2A33"
        spark_text = "#6A737D" if light_mode else "#7A8794"
        spark_bg = "#FFFFFF" if light_mode else "#0A1116"
        spark_total_color = "#2563EB" if light_mode else "#4DA3FF"
        spark_high_color = "#B8541A" if light_mode else "#E8C547"

        spark_long = sparkline_df.melt(
            id_vars=["day"],
            value_vars=["total", "high_impact"],
            var_name="series",
            value_name="count",
        )
        spark = (
            alt.Chart(spark_long)
            .mark_area(opacity=0.55, line=True)
            .encode(
                x=alt.X(
                    "day:T",
                    axis=alt.Axis(
                        labelColor=spark_text, format="%b %d",
                        title=None, grid=False, ticks=False,
                    ),
                ),
                y=alt.Y(
                    "count:Q",
                    axis=alt.Axis(
                        labelColor=spark_text, title="signals",
                        titleColor=spark_text, grid=True, gridColor=spark_grid,
                    ),
                    stack=None,
                ),
                color=alt.Color(
                    "series:N",
                    scale=alt.Scale(
                        domain=["total", "high_impact"],
                        range=[spark_total_color, spark_high_color],
                    ),
                    legend=alt.Legend(orient="top", title=None,
                                      labelColor=spark_text),
                ),
                tooltip=["day:T", "series:N", "count:Q"],
            )
            .properties(height=110)
            .configure_view(stroke=None, fill=spark_bg)
            .configure_axis(domainColor=spark_grid, tickColor=spark_grid)
        )
        st.altair_chart(spark, use_container_width=True)

    st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)

    open_pos = [
        p for p in pos_rows
        if "pending" in (p["bond_counsel_view"], p["municipal_advisor_view"], p["pid_admin_view"])
    ]
    upcoming = upcoming_dates(deal["id"], horizon_days=60)
    critical_only = [r for r in upcoming if r["is_critical"]]
    open_pos_high_value = sorted(
        open_pos, key=lambda p: float(p.get("estimated_dollars") or 0), reverse=True
    )[:3]

    new_signals_24h = signals_last_24h(min_impact=4)
    new_positions_24h = positions_added_last_24h(deal["id"])
    acked_24h = dates_acked_last_24h(deal["id"])

    needs_items: list[str] = []
    if unacked_dates:
        next_unacked = unacked_dates[0]
        needs_items.append(
            f'{pill("ACK", "critical")} '
            f'<b>{next_unacked["value"]}</b> — {next_unacked["kind"]} on '
            f'{next_unacked["contract_title"]} is agreed but unacked.'
        )
    for p in open_pos_high_value:
        d = float(p.get("estimated_dollars") or 0)
        needs_items.append(
            f'{pill("SIGNOFF", "info")} '
            f'<b>${d/1_000_000:.2f}M</b> — {p["title"]} '
            f'<span style="color:#7A8794;">awaiting advisor view</span>'
        )
    for s in high_impact_recent[:2]:
        needs_items.append(
            f'{impact_pill(s["impact_score"])} '
            f'<span style="color:#7A8794;">{s["source"]}</span> {s["title"]}'
        )

    diff_items: list[str] = []
    for s in new_signals_24h[:3]:
        diff_items.append(
            f'{impact_pill(s["impact_score"])} '
            f'<span style="color:#7A8794;">{s["source"]}</span> {s["title"]}'
        )
    for p in new_positions_24h[:3]:
        d = float(p.get("estimated_dollars") or 0)
        diff_items.append(
            f'{pill("NEW", "info")} '
            f'<b>${d/1_000_000:.2f}M</b> — {p["title"]} '
            f'<span style="color:#7A8794;">awaiting advisor view</span>'
        )
    for d_row in acked_24h[:3]:
        diff_items.append(
            f'{pill("ACKED", "ok")} '
            f'<b>{d_row["value"]}</b> — {d_row["kind"]} on '
            f'{d_row["contract_title"]} '
            f'<span style="color:#7A8794;">marked acknowledged</span>'
        )

    panel_l, panel_r = st.columns(2)

    with panel_l:
        st.markdown("## What needs you")
        if needs_items:
            st.markdown(
                "<div style='border:1px solid #2D3F4D; border-left:3px solid #E8C547; "
                "background:rgba(232,197,71,0.04); padding:14px 16px; border-radius:4px;'>"
                "<div style='line-height:2.0;'>"
                + "<br>".join(needs_items)
                + "</div></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                pill("ALL CLEAR", "ok") + " no open action items.",
                unsafe_allow_html=True,
            )

    with panel_r:
        st.markdown("## Changed in last 24h")
        if diff_items:
            st.markdown(
                "<div style='border:1px solid #2D3F4D; border-left:3px solid #4DA3FF; "
                "background:rgba(77,163,255,0.04); padding:14px 16px; border-radius:4px;'>"
                "<div style='line-height:2.0;'>"
                + "<br>".join(diff_items)
                + "</div></div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                pill("QUIET", "muted") + " no new signals, positions, or acks since yesterday.",
                unsafe_allow_html=True,
            )

    st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)

    left, right = st.columns([3, 2])

    with left:
        st.markdown("## Capacity vs. classified")
        if inst_rows:
            chart_rows = []
            for i in inst_rows:
                chart_rows.append(
                    {
                        "instrument": i["kind"],
                        "series": "capacity",
                        "value": float(i["capacity_remaining"] or 0),
                    }
                )
                chart_rows.append(
                    {
                        "instrument": i["kind"],
                        "series": "classified",
                        "value": float(i["classified_eligible"] or 0),
                    }
                )
            chart_df = pd.DataFrame(chart_rows)
            chart_text = "#6A737D" if light_mode else "#7A8794"
            chart_grid = "#E8ECF0" if light_mode else "#1E2A33"
            chart_bg = "#FFFFFF" if light_mode else "#0A1116"
            chart_legend = "#1A1F26" if light_mode else "#A8B2BC"
            cap_bar = "#CBD5DD" if light_mode else "#2D3F4D"
            classified_bar = "#2563EB" if light_mode else "#4DA3FF"
            chart = (
                alt.Chart(chart_df)
                .mark_bar()
                .encode(
                    x=alt.X(
                        "instrument:N",
                        axis=alt.Axis(
                            labelAngle=0, labelColor=chart_text, title=None,
                        ),
                    ),
                    xOffset=alt.XOffset("series:N"),
                    y=alt.Y(
                        "value:Q",
                        axis=alt.Axis(
                            format="$,.2s",
                            labelColor=chart_text,
                            titleColor=chart_text,
                            title="USD",
                            grid=True,
                            gridColor=chart_grid,
                        ),
                    ),
                    color=alt.Color(
                        "series:N",
                        scale=alt.Scale(
                            domain=["capacity", "classified"],
                            range=[cap_bar, classified_bar],
                        ),
                        legend=alt.Legend(
                            orient="top", labelColor=chart_legend,
                            titleColor=chart_text, title=None,
                        ),
                    ),
                    tooltip=["instrument", "series", alt.Tooltip("value:Q", format="$,.0f")],
                )
                .properties(height=220)
                .configure_view(stroke=None, fill=chart_bg)
                .configure_axis(domainColor=chart_grid, tickColor=chart_grid)
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.markdown(pill("NO INSTRUMENTS", "muted"), unsafe_allow_html=True)

        st.markdown("## Open structuring proposals")
        if not open_pos:
            st.markdown(
                pill("ALL CLEAR", "ok") + " every position has all three advisor views recorded.",
                unsafe_allow_html=True,
            )
        else:
            df = pd.DataFrame(
                [
                    {
                        "$": float(p["estimated_dollars"] or 0),
                        "family": p["family"],
                        "title": p["title"],
                        "BC": p["bond_counsel_view"],
                        "MA": p["municipal_advisor_view"],
                        "PA": p["pid_admin_view"],
                    }
                    for p in open_pos
                ]
            )
            df["$"] = df["$"].map(lambda v: f"${v:,.0f}")
            st.dataframe(df, use_container_width=True, hide_index=True, height=300)

        st.markdown("## Upcoming critical dates")
        if not critical_only:
            st.markdown(
                pill("NONE", "muted") + " no critical dates in the next 60 days.",
                unsafe_allow_html=True,
            )
        else:
            df = pd.DataFrame(
                [
                    {
                        "date": str(r["value"]),
                        "kind": r["kind"],
                        "label": r["label"],
                        "agreed": "✓" if r["agreed"] else "—",
                        "acked": "✓" if r["human_acked"] else "—",
                        "contract": r["contract_title"],
                    }
                    for r in critical_only
                ]
            )
            st.dataframe(df, use_container_width=True, hide_index=True, height=240)

    with right:
        st.markdown("## High-impact signals")
        if not high_impact_recent:
            st.markdown(
                pill("QUIET", "muted") + " nothing scored 4+ in the recent window.",
                unsafe_allow_html=True,
            )
        else:
            for s in high_impact_recent:
                st.markdown(
                    f'<div style="margin-bottom:0.7rem; padding:0.6rem 0.7rem; '
                    f'background:#0F1820; border:1px solid #1E2A33; border-radius:4px;">'
                    f'<div style="display:flex; justify-content:space-between; align-items:center;">'
                    f'  {impact_pill(s["impact_score"])} '
                    f'  <span style="color:#7A8794; font-size:0.74rem; font-family:IBM Plex Mono, monospace;">'
                    f'    {s["source"]} · {s["occurred_on"] or "n/a"}'
                    f'  </span>'
                    f'</div>'
                    f'<div style="font-weight:500; margin-top:6px;">{s["title"]}</div>'
                    f'<div style="color:#A8B2BC; font-size:0.85rem; margin-top:4px;">'
                    f'  {(s["summary"] or "")[:180]}'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        st.markdown("## Per-instrument detail")
        if inst_rows:
            for i in inst_rows:
                cap = float(i["capacity_remaining"] or 0)
                cl = float(i["classified_eligible"] or 0)
                pct = (cl / cap * 100.0) if cap > 0 else 0.0
                bar_pct = min(pct, 100)
                st.markdown(
                    f'<div style="margin-bottom:0.6rem;">'
                    f'  <div class="kv-row" style="border:none; padding-bottom:2px;">'
                    f'    <span class="kv-key">{i["kind"]} · {i["name"]}</span>'
                    f'    <span class="kv-val">${cap/1_000_000:.2f}M · {pct:.0f}%</span>'
                    f'  </div>'
                    f'  <div style="height:4px; background:#1E2A33; border-radius:2px; overflow:hidden;">'
                    f'    <div style="width:{bar_pct}%; height:100%; background:#4DA3FF;"></div>'
                    f'  </div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )


# ---------------- Analyst ----------------

elif role == "Analyst":
    st.markdown(f"# {deal['name']} — ops console")
    st.caption(f"Analyst surface · {datetime.utcnow():%Y-%m-%d %H:%M UTC}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pending classification", cls["pending_lines"])
    c2.metric("Pending advisor review", cls["pending_review"])
    c3.metric("Unacked critical dates", len(unacked_dates))
    pf = parse_failures(deal["id"])
    c4.metric("Parse failures", len(pf))

    st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)

    queues, actions = st.columns([3, 2])

    with queues:
        st.markdown("## Unacked critical dates")
        if not unacked_dates:
            st.markdown(pill("CLEAR", "ok"), unsafe_allow_html=True)
        else:
            for r in unacked_dates:
                with st.container(border=True):
                    cols = st.columns([1, 4, 1])
                    cols[0].markdown(
                        f'<span class="pill pill-critical">{str(r["value"])}</span>',
                        unsafe_allow_html=True,
                    )
                    cols[1].markdown(
                        f"**{r['kind']}** — {r['label']}<br>"
                        f"<span style='color:#7A8794; font-size:0.82rem;'>"
                        f"{r['contract_title']} · {r.get('source_ref') or '(no ref)'}</span>",
                        unsafe_allow_html=True,
                    )
                    if cols[2].button("Ack", key=f"ack-{r['id']}"):
                        with cursor() as cur:
                            cur.execute(
                                "UPDATE dates SET human_acked = TRUE, "
                                "human_acked_at = NOW(), updated_at = NOW() "
                                "WHERE id = %s",
                                (r["id"],),
                            )
                        st.cache_data.clear()
                        st.rerun()

        st.markdown("## Parse failures")
        if not pf:
            st.markdown(pill("CLEAR", "ok"), unsafe_allow_html=True)
        else:
            df = pd.DataFrame(pf)[["title", "parse_status", "parse_error", "document_uri", "created_at"]]
            st.dataframe(df, use_container_width=True, hide_index=True, height=240)

        st.markdown("## Weekly miss-audit history")
        audit_rows = weekly_audit_state()
        if audit_rows:
            df = pd.DataFrame(audit_rows)
            st.dataframe(df, use_container_width=True, hide_index=True, height=240)
        else:
            st.markdown(pill("NONE", "muted") + " no miss-audit runs yet.", unsafe_allow_html=True)

    with actions:
        st.markdown("## Recent signals")
        if not sig_rows:
            st.markdown(pill("EMPTY", "muted") + " no signals ingested.", unsafe_allow_html=True)
        else:
            df = pd.DataFrame(sig_rows[:30])[
                ["impact_score", "kind", "source", "title", "occurred_on", "source_url"]
            ]
            df.columns = ["impact", "kind", "source", "title", "date", "url"]
            st.dataframe(df, use_container_width=True, hide_index=True, height=380)

        st.markdown("## Quick actions")
        st.caption(
            "Each runs synchronously and refreshes the page on completion. "
            "Long-running jobs (classify, scan) lock the UI until they return."
        )

        max_lines = st.number_input(
            "classify — max lines",
            min_value=1, max_value=10000, value=200, step=50,
            help="Cap on cost-ledger lines processed in this run.",
        )
        from services.reimbursement_api.classify import run_classify

        run_action_async("Run classifier", run_classify, max_lines=int(max_lines))

        force_scan = st.toggle("scan — ignore cadence (force)", value=False)
        from services.signal_collectors.schedule import run_schedule

        run_action_async("Run signal scan", run_schedule, force=force_scan)

        from services.sharepoint_watcher.weekly_audit import run_weekly_audit

        run_action_async("Run weekly miss-audit", run_weekly_audit)

        from services.signal_collectors.digest import render_daily

        def _daily_now() -> Any:
            now = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            return render_daily(period_start=now, period_end=now + timedelta(days=1))

        run_action_async("Render daily digest", _daily_now)

        from services.sharepoint_watcher.calendar_push import push_calendar

        run_action_async("Push to Outlook calendar", push_calendar, force=False)

        last_scan = last_run_for_source("lavon_council")
        last_daily = latest_digest("daily")
        last_weekly = latest_digest("weekly")
        st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)
        st.markdown(
            "<div style='font-size:0.78rem; color:#7A8794; line-height:1.7;'>"
            f"<b>last lavon_council scan:</b> {last_scan or '(never)'}<br>"
            f"<b>last daily digest:</b> "
            f"{(last_daily or {}).get('sent_at') or '(never)'} "
            f"({(last_daily or {}).get('signal_count', 0)} signals)<br>"
            f"<b>last weekly digest:</b> "
            f"{(last_weekly or {}).get('sent_at') or '(never)'} "
            f"({(last_weekly or {}).get('signal_count', 0)} signals)"
            "</div>",
            unsafe_allow_html=True,
        )

    st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)

    st.markdown("## Takedown schedules")
    td_rows = takedown_for(deal["id"])
    if td_rows:
        df = pd.DataFrame(td_rows)[
            ["builder", "builder_tier", "section",
             "lot_count", "base_lot_price", "escalator_pct",
             "velocity_per_qtr", "first_takedown_on", "last_takedown_on"]
        ]
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.markdown(pill("NONE", "muted"), unsafe_allow_html=True)


# ---------------- Advisor ----------------

else:
    advisor_label = {
        "bond_counsel": "Bond counsel",
        "municipal_advisor": "Municipal advisor",
        "pid_admin": "PID administrator",
    }[advisor_role]
    view_col = {
        "bond_counsel": "bond_counsel_view",
        "municipal_advisor": "municipal_advisor_view",
        "pid_admin": "pid_admin_view",
    }[advisor_role]
    notes_col = view_col.replace("_view", "_notes")

    st.markdown(f"# Review portal — {advisor_label}")
    st.caption(f"{deal['name']} · {datetime.utcnow():%Y-%m-%d %H:%M UTC}")

    pending = [p for p in pos_rows if p[view_col] == "pending"]
    accepted = [p for p in pos_rows if p[view_col] == "accepted"]
    declined = [p for p in pos_rows if p[view_col] in ("declined", "hedged")]

    c1, c2, c3 = st.columns(3)
    c1.metric("Pending your review", len(pending))
    c2.metric("Accepted", len(accepted))
    c3.metric("Hedged or declined", len(declined))

    st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)

    if not pending:
        st.markdown(pill("INBOX EMPTY", "ok") + " every proposal has your view recorded.", unsafe_allow_html=True)
    else:
        st.markdown(f"## Awaiting your view — {len(pending)}")
        for p in pending:
            with st.container(border=True):
                top = st.columns([3, 1])
                top[0].markdown(
                    f"**{p['title']}**  {pill(p['family'], 'info')}",
                    unsafe_allow_html=True,
                )
                top[1].markdown(
                    f"<div style='text-align:right; font-family:IBM Plex Mono, monospace;'>"
                    f"${(p['estimated_dollars'] or 0)/1_000_000:.2f}M</div>",
                    unsafe_allow_html=True,
                )

                st.markdown(
                    f"<div style='color:#A8B2BC; font-size:0.9rem;'>"
                    f"{(p['proposal'] or '')[:600]}{'…' if len(p['proposal'] or '') > 600 else ''}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

                with st.expander("Risk & defensibility notes"):
                    st.write(p["risk_notes"] or "(none captured)")

                with st.form(key=f"adv-{p['id']}"):
                    decision = st.radio(
                        "Decision",
                        ["accepted", "hedged", "declined"],
                        horizontal=True,
                        key=f"d-{p['id']}",
                    )
                    notes = st.text_area("Notes", key=f"n-{p['id']}", height=80)
                    if st.form_submit_button("Record"):
                        with cursor() as cur:
                            cur.execute(
                                f"UPDATE pf_positions SET {view_col} = %s, "
                                f"{notes_col} = %s, updated_at = NOW() WHERE id = %s",
                                (decision, notes or None, p["id"]),
                            )
                        st.cache_data.clear()
                        st.success(f"Recorded {advisor_label}: {decision}")
                        st.rerun()

    if accepted:
        st.markdown('<div class="section-rule"></div>', unsafe_allow_html=True)
        st.markdown(f"## Your accepted positions — {len(accepted)}")
        df = pd.DataFrame(
            [
                {
                    "$": f"${(p['estimated_dollars'] or 0)/1_000_000:.2f}M",
                    "family": p["family"],
                    "title": p["title"],
                    "incorporated_into": p["incorporated_into"] or "(pending)",
                }
                for p in accepted
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)
