"""Per-builder takedown forecast: cash-flow projection from takedown_schedules.

Quarter-by-quarter projection of velocity × escalated-price for each
schedule, segmented by builder_tier. Output: a Word doc with the by-tier
cash-flow table and a per-schedule breakdown, plus a JSON summary.

The forecast is deterministic — no LLM call. Source of truth is the
takedown_schedules rows the dual-extraction pipeline persisted; if the
operator disagrees with the projection, they edit the row in Postgres
and re-run.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from docx import Document
from docx.shared import Pt, RGBColor

from services.common.config import REPO_ROOT
from services.common.db import cursor


@dataclass
class QuarterProjection:
    quarter_label: str
    quarter_start: date
    lots: float
    revenue: float


@dataclass
class ScheduleForecast:
    schedule_id: str
    builder: str
    builder_tier: str | None
    section: str | None
    base_lot_price: float | None
    escalator_pct: float | None
    velocity_per_qtr: float | None
    quarters: list[QuarterProjection]
    total_lots: float
    total_revenue: float


@dataclass
class ForecastResult:
    deal_slug: str
    horizon_quarters: int
    schedules: list[ScheduleForecast]
    by_tier_totals: dict[str, dict[str, float]]
    word_path: str


def _quarter_starts(start: date, n: int) -> list[date]:
    out: list[date] = []
    cur = date(start.year, ((start.month - 1) // 3) * 3 + 1, 1)
    for i in range(n):
        out.append(cur)
        m = cur.month + 3
        y = cur.year
        if m > 12:
            m -= 12
            y += 1
        cur = date(y, m, 1)
    return out


def _quarter_label(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"{d.year} Q{q}"


def _project_schedule(
    *, schedule: dict[str, Any], horizon_quarters: int, today: date
) -> ScheduleForecast:
    velocity = float(schedule["velocity_per_qtr"] or 0.0)
    base = float(schedule["base_lot_price"] or 0.0)
    escalator = float(schedule["escalator_pct"] or 0.0)
    lot_count_remaining = (
        float(schedule["lot_count"]) if schedule["lot_count"] is not None else None
    )

    first = schedule["first_takedown_on"] or today
    last = schedule["last_takedown_on"]
    starts = _quarter_starts(first, horizon_quarters)
    if last is not None:
        starts = [s for s in starts if s <= last]

    quarters: list[QuarterProjection] = []
    total_lots = 0.0
    total_revenue = 0.0
    remaining = lot_count_remaining

    for k, qstart in enumerate(starts):
        if velocity <= 0 or base <= 0:
            quarters.append(
                QuarterProjection(
                    quarter_label=_quarter_label(qstart),
                    quarter_start=qstart,
                    lots=0.0,
                    revenue=0.0,
                )
            )
            continue

        lots_this_q = velocity
        if remaining is not None:
            if remaining <= 0:
                lots_this_q = 0.0
            else:
                lots_this_q = min(velocity, remaining)
                remaining -= lots_this_q

        price = base * ((1.0 + escalator) ** k)
        revenue = lots_this_q * price
        total_lots += lots_this_q
        total_revenue += revenue
        quarters.append(
            QuarterProjection(
                quarter_label=_quarter_label(qstart),
                quarter_start=qstart,
                lots=lots_this_q,
                revenue=revenue,
            )
        )

    return ScheduleForecast(
        schedule_id=schedule["id"],
        builder=schedule["builder"],
        builder_tier=schedule.get("builder_tier"),
        section=schedule.get("section"),
        base_lot_price=base or None,
        escalator_pct=escalator or None,
        velocity_per_qtr=velocity or None,
        quarters=quarters,
        total_lots=total_lots,
        total_revenue=total_revenue,
    )


def _gather_schedules(deal_slug: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with cursor() as cur:
        cur.execute(
            "SELECT id, slug, name FROM deals WHERE slug = %s",
            (deal_slug,),
        )
        deal = cur.fetchone()
        if deal is None:
            raise RuntimeError(f"Deal {deal_slug!r} not found.")
        deal = dict(deal)
        cur.execute(
            """
            SELECT id, deal_id, builder, builder_tier, section,
                   lot_count, base_lot_price, escalator_pct, escalator_basis,
                   option_fee, cadence, first_takedown_on, last_takedown_on,
                   velocity_per_qtr, default_triggers
            FROM takedown_schedules
            WHERE deal_id = %s
            ORDER BY first_takedown_on ASC NULLS LAST, builder ASC
            """,
            (deal["id"],),
        )
        rows = [dict(r) for r in cur.fetchall()]
    return deal, rows


def _build_word(
    *,
    deal: dict[str, Any],
    horizon_quarters: int,
    schedules: list[ScheduleForecast],
    by_tier: dict[str, dict[str, float]],
    out_dir: Path,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{deal['slug']}_takedown_forecast_{datetime.utcnow():%Y%m%d_%H%M}.docx"

    doc = Document()
    doc.add_heading(f"Takedown forecast — {deal['name']}", level=0)
    doc.add_paragraph(
        f"Generated: {datetime.utcnow():%Y-%m-%d %H:%M UTC}\n"
        f"Horizon: {horizon_quarters} quarters\n"
        f"Schedules: {len(schedules)}"
    )

    banner = doc.add_paragraph()
    run = banner.add_run(
        "Deterministic projection from takedown_schedules. Velocity × "
        "(base_lot_price × (1 + escalator)^k) per quarter, segmented by "
        "builder_tier. Re-run after updating the underlying schedule rows."
    )
    run.italic = True
    run.font.size = Pt(10)

    doc.add_heading("By tier — totals", level=1)
    if not by_tier:
        doc.add_paragraph("(no schedules)")
    else:
        table = doc.add_table(rows=1, cols=3)
        table.style = "Light List"
        h = table.rows[0].cells
        h[0].text = "Tier"
        h[1].text = "Total lots"
        h[2].text = "Total revenue"
        for tier, totals in sorted(by_tier.items()):
            r = table.add_row().cells
            r[0].text = tier
            r[1].text = f"{totals['lots']:,.0f}"
            r[2].text = f"${totals['revenue']:,.0f}"

    doc.add_heading("Per-schedule breakdown", level=1)
    if not schedules:
        doc.add_paragraph("(none)")
    else:
        for s in schedules:
            doc.add_heading(
                f"{s.builder} — {s.section or '(no section)'}", level=2
            )
            doc.add_paragraph(
                f"Tier: {s.builder_tier or 'unknown'}\n"
                f"Base lot price: ${(s.base_lot_price or 0):,.0f}\n"
                f"Escalator: {(s.escalator_pct or 0):.2%} per quarter index\n"
                f"Velocity: {s.velocity_per_qtr or 0:,.1f} lots/qtr\n"
                f"Total lots projected: {s.total_lots:,.0f}\n"
                f"Total revenue projected: ${s.total_revenue:,.0f}"
            )
            t = doc.add_table(rows=1, cols=3)
            t.style = "Light Grid"
            h = t.rows[0].cells
            h[0].text = "Quarter"
            h[1].text = "Lots"
            h[2].text = "Revenue"
            for q in s.quarters:
                row = t.add_row().cells
                row[0].text = q.quarter_label
                row[1].text = f"{q.lots:,.1f}"
                row[2].text = f"${q.revenue:,.0f}"

    doc.save(out_path)
    return out_path


def render_takedown_forecast(
    *,
    deal_slug: str,
    horizon_quarters: int = 16,
) -> ForecastResult:
    deal, raw_rows = _gather_schedules(deal_slug)
    today = datetime.utcnow().date()
    forecasts = [
        _project_schedule(schedule=r, horizon_quarters=horizon_quarters, today=today)
        for r in raw_rows
    ]

    by_tier: dict[str, dict[str, float]] = defaultdict(lambda: {"lots": 0.0, "revenue": 0.0})
    for f in forecasts:
        tier = f.builder_tier or "unknown"
        by_tier[tier]["lots"] += f.total_lots
        by_tier[tier]["revenue"] += f.total_revenue

    out_dir = REPO_ROOT / "templates" / "deliverables" / "takedown_forecasts"
    word_path = _build_word(
        deal=deal,
        horizon_quarters=horizon_quarters,
        schedules=forecasts,
        by_tier=dict(by_tier),
        out_dir=out_dir,
    )

    return ForecastResult(
        deal_slug=deal["slug"],
        horizon_quarters=horizon_quarters,
        schedules=forecasts,
        by_tier_totals=dict(by_tier),
        word_path=str(word_path),
    )
