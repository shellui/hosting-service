"""Canonical JSON serialization for signed webhook bodies."""

from __future__ import annotations

import json
from typing import Any


def serialize_webhook_envelope(envelope: dict[str, Any]) -> bytes:
    """
    Compact UTF-8 JSON for signing and POST body.

    Uses ``ensure_ascii=False`` so Unicode in payloads is not escaped; verifiers must
    use the raw request body bytes (Standard Webhooks style).
    """
    return json.dumps(
        envelope,
        separators=(',', ':'),
        sort_keys=True,
        ensure_ascii=False,
    ).encode('utf-8')
