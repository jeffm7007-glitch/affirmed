"""Claim contract: caller-submitted atomic claims only (spec §4C, §4E).

- Claims come from the tool input; Affirmed never infers free-text claims.
- Unknown claim fields are rejected; no silent splitting or repair.
- The atomicity/ambiguity heuristics are documented deterministic rules, not
  language understanding; uncertain cases route to review outcomes.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from .canonical import digest
from .config import Policy
from .errors import invalid_input

CLAIM_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
MATERIALITY_ENUM = ("material", "non_material", "unknown")

CLAIMS_REQUIRED = "CLAIMS_REQUIRED"
CLAIMS_MALFORMED = "CLAIMS_MALFORMED"
CLAIMS_NOT_ATOMIC = "CLAIMS_NOT_ATOMIC"
CLAIM_AMBIGUOUS = "CLAIM_AMBIGUOUS"

_ALLOWED_CLAIM_FIELDS = {"claim_id", "text", "materiality", "subject_id", "field_name"}

# Documented deterministic atomicity heuristic v1.
_CLAUSE_SPLIT_RE = re.compile(r"\b(?: and| but| or| ;|\.)\s+", re.IGNORECASE)
_VERBISH_TOKENS = (
    "is", "are", "was", "were", "has", "have", "costs", "offer", "offers", "provides",
    "provide", "covers", "serves", "includes", "charges", "available", "operates",
)


@dataclass(frozen=True)
class ClaimInput:
    claim_id: str
    text: str
    materiality: str = "unknown"
    subject_id: str | None = None
    field_name: str | None = None

    def canonical(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "claim_id": self.claim_id,
            "text": unicodedata.normalize("NFC", self.text),
            "materiality": self.materiality,
        }
        if self.subject_id is not None:
            out["subject_id"] = self.subject_id
        if self.field_name is not None:
            out["field_name"] = self.field_name
        return out


@dataclass
class ClaimAbstention:
    """Domain abstention before evidence retrieval (receipt returned, not an error)."""

    code: str
    message: str
    affected_claim_ids: list[str]
    suggested_claims: list[dict[str, Any]]
    suggestion_set_digest: str | None


def submitted_claims_digest(claims: list[ClaimInput]) -> str:
    """Digest over the canonical submitted claim set (sorted by claim_id)."""
    canonical = sorted((c.canonical() for c in claims), key=lambda item: item["claim_id"])
    return digest({"claims": canonical})


def _suggestions_canonical(texts: list[str]) -> dict[str, Any]:
    normalized = sorted(unicodedata.normalize("NFC", t) for t in texts)
    return {"texts": normalized, "label": "suggested_claims_not_verified"}


def suggestion_set_digest(suggestions: list[dict[str, Any]]) -> str:
    """Digest over the canonical suggestion TEXT set (ids are advisory only).

    Acceptance matching is text-based: the caller may resubmit under their own
    claim_ids, but the suggested texts must be resubmitted unedited.
    """
    return digest(_suggestions_canonical([s["text"] for s in suggestions]))


def suggestion_texts_digest(texts: list[str]) -> str:
    """Digest over submitted claim texts, for suggested_accepted matching."""
    return digest(_suggestions_canonical(texts))


def _structurally_invalid_items(claims: Any, policy: Policy) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (problems, valid_indices). Claim-item domain validation (§4C)."""
    problems: list[dict[str, Any]] = []
    valid: list[str] = []
    seen_ids: set[str] = set()
    aggregate_chars = 0
    if not isinstance(claims, list):
        return ([{"index": None, "problem": "claims must be an array"}], [])
    for idx, item in enumerate(claims):
        where = f"claims[{idx}]"
        if not isinstance(item, dict):
            problems.append({"index": idx, "problem": "claim item must be an object"})
            continue
        unknown = sorted(set(item) - _ALLOWED_CLAIM_FIELDS)
        if unknown:
            problems.append({"index": idx, "claim_id": item.get("claim_id"), "problem": f"unknown claim fields {unknown}"})
            continue
        claim_id = item.get("claim_id")
        text = item.get("text")
        materiality = item.get("materiality", "unknown")
        if not isinstance(claim_id, str) or not claim_id or len(claim_id) > policy.max_identifier_chars:
            problems.append({"index": idx, "problem": "claim_id must be a non-empty string <= 128 chars"})
            continue
        if claim_id in seen_ids:
            problems.append({"index": idx, "claim_id": claim_id, "problem": "duplicate claim_id"})
            continue
        if not CLAIM_ID_RE.match(claim_id):
            problems.append({"index": idx, "claim_id": claim_id, "problem": "claim_id must match [A-Za-z0-9._-]+"})
            continue
        if not isinstance(text, str) or not text.strip():
            problems.append({"index": idx, "claim_id": claim_id, "problem": "text is required and must be non-blank"})
            continue
        if len(text) > policy.max_claim_text_chars:
            problems.append({"index": idx, "claim_id": claim_id, "problem": "claim text exceeds maximum length"})
            continue
        if materiality not in MATERIALITY_ENUM:
            problems.append({"index": idx, "claim_id": claim_id, "problem": f"invalid materiality {materiality!r}"})
            continue
        for optional in ("subject_id", "field_name"):
            value = item.get(optional)
            if value is not None and (not isinstance(value, str) or not value or len(value) > policy.max_identifier_chars):
                problems.append({"index": idx, "claim_id": claim_id, "problem": f"{optional} must be a non-empty string <= 128 chars"})
                continue
        seen_ids.add(claim_id)
        aggregate_chars += len(text)
        valid.append(str(idx))
    if aggregate_chars > policy.max_aggregate_claim_text_chars:
        problems.append({"index": None, "problem": "aggregate claim text exceeds maximum length"})
    return problems, valid


def parse_and_validate_claims(claims: Any, policy: Policy) -> tuple[list[ClaimInput] | None, ClaimAbstention | None]:
    """Validate the claim contract. Returns (claims, abstention).

    - claims omitted/null/empty  -> CLAIMS_REQUIRED abstention
    - structurally invalid items -> CLAIMS_MALFORMED abstention (affected ids identified)
    """
    if claims is None or (isinstance(claims, list) and len(claims) == 0):
        return None, ClaimAbstention(
            code=CLAIMS_REQUIRED,
            message="claims are required: submit the atomic claims you intend to make",
            affected_claim_ids=[],
            suggested_claims=[],
            suggestion_set_digest=None,
        )
    problems, valid_indices = _structurally_invalid_items(claims, policy)
    if problems:
        affected = sorted({p.get("claim_id") for p in problems if p.get("claim_id")})
        return None, ClaimAbstention(
            code=CLAIMS_MALFORMED,
            message="one or more claim items are structurally malformed",
            affected_claim_ids=affected,
            suggested_claims=[],
            suggestion_set_digest=None,
        )
    parsed = [
        ClaimInput(
            claim_id=item["claim_id"],
            text=item["text"],
            materiality=item.get("materiality", "unknown"),
            subject_id=item.get("subject_id"),
            field_name=item.get("field_name"),
        )
        for idx, item in enumerate(claims)
        if str(idx) in set(valid_indices)
    ]
    return parsed, None


def check_atomicity(claims: list[ClaimInput]) -> ClaimAbstention | None:
    """Detect compound claims deterministically; never split or verify them (§4C)."""
    non_atomic: list[str] = []
    suggestions: list[dict[str, Any]] = []
    for claim in claims:
        parts = _split_into_atomic_candidates(claim.text)
        if len(parts) > 1:
            non_atomic.append(claim.claim_id)
            for i, part in enumerate(parts):
                suggestions.append(
                    {
                        "suggestion_id": f"{claim.claim_id}.suggested.{i + 1}",
                        "text": part,
                        "source_claim_id": claim.claim_id,
                        "label": "suggestion",
                    }
                )
    if not non_atomic:
        return None
    return ClaimAbstention(
        code=CLAIMS_NOT_ATOMIC,
        message="one or more claims appear compound; they were not split or verified",
        affected_claim_ids=non_atomic,
        suggested_claims=suggestions,
        suggestion_set_digest=suggestion_set_digest(suggestions),
    )


def _split_into_atomic_candidates(text: str) -> list[str]:
    """Documented deterministic heuristic: split at sentence/conjunction boundaries
    where each side carries its own predicate-like token. Not a complete language
    understanding system; uncertain cases stay whole (review routed elsewhere)."""
    normalized = unicodedata.normalize("NFC", text).strip()
    segments = [s.strip() for s in _CLAUSE_SPLIT_RE.split(normalized) if s.strip()]
    if len(segments) <= 1:
        return [normalized]
    # Each segment must look like an independent proposition (verbish token).
    independent = []
    for seg in segments:
        lower = seg.lower()
        if any(tok in lower.split() or f"{tok} " in lower for tok in _VERBISH_TOKENS) and len(seg) >= 12:
            independent.append(seg)
    if len(independent) >= 2:
        return independent
    return [normalized]


def suggest_claims_for_answer(answer_text: str) -> list[dict[str, Any]]:
    """CLI §4E: deterministic sentence-boundary + conjunction heuristic.
    Output is labeled suggestions; nothing is submitted or verified."""
    normalized = unicodedata.normalize("NFC", answer_text)
    raw = [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]
    suggestions: list[dict[str, Any]] = []
    for i, sentence in enumerate(raw):
        for j, part in enumerate(_split_into_atomic_candidates(sentence)):
            if not part:
                continue
            suggestions.append(
                {
                    "suggestion_id": f"suggested.{i + 1}.{j + 1}",
                    "text": part,
                    "source_claim_id": None,
                    "label": "suggestion",
                }
            )
    return suggestions


def verify_top_level_request(payload: Any, allowed_fields: set[str], tool: str) -> dict[str, Any]:
    """Pre-validation: unknown top-level fields rejected (§4A)."""
    if not isinstance(payload, dict):
        raise invalid_input(f"{tool}: request payload must be a JSON object")
    unknown = sorted(set(payload) - allowed_fields)
    if unknown:
        raise invalid_input(f"{tool}: unknown top-level fields", unknown_fields=unknown)
    return payload
