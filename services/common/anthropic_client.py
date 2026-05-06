from __future__ import annotations

from typing import Any

# Model IDs per the firm's standard rotation.
# Opus 4.7 — Structuring + critical-date verification
# Sonnet 4.6 — Capture classification + dates pass A + signal scoring
# Haiku 4.5 — cheap routing / triage
OPUS = "claude-opus-4-7"
SONNET = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5"


def client() -> Any:
    from anthropic import Anthropic

    return Anthropic()
