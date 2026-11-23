"""Stable error envelope (spec §4A).

Every service failure uses ``{code, message, retryable, details}``.
``details`` is schema-validated, non-sensitive, and safe for ordinary clients.
No stack traces, environment variables, local secrets, or provider credentials.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Error codes
INVALID_INPUT = "INVALID_INPUT"
SOURCE_ERROR = "SOURCE_ERROR"
SOURCE_SCHEMA_MISMATCH = "SOURCE_SCHEMA_MISMATCH"
SNAPSHOT_MISMATCH = "SNAPSHOT_MISMATCH"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
INTERNAL_ERROR = "INTERNAL_ERROR"

# Advisory codes (spec §7)
ADVISORY_TIMEOUT = "ADVISORY_TIMEOUT"
ADVISORY_REFUSED = "ADVISORY_REFUSED"
ADVISORY_INVALID_RESPONSE = "ADVISORY_INVALID_RESPONSE"
ADVISORY_AUTH_FAILED = "ADVISORY_AUTH_FAILED"
ADVISORY_RATE_LIMITED = "ADVISORY_RATE_LIMITED"
ADVISORY_NETWORK_ERROR = "ADVISORY_NETWORK_ERROR"
ADVISORY_NOT_CONFIGURED = "ADVISORY_NOT_CONFIGURED"
ADVISORY_UNTRUSTED = "ADVISORY_UNTRUSTED"

_RETRYABLE_CODES = {
    SOURCE_UNAVAILABLE,
    ADVISORY_TIMEOUT,
    ADVISORY_RATE_LIMITED,
    ADVISORY_NETWORK_ERROR,
}


@dataclass
class ServiceError(Exception):
    """Stable service error. ``details`` must be JSON-serializable and safe."""

    code: str
    message: str
    retryable: bool | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.retryable is None:
            self.retryable = self.code in _RETRYABLE_CODES
        Exception.__init__(self, f"{self.code}: {self.message}")

    def to_envelope(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": bool(self.retryable),
            "details": self.details if isinstance(self.details, dict) else {},
        }


def invalid_input(message: str, **details) -> ServiceError:
    return ServiceError(INVALID_INPUT, message, retryable=False, details=details)


def source_error(message: str, code: str = SOURCE_ERROR, **details) -> ServiceError:
    return ServiceError(code, message, retryable=False, details=details)


def internal_error(message: str = "internal service error", **details) -> ServiceError:
    return ServiceError(INTERNAL_ERROR, message, retryable=True, details=details)
