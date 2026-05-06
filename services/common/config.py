from __future__ import annotations

import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PILOT_CONFIG = REPO_ROOT / "configs" / "pilot_lavon.yml"


try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def pilot_config(path: Path | str | None = None) -> dict[str, Any]:
    """Load and return the active pilot config (default: Lavon)."""
    import yaml

    target = Path(path) if path else Path(os.environ.get("PILOT_CONFIG", DEFAULT_PILOT_CONFIG))
    if not target.is_absolute():
        target = REPO_ROOT / target
    with target.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value
