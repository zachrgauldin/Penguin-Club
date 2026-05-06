"""SharePoint contracts watcher.

Reads `sharepoint.contracts_path` from the pilot config, walks the folder
recursively via Microsoft Graph, and runs the dual-extraction pipeline
on every file we haven't seen before.

V1 idempotency: a file is "already seen" when a `contracts` row exists
with the same `sharepoint_item_id`. To force re-extract on a metadata
change, pass `--force` (operator-driven) — the V2 cleanup is a content
hash that detects real edits vs. metadata bumps.

This is the production conduit Agent 3 was built for. Operator wires
to cron once M365 service-principal env vars are provisioned:
  */15 * * * *  python -m services.sharepoint_watcher watch
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.common.config import pilot_config
from services.common.db import cursor
from services.sharepoint_watcher.extraction import extract_contract
from services.sharepoint_watcher.graph_client import GraphClient, GraphFile
from services.sharepoint_watcher.persistence import persist_extraction


SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md"}


@dataclass
class WatchResult:
    deal_slug: str
    folder_path: str
    files_seen: int
    files_extracted: int
    files_skipped_existing: int
    files_skipped_unsupported: int
    files_failed: int
    contract_ids: list[str]
    errors: list[dict[str, Any]]


def _already_ingested(item_id: str) -> bool:
    with cursor() as cur:
        cur.execute(
            "SELECT 1 FROM contracts WHERE sharepoint_item_id = %s LIMIT 1",
            (item_id,),
        )
        return cur.fetchone() is not None


def watch_once(*, force: bool = False, kind_hint: str | None = None) -> WatchResult:
    cfg = pilot_config()
    sp = cfg.get("sharepoint") or {}
    folder = sp.get("contracts_path")
    if not folder:
        raise RuntimeError(
            "pilot config missing sharepoint.contracts_path; cannot run watcher."
        )
    deal_slug = cfg["deal"]["slug"]

    seen = extracted = skipped_existing = skipped_unsupported = failed = 0
    contract_ids: list[str] = []
    errors: list[dict[str, Any]] = []

    with GraphClient() as client:
        for f in client.list_folder(folder):
            seen += 1
            suffix = Path(f.name).suffix.lower()
            if suffix not in SUPPORTED_SUFFIXES:
                skipped_unsupported += 1
                continue
            if not force and _already_ingested(f.item_id):
                skipped_existing += 1
                continue

            tmpdir = tempfile.mkdtemp(prefix="penguin_sp_")
            tmp_path = Path(tmpdir) / f.name
            try:
                client.download(f, str(tmp_path))
                extraction = extract_contract(tmp_path, kind_hint=kind_hint)
                persisted = persist_extraction(
                    extraction=extraction,
                    document_uri=f.web_url or f"graph:{f.item_id}",
                    deal_slug=deal_slug,
                    sharepoint_item_id=f.item_id,
                )
                contract_ids.append(persisted.contract_id)
                extracted += 1
            except Exception as e:
                failed += 1
                errors.append({"name": f.name, "item_id": f.item_id, "error": str(e)})
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                    Path(tmpdir).rmdir()
                except OSError:
                    pass

    return WatchResult(
        deal_slug=deal_slug,
        folder_path=folder,
        files_seen=seen,
        files_extracted=extracted,
        files_skipped_existing=skipped_existing,
        files_skipped_unsupported=skipped_unsupported,
        files_failed=failed,
        contract_ids=contract_ids,
        errors=errors,
    )
