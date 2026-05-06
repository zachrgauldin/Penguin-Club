"""Query the firm negotiation memory.

Two surfaces:
  - filter_positions: structured SQL filter (doc_kind, tier, tag, outcome)
  - synthesize: Sonnet 4.6 synthesis over filtered positions, returning a
    grounded answer with citations to source_doc_uri + source_ref.

The corpus is small enough that we can put filtered rows directly in the
prompt instead of building a vector store. When the corpus grows past
a few hundred positions, swap in pg_trgm or pgvector retrieval here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.common.anthropic_client import SONNET, client
from services.common.db import cursor


SYSTEM_PROMPT = """You answer questions about a Texas land developer's negotiating positions, using ONLY the negotiated_positions corpus passed in the user message. Rules:

- Cite specific positions in [brackets] using their section_title + counterparty_tier (e.g. "[Earnest Money / national_public]"). After your answer, list the source_doc_uri for every cited row.
- If the firm's positions vary across counterparties or document kinds, surface the pattern: "We push for X with luxury builders, accept Y with national publics."
- Be tight. Two short paragraphs maximum, plus a citation list. If the corpus doesn't cover the question, say so plainly — don't infer.
- Outcomes matter: distinguish between positions the firm successfully held (`accepted`) versus those that landed at compromise or got rejected.
"""


@dataclass
class QueryResult:
    n_positions_consulted: int
    answer: str
    rows: list[dict[str, Any]]


def filter_positions(
    *,
    tag: str | None = None,
    section: str | None = None,
    counterparty_tier: str | None = None,
    doc_kind: str | None = None,
    outcome: str | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    where_clauses: list[str] = []
    params: list[Any] = []

    if tag:
        where_clauses.append("%s = ANY(tags)")
        params.append(tag)
    if section:
        where_clauses.append("section_title ILIKE %s")
        params.append(f"%{section}%")
    if counterparty_tier:
        where_clauses.append("counterparty_tier = %s")
        params.append(counterparty_tier)
    if doc_kind:
        where_clauses.append("doc_kind::text = %s")
        params.append(doc_kind)
    if outcome:
        where_clauses.append("final_outcome::text = %s")
        params.append(outcome)

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = f"""
        SELECT id, doc_kind::text AS doc_kind, counterparty, counterparty_tier,
               section_title, firm_position, counterparty_position,
               final_outcome::text AS final_outcome, final_text, rationale,
               source_doc_uri, source_ref, tags, confidence, created_at
        FROM negotiated_positions
        {where_sql}
        ORDER BY created_at DESC
        LIMIT %s
    """
    params.append(limit)
    with cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def _format_row(r: dict[str, Any]) -> str:
    tags = ", ".join(r["tags"]) or "(no tags)"
    return (
        f"[{r['section_title']} / {r['counterparty_tier'] or 'unknown'} / "
        f"{r['doc_kind']} / {r['final_outcome']}]\n"
        f"  counterparty: {r['counterparty']}\n"
        f"  source: {r['source_doc_uri']} ({r.get('source_ref') or 'n/a'})\n"
        f"  tags: {tags}\n"
        f"  firm_position: {r['firm_position']}\n"
        f"  counterparty_position: {r.get('counterparty_position') or '(not captured)'}\n"
        f"  final_text: {r.get('final_text') or '(not captured)'}\n"
        f"  rationale: {r.get('rationale') or '(not captured)'}"
    )


def synthesize(
    question: str,
    *,
    tag: str | None = None,
    section: str | None = None,
    counterparty_tier: str | None = None,
    doc_kind: str | None = None,
    outcome: str | None = None,
) -> QueryResult:
    rows = filter_positions(
        tag=tag,
        section=section,
        counterparty_tier=counterparty_tier,
        doc_kind=doc_kind,
        outcome=outcome,
    )

    if not rows:
        corpus_block = "(no matching negotiated_positions in the corpus)"
    else:
        corpus_block = "\n\n".join(_format_row(r) for r in rows)

    user_msg = (
        f"Question: {question}\n\n"
        f"[NEGOTIATION-MEMORY CORPUS]\n{corpus_block}"
    )

    a = client()
    response = a.messages.create(
        model=SONNET,
        max_tokens=2000,
        thinking={"type": "disabled"},
        system=[{"type": "text", "text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": user_msg}],
    )
    answer = next((b.text for b in response.content if b.type == "text"), "")

    return QueryResult(
        n_positions_consulted=len(rows),
        answer=answer,
        rows=rows,
    )
