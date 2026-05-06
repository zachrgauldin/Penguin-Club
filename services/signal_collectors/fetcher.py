"""Fetch a URL and prepare a content block for the normalizer.

PDFs are base64-encoded as a `document` block. HTML/text is returned as
a single text block. Per-source HTML cleanup belongs in a future
service/signal_collectors/sources/ module — for V1 the LLM reads the
raw HTML.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

USER_AGENT = "Penguin-Club Lavon-watch/0.1 (+internal)"


@dataclass
class FetchedDocument:
    source_url: str
    content_block: dict[str, Any]
    raw_bytes_len: int
    media_type: str


def fetch_url(url: str, *, timeout: float = 30.0) -> FetchedDocument:
    with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": USER_AGENT}) as cx:
        r = cx.get(url)
        r.raise_for_status()
    media_type = (r.headers.get("content-type") or "").split(";")[0].strip()
    body = r.content

    if media_type == "application/pdf" or url.lower().endswith(".pdf"):
        block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(body).decode("utf-8"),
            },
        }
        return FetchedDocument(
            source_url=url,
            content_block=block,
            raw_bytes_len=len(body),
            media_type="application/pdf",
        )

    text = r.text
    return FetchedDocument(
        source_url=url,
        content_block={"type": "text", "text": text},
        raw_bytes_len=len(body),
        media_type=media_type or "text/plain",
    )


def fetch_path(path: Path) -> FetchedDocument:
    suffix = path.suffix.lower()
    body = path.read_bytes()
    if suffix == ".pdf":
        block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.standard_b64encode(body).decode("utf-8"),
            },
        }
        return FetchedDocument(
            source_url=str(path),
            content_block=block,
            raw_bytes_len=len(body),
            media_type="application/pdf",
        )
    return FetchedDocument(
        source_url=str(path),
        content_block={"type": "text", "text": path.read_text(encoding="utf-8")},
        raw_bytes_len=len(body),
        media_type="text/plain",
    )
