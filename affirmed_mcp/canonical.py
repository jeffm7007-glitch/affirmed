"""Canonical JSON and digest utilities (spec §8B).

Canonical JSON: UTF-8, sorted object keys, no insignificant whitespace,
explicit Unicode normalization (NFC), versioned number serialization.
SHA-256 digests use the form ``sha256:<lowercase hex>``.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from decimal import Decimal

from . import CANONICALIZATION_VERSION


class CanonicalizationError(ValueError):
    """Raised when a value cannot be canonically serialized."""


def _normalize_string(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _prepare(value):
    """Recursively normalize a JSON-like value for canonical serialization.

    - strings: NFC-normalized
    - floats: serialized via repr() and pinned (versioned); NaN/Inf rejected
    - Decimal: converted to a plain float via float() (documented policy)
    - dict: keys must be strings; sorted by code-point order after NFC
    - list/tuple: order preserved
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _normalize_string(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise CanonicalizationError("non-finite float is not canonicalizable")
        return float(repr(value))
    if isinstance(value, Decimal):
        return float(repr(float(value)))
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalizationError("canonical JSON object keys must be strings")
            out[_normalize_string(key)] = _prepare(item)
        return out
    if isinstance(value, (list, tuple)):
        return [_prepare(item) for item in value]
    raise CanonicalizationError(f"unsupported canonical JSON type: {type(value).__name__}")


def canonical_dumps(value) -> str:
    """Serialize a value as canonical JSON (sorted keys, compact separators)."""
    prepared = _prepare(value)
    try:
        return json.dumps(prepared, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise CanonicalizationError(str(exc)) from exc


def canonical_bytes(value) -> bytes:
    return canonical_dumps(value).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value) -> str:
    """Canonicalize ``value`` and return ``sha256:<hex>``."""
    return "sha256:" + sha256_hex(canonical_bytes(value))


def digest_bytes(data: bytes) -> str:
    return "sha256:" + sha256_hex(data)
