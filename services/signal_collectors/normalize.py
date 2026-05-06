"""Sonnet 4.6 normalizer: agenda/docket/board-minute text -> CandidateSignals.

Pilot context goes in the cached system-prompt prefix. The volatile per-call
content (the source URL + fetched document) sits after the cache breakpoint
so iterating on which URLs to ingest doesn't re-pay the prefix cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.common.anthropic_client import SONNET, client
from services.signal_collectors.fetcher import FetchedDocument
from services.signal_collectors.pilot_context import load_pilot_context_text
from services.signal_collectors.schemas import NormalizedScan, SignalSource


SYSTEM_PROMPT = """You are a hyper-local entitlement and political-risk watcher for a Lavon, TX MPC pilot. Your job is to read agendas, dockets, board minutes, election filings, and corridor announcements; pull out actionable signals; and score each by potential impact on the pilot.

Three failure modes the firm has actually paid for:
1. Council turnover during a deal — councilmembers replaced mid-deal who reverse a prior position.
2. City planner / staff change — the planner who shepherded an approval leaves and the replacement re-litigates.
3. MUD creation / TCEQ timing — TCEQ docket actions (filings, hearings, bond authorization) that move our reimbursement timing.

For every signal you extract:
- Source-link via the source URL the operator passed in. Do not invent URLs.
- Score impact_score 0–5 with explicit reference to the active deal and instruments below. Generic framings like "this could affect the deal" are not acceptable; tie the score to a specific instrument, capacity, or critical-path event.
- Populate `affected_instruments` only when the signal directly touches a specific PF instrument; leave empty for purely jurisdictional signals.
- Return an empty list if the source contains no actionable signals.

Be conservative on impact_score. 5 is reserved for direct critical-path events (council vote on our deal, TCEQ confirmation hearing, planner departure, election outcome that changes our council majority). 4 means it directly affects an active instrument. 0–2 is the broad informational floor.
"""


@dataclass
class NormalizeResult:
    scan: NormalizedScan
    cache_read_tokens: int
    cache_creation_tokens: int
    deal_id: str
    deal_slug: str
    instruments_by_kind: dict[str, dict[str, Any]]


def _build_system_blocks(pilot_text: str) -> list[dict[str, Any]]:
    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        {
            "type": "text",
            "text": pilot_text,
            "cache_control": {"type": "ephemeral"},
        },
    ]


def normalize_document(
    *,
    document: FetchedDocument,
    source: SignalSource,
) -> NormalizeResult:
    ctx = load_pilot_context_text()

    user_content: list[dict[str, Any]] = [
        document.content_block,
        {
            "type": "text",
            "text": (
                f"Source URL: {document.source_url}\n"
                f"Source label: {source}\n\n"
                f"Extract every actionable signal from the document above. "
                f"For each signal, set `kind` to the closest matching enum value. "
                f"If the document is an agenda, prefer one signal per agenda item. "
                f"Date all signals from the document where possible (occurred_on)."
            ),
        },
    ]

    a = client()
    response = a.messages.parse(
        model=SONNET,
        max_tokens=8000,
        thinking={"type": "disabled"},
        system=_build_system_blocks(ctx["context_text"]),
        messages=[{"role": "user", "content": user_content}],
        output_format=NormalizedScan,
    )
    scan: NormalizedScan = response.parsed_output
    if scan.source_url != document.source_url:
        scan = scan.model_copy(update={"source_url": document.source_url})

    return NormalizeResult(
        scan=scan,
        cache_read_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        deal_id=ctx["deal_id"],
        deal_slug=ctx["deal_slug"],
        instruments_by_kind=ctx["instruments_by_kind"],
    )
