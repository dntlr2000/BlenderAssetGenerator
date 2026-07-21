from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel


def canonical_json_sha256(value: Any) -> str:
    """Hash JSON-compatible data with stable key ordering and separators."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_model_sha256(value: BaseModel) -> str:
    """Hash a validated Pydantic contract using canonical JSON data."""

    return canonical_json_sha256(value.model_dump(mode="json"))
