"""Versioned local policy configuration (spec §11).

All configuration lives in a versioned ``Policy`` dataclass. Local policy is
loaded once, schema-validated, versioned, and disclosed in each receipt.
There are NO per-request policy overrides; unknown fields / unsafe values
fail closed at startup.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from . import POLICY_VERSION, RETRIEVAL_VERSION, TOKENIZER_VERSION, CANONICALIZATION_VERSION
from .canonical import canonical_bytes, sha256_hex
from .errors import invalid_input

AUDIT_MODES = ("deterministic", "semantic", "auto")
SNAPSHOT_METHODS = ("full_export_sha256", "trusted_source_version")

# Hard bounds (spec §11)
HARD_MAX_QUERY_CHARS = 512
HARD_MAX_ANSWER_CHARS = 8000
HARD_MAX_CLAIMS = 64
HARD_MAX_RETRIEVE_LIMIT = 50
HARD_MAX_IDENTIFIER_CHARS = 128
HARD_MAX_CLAIM_TEXT_CHARS = 1000
HARD_MAX_AGGREGATE_CLAIM_TEXT_CHARS = 16000
HARD_MAX_AUDIT_TIMEOUT_S = 60
HARD_MAX_AUDIT_ATTEMPTS = 3

DEFAULT_SOURCE_AUTHORITY_RANK = {
    "primary_official": 0,
    "official": 1,
    "licensed_partner": 2,
    "partner": 3,
    "secondary": 4,
    "untrusted": 99,
}


@dataclass(frozen=True)
class Policy:
    """Local policy. Frozen: loaded once, validated, disclosed in receipts."""

    policy_version: str = POLICY_VERSION

    # Retrieval
    retrieve_limit: int = 5
    retrieve_max_query_chars: int = HARD_MAX_QUERY_CHARS
    bm25_k1: float = 1.2
    bm25_b: float = 0.75

    # Verification input bounds
    verify_max_answer_chars: int = HARD_MAX_ANSWER_CHARS
    verify_max_claims: int = HARD_MAX_CLAIMS
    max_claim_text_chars: int = HARD_MAX_CLAIM_TEXT_CHARS
    max_aggregate_claim_text_chars: int = HARD_MAX_AGGREGATE_CLAIM_TEXT_CHARS
    max_identifier_chars: int = HARD_MAX_IDENTIFIER_CHARS

    # Audit
    audit_default_mode: str = "deterministic"
    audit_timeout_s: float = 20.0
    audit_max_retries: int = 2  # transient retries; total attempts = 1 + retries <= 3

    # Source snapshot
    source_snapshot_method: str = "full_export_sha256"
    trusted_source_version_table: str | None = None
    trusted_source_version_column: str | None = None
    source_file_staleness_warning_s: float | None = None  # disabled by default

    # Mandatory invariants (non-overridable)
    materiality_unknown_default: str = "material"
    claim_coverage_default: str = "partial_or_unknown"
    semantic_can_promote_verdict: bool = False

    # Source authority classes (configured + documented, spec §6D)
    source_authority_rank: dict[str, int] = field(
        default_factory=lambda: dict(DEFAULT_SOURCE_AUTHORITY_RANK)
    )

    # Source path (local config; disclosed via config hash)
    source_path: str | None = None

    def __post_init__(self):
        self.validate()

    # ------------------------------------------------------------------ #
    def validate(self) -> None:
        """Fail closed: unknown fields, unknown enums, unsafe values rejected."""
        if not isinstance(self.policy_version, str) or not self.policy_version:
            raise invalid_input("policy_version must be a non-empty string")
        _check_int("retrieve_limit", self.retrieve_limit, 1, HARD_MAX_RETRIEVE_LIMIT)
        _check_int("retrieve_max_query_chars", self.retrieve_max_query_chars, 1, HARD_MAX_QUERY_CHARS)
        _check_int("verify_max_answer_chars", self.verify_max_answer_chars, 1, HARD_MAX_ANSWER_CHARS)
        _check_int("verify_max_claims", self.verify_max_claims, 1, HARD_MAX_CLAIMS)
        _check_int("max_claim_text_chars", self.max_claim_text_chars, 1, HARD_MAX_CLAIM_TEXT_CHARS)
        _check_int(
            "max_aggregate_claim_text_chars",
            self.max_aggregate_claim_text_chars,
            1,
            HARD_MAX_AGGREGATE_CLAIM_TEXT_CHARS,
        )
        _check_int("max_identifier_chars", self.max_identifier_chars, 1, HARD_MAX_IDENTIFIER_CHARS)
        if self.audit_default_mode not in AUDIT_MODES:
            raise invalid_input(
                "audit_default_mode must be one of %s" % (AUDIT_MODES,),
                value=self.audit_default_mode,
            )
        if not (0 < float(self.audit_timeout_s) <= HARD_MAX_AUDIT_TIMEOUT_S):
            raise invalid_input("audit_timeout_s out of bounds", value=self.audit_timeout_s)
        _check_int("audit_max_retries", self.audit_max_retries, 0, HARD_MAX_AUDIT_ATTEMPTS - 1)
        if self.source_snapshot_method not in SNAPSHOT_METHODS:
            raise invalid_input(
                "source_snapshot_method must be one of %s" % (SNAPSHOT_METHODS,),
                value=self.source_snapshot_method,
            )
        if self.source_snapshot_method == "trusted_source_version":
            if not self.trusted_source_version_table or not self.trusted_source_version_column:
                raise invalid_input(
                    "trusted_source_version requires table and column configuration"
                )
        if self.source_file_staleness_warning_s is not None:
            if not isinstance(self.source_file_staleness_warning_s, (int, float)) or (
                self.source_file_staleness_warning_s < 0
            ):
                raise invalid_input(
                    "source_file_staleness_warning_s must be null or a non-negative number"
                )
        if self.materiality_unknown_default != "material":
            raise invalid_input("materiality_unknown_default is mandatory and must be 'material'")
        if self.claim_coverage_default != "partial_or_unknown":
            raise invalid_input("claim_coverage_default must be 'partial_or_unknown'")
        if self.semantic_can_promote_verdict is not False:
            raise invalid_input("semantic_can_promote_verdict is a hard-coded invariant (false)")
        if not isinstance(self.source_authority_rank, dict) or not self.source_authority_rank:
            raise invalid_input("source_authority_rank must be a non-empty mapping")
        for key, value in self.source_authority_rank.items():
            if not isinstance(key, str) or not isinstance(value, int):
                raise invalid_input("source_authority_rank keys/values must be str/int")
        if float(self.bm25_k1) <= 0 or not (0.0 <= float(self.bm25_b) <= 1.0):
            raise invalid_input("bm25 parameters out of documented bounds")

    # ------------------------------------------------------------------ #
    @property
    def max_audit_attempts(self) -> int:
        return 1 + self.audit_max_retries

    @property
    def config_hash(self) -> str:
        """SHA-256 over the accepted local configuration (canonical, sorted keys)."""
        return "sha256:" + sha256_hex(canonical_bytes(self.to_dict()))

    def to_dict(self) -> dict[str, Any]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Policy":
        if not isinstance(data, dict):
            raise invalid_input("policy configuration must be a JSON object")
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise invalid_input("unknown policy fields", unknown_fields=unknown)
        return cls(**data)

    @classmethod
    def load(cls, path: str | None = None, **overrides) -> "Policy":
        """Load policy from an optional JSON file plus explicit local overrides.

        Local-only configuration. MCP requests can never carry policy changes.
        """
        data: dict[str, Any] = {}
        if path:
            try:
                raw = Path(path).read_text(encoding="utf-8")
            except OSError as exc:
                raise invalid_input("policy file unreadable", path=path, reason=str(exc))
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise invalid_input("policy file is not valid JSON", path=path, reason=str(exc))
            if not isinstance(parsed, dict):
                raise invalid_input("policy file must contain a JSON object", path=path)
            data.update(parsed)
        data.update(overrides)
        return cls.from_dict(data)


def _check_int(name: str, value, lo: int, hi: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not (lo <= value <= hi):
        raise invalid_input(f"{name} out of bounds", value=value, minimum=lo, maximum=hi)


def versioned_component_versions() -> dict[str, str]:
    """Versions recorded in every receipt."""
    return {
        "tokenizer_version": TOKENIZER_VERSION,
        "retrieval_version": RETRIEVAL_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "policy_version": POLICY_VERSION,
    }
