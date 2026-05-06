from __future__ import annotations

from anthropic import Anthropic

# Model IDs per the firm's standard rotation.
# Opus 4.7 — Structuring + critical-date verification
# Sonnet 4.6 — Capture classification + dates pass A + signal scoring
# Haiku 4.5 — cheap routing / triage
OPUS = "claude-opus-4-7"
SONNET = "claude-sonnet-4-6"
HAIKU = "claude-haiku-4-5-20251001"


def client() -> Anthropic:
    return Anthropic()
