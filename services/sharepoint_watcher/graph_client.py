"""Microsoft Graph client for the contracts watcher.

Thin wrapper over msal (token) + httpx (REST) — avoids the msgraph-sdk
async-only surface that complicates a synchronous CLI.

Required env vars:
  MS_GRAPH_TENANT_ID
  MS_GRAPH_CLIENT_ID
  MS_GRAPH_CLIENT_SECRET
  MS_GRAPH_DEALS_DRIVE_ID

The drive ID is resolved once via the Graph API and stuck in env;
re-resolving on every run isn't worth the round-trip.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator

import httpx
import msal


GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _required(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(
            f"Missing required env var: {name}. "
            f"See .env.example for the full SharePoint integration set."
        )
    return v


def _acquire_token() -> str:
    tenant = _required("MS_GRAPH_TENANT_ID")
    client_id = _required("MS_GRAPH_CLIENT_ID")
    client_secret = _required("MS_GRAPH_CLIENT_SECRET")
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=f"https://login.microsoftonline.com/{tenant}",
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" not in result:
        err = result.get("error_description") or result.get("error") or str(result)
        raise RuntimeError(f"Graph token acquisition failed: {err}")
    return result["access_token"]


@dataclass
class GraphFile:
    item_id: str
    name: str
    web_url: str
    last_modified: datetime
    size_bytes: int
    download_url: str | None


class GraphClient:
    def __init__(self, *, drive_id: str | None = None) -> None:
        self.drive_id = drive_id or _required("MS_GRAPH_DEALS_DRIVE_ID")
        self._token = _acquire_token()
        self._client = httpx.Client(
            base_url=GRAPH_BASE,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=60.0,
        )

    def __enter__(self) -> "GraphClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self._client.close()

    def list_folder(self, folder_path: str) -> Iterator[GraphFile]:
        """Yield every file under a folder (recursive). `folder_path` is
        relative to the drive root, e.g. '/Deals/Lavon-Pilot/Contracts'.
        """
        path = folder_path.strip("/")
        url = f"/drives/{self.drive_id}/root:/{path}:/children"
        while url:
            r = self._client.get(url)
            r.raise_for_status()
            payload = r.json()
            for item in payload.get("value", []):
                if "folder" in item:
                    sub = f"{folder_path.rstrip('/')}/{item['name']}"
                    yield from self.list_folder(sub)
                    continue
                if "file" not in item:
                    continue
                yield GraphFile(
                    item_id=item["id"],
                    name=item["name"],
                    web_url=item.get("webUrl", ""),
                    last_modified=datetime.fromisoformat(
                        item["lastModifiedDateTime"].rstrip("Z") + "+00:00"
                    ),
                    size_bytes=int(item.get("size", 0)),
                    download_url=item.get("@microsoft.graph.downloadUrl"),
                )
            url = payload.get("@odata.nextLink")
            if url and url.startswith(GRAPH_BASE):
                url = url[len(GRAPH_BASE):]

    def post(self, path: str, json: dict[str, Any]) -> dict[str, Any]:
        r = self._client.post(path, json=json)
        r.raise_for_status()
        return r.json()

    def download(self, item: GraphFile, dest_path: str) -> int:
        if item.download_url:
            with httpx.stream("GET", item.download_url, timeout=120.0) as r:
                r.raise_for_status()
                size = 0
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
                        size += len(chunk)
                return size

        with self._client.stream(
            "GET", f"/drives/{self.drive_id}/items/{item.item_id}/content"
        ) as r:
            r.raise_for_status()
            size = 0
            with open(dest_path, "wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
                    size += len(chunk)
            return size
