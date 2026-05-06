"""Ingest orchestrator: fetch -> normalize -> persist.

Entry point for `/lavon ingest --url ... --source ...` and the
`scan-source` command. Per-source HTML scrapers and scheduled polling
are deferred — operator confirms a URL, ingests it, and the pipeline
runs end-to-end.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from services.signal_collectors.fetcher import fetch_path, fetch_url
from services.signal_collectors.normalize import normalize_document
from services.signal_collectors.persistence import PersistedScan, persist_scan
from services.signal_collectors.schemas import SignalSource


@dataclass
class IngestResult:
    source: str
    source_url: str
    n_candidates: int
    persisted: PersistedScan
    cache_read_tokens: int
    cache_creation_tokens: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_url": self.source_url,
            "n_candidates": self.n_candidates,
            "new_signals": self.persisted.new_signals,
            "duplicate_signals": self.persisted.duplicate_signals,
            "high_impact_signals": self.persisted.high_impact_signals,
            "collector_run_id": self.persisted.collector_run_id,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "persisted": [asdict(p) for p in self.persisted.persisted],
        }


def ingest_url(*, url: str, source: SignalSource) -> IngestResult:
    document = fetch_url(url)
    return _ingest_document(document=document, source=source)


def ingest_path(*, path: Path, source: SignalSource) -> IngestResult:
    document = fetch_path(path)
    return _ingest_document(document=document, source=source)


def _ingest_document(*, document, source: SignalSource) -> IngestResult:
    norm = normalize_document(document=document, source=source)
    persisted = persist_scan(source=source, result=norm)
    return IngestResult(
        source=source,
        source_url=norm.scan.source_url,
        n_candidates=len(norm.scan.candidates),
        persisted=persisted,
        cache_read_tokens=norm.cache_read_tokens,
        cache_creation_tokens=norm.cache_creation_tokens,
    )
