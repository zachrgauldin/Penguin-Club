"""Q&A over the signals corpus.

Loads the most recent signals + any matching the operator's question into
context, asks Sonnet 4.6 with the pilot context cached as the system-prompt
prefix, and returns the answer with source citations to `source_url`.
"""
from __future__ import annotations

from typing import Any

from services.common.anthropic_client import SONNET, client
from services.common.db import cursor
from services.signal_collectors.pilot_context import load_pilot_context_text


SYSTEM_PROMPT = """You answer questions about the Lavon pilot's political and entitlement landscape using ONLY the signals corpus passed in the user message. Rules:

- Cite the exact signal title in [brackets] for every claim. If a claim has no supporting signal, do not make it.
- Include the source URL after the answer for any signal you cite.
- If the corpus is empty or doesn't cover the question, say so plainly. Do not infer beyond the signals.
- Be tight. Two short paragraphs maximum unless the question explicitly asks for a list.
"""


def _gather_corpus(*, query: str, limit: int = 60) -> list[dict[str, Any]]:
    """V1 corpus retrieval: most recent N signals + ILIKE on title/summary.

    Real semantic search is a Wave-2 deliverable; for now we lean on Sonnet
    being able to reason over a moderate batch of recent signals plus any
    keyword-matched ones. Postgres pg_trgm or pgvector come later.
    """
    like = f"%{query}%"
    sql = """
        WITH recent AS (
            SELECT id, kind::text, source::text, title, summary, source_url,
                   occurred_on, impact_score, impact_rationale
            FROM signals
            ORDER BY retrieved_at DESC
            LIMIT %s
        ),
        matched AS (
            SELECT id, kind::text, source::text, title, summary, source_url,
                   occurred_on, impact_score, impact_rationale
            FROM signals
            WHERE title ILIKE %s OR summary ILIKE %s OR impact_rationale ILIKE %s
            ORDER BY impact_score DESC, retrieved_at DESC
            LIMIT %s
        )
        SELECT * FROM recent
        UNION
        SELECT * FROM matched
    """
    with cursor() as cur:
        cur.execute(sql, (limit, like, like, like, limit))
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def ask(question: str) -> dict[str, Any]:
    ctx = load_pilot_context_text()
    corpus = _gather_corpus(query=question)

    if not corpus:
        corpus_block = "(signals corpus is empty)"
    else:
        corpus_block = "\n\n".join(
            f"[{r['title']}]\n"
            f"  kind={r['kind']} source={r['source']} occurred_on={r['occurred_on']} "
            f"impact={r['impact_score']}\n"
            f"  url: {r['source_url']}\n"
            f"  summary: {r['summary']}\n"
            f"  rationale: {r['impact_rationale']}"
            for r in corpus
        )

    user_msg = (
        f"Question: {question}\n\n"
        f"[SIGNALS CORPUS]\n{corpus_block}"
    )

    a = client()
    response = a.messages.create(
        model=SONNET,
        max_tokens=2000,
        thinking={"type": "disabled"},
        system=[
            {"type": "text", "text": SYSTEM_PROMPT},
            {"type": "text", "text": ctx["context_text"], "cache_control": {"type": "ephemeral"}},
        ],
        messages=[{"role": "user", "content": user_msg}],
    )
    answer = next((b.text for b in response.content if b.type == "text"), "")

    return {
        "question": question,
        "answer": answer,
        "n_signals_consulted": len(corpus),
    }
