"""Deterministic verifier: typed-field comparisons, scope checks, conflict
policy, and verdict composition (spec §5, §6C, §6D, §6E).

Evidence-backed verdicts are produced by deterministic rules only. Text
overlap alone can never satisfy the support contract for numbers, negation,
dates, availability, geography, or material quantifier scope. Lexical
similarity may rank evidence; it may contribute to PARTIALLY_SUPPORTED only
when other material elements are independently supported.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import VERIFIER_VERSION
from .claims import ClaimInput
from .config import Policy
from .features import ClaimFeatures, extract_features
from .retrieval import evidence_set_digest

# Verdict order from least to most assured (spec §5A)
VERDICT_ORDER = ["CONTRADICTED", "UNSUPPORTED", "PARTIALLY_SUPPORTED", "SUPPORTED"]

# Element status order (least to most assured) for conservative composition
_ELEMENT_RANK = {"CONTRADICTED": 0, "UNRESOLVED": 1, "UNSUPPORTED": 2, "SUPPORTED": 3}

# Stable reason codes (spec §16 vocabulary + internal rule codes)
EVIDENCE_CONFLICT = "EVIDENCE_CONFLICT"
REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
RETRIEVAL_NO_MATCH = "RETRIEVAL_NO_MATCH"
CLAIM_AMBIGUOUS = "CLAIM_AMBIGUOUS"
FEATURE_UNVERIFIABLE = "FEATURE_UNVERIFIABLE"
FEATURE_EXTRACTION_FAILED = "FEATURE_EXTRACTION_FAILED"
SOURCE_AUTHORITY_UNRESOLVED = "SOURCE_AUTHORITY_UNRESOLVED"
UNIT_NOT_RESOLVABLE = "UNIT_NOT_RESOLVABLE"
VALUE_MISMATCH = "VALUE_MISMATCH"
SUPPORTED_BY_TYPED_FIELD = "SUPPORTED_BY_TYPED_FIELD"
SCOPE_INCOMPATIBLE = "SCOPE_INCOMPATIBLE"

# Rule identifiers recorded in receipts (verifier v1)
RULE_SUPPORT_CONTRACT = "RULE_SUPPORT_CONTRACT_V1"
RULE_TYPED_FIELD_MATCH = "RULE_TYPED_FIELD_MATCH_V1"
RULE_NUMERIC_COMPARISON = "RULE_NUMERIC_COMPARISON_V1"
RULE_AVAILABILITY_COMPARISON = "RULE_AVAILABILITY_COMPARISON_V1"
RULE_NEGATION_COMPARISON = "RULE_NEGATION_COMPARISON_V1"
RULE_GEO_COMPARISON = "RULE_GEO_COMPARISON_V1"
RULE_QUANTIFIER_COMPARISON = "RULE_QUANTIFIER_COMPARISON_V1"
RULE_TEMPORAL_APPLICABILITY = "RULE_TEMPORAL_APPLICABILITY_V1"
RULE_CONFLICT_AUTHORITY = "RULE_CONFLICT_AUTHORITY_V1"
RULE_NO_TEXT_UPGRADE = "RULE_NO_TEXT_UPGRADE_V1"

UNTRUSTED_AUTHORITY_FALLBACK_RANK = 50


@dataclass
class ElementResult:
    element: str
    kind: str
    status: str  # SUPPORTED | UNSUPPORTED | CONTRADICTED | UNRESOLVED
    reasons: list[str] = field(default_factory=list)
    rule_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "element": self.element,
            "kind": self.kind,
            "status": self.status,
            "reasons": self.reasons,
            "rule_ids": self.rule_ids,
            "evidence_ids": self.evidence_ids,
            "detail": self.detail,
        }


@dataclass
class ClaimEvaluation:
    claim: ClaimInput
    features: ClaimFeatures
    evaluation_status: str  # EVALUATED | UNRESOLVED
    deterministic_verdict: str | None
    reasons: list[str]
    rule_ids: list[str]
    evidence_ids: list[str]
    evidence_set_digest: str | None
    elements: list[ElementResult]
    materiality: str
    materiality_origin: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim.claim_id,
            "text": self.claim.text,
            "materiality": self.materiality,
            "materiality_origin": self.materiality_origin,
            "features": self.features.to_dict(),
            "evaluation_status": self.evaluation_status,
            "deterministic_verdict": self.deterministic_verdict,
            "reasons": self.reasons,
            "rule_ids": sorted(set(self.rule_ids)),
            "evidence_ids": self.evidence_ids,
            "evidence_set_digest": self.evidence_set_digest,
            "elements": [e.to_dict() for e in self.elements],
        }


def parse_as_of(as_of: str | None) -> tuple[datetime, str]:
    """Parse explicit as_of (ISO 8601 UTC) or default to current UTC time.

    The as_of value is recorded and treated as a deterministic input; the
    default is the current UTC time recorded in the receipt.
    """
    if as_of is None:
        now = datetime.now(timezone.utc)
        return now, now.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        parsed = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"as_of must be ISO 8601, got {as_of!r}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc), parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _record_applicable_at(record: dict[str, Any], as_of: datetime) -> bool:
    """Interval semantics: [valid_from, valid_to); null boundaries unbounded."""
    valid_from = record.get("valid_from")
    valid_to = record.get("valid_to")
    if valid_from is not None and as_of < _parse_iso(valid_from):
        return False
    if valid_to is not None and as_of >= _parse_iso(valid_to):
        return False
    return True


def _authority_rank(record: dict[str, Any], policy: Policy) -> int:
    authority = record.get("source_authority")
    if authority is None:
        return UNTRUSTED_AUTHORITY_FALLBACK_RANK
    return policy.source_authority_rank.get(authority, UNTRUSTED_AUTHORITY_FALLBACK_RANK)


def _temporally_disjoint(a: dict[str, Any], b: dict[str, Any]) -> bool:
    a_from, a_to = a.get("valid_from"), a.get("valid_to")
    b_from, b_to = b.get("valid_from"), b.get("valid_to")
    if a_to is not None and b_from is not None and _parse_iso(a_to) <= _parse_iso(b_from):
        return True
    if b_to is not None and a_from is not None and _parse_iso(b_to) <= _parse_iso(a_from):
        return True
    return False


def _resolve_conflict(records: list[dict[str, Any]], policy: Policy) -> tuple[list[dict[str, Any]], str | None]:
    """Apply the documented conflict policy (spec §6D).

    Returns (resolved_records, conflict_note). Records with different
    effective dates may describe different states rather than true conflicts.
    Authority ranking is configured, never invented. Retrieval score/count is
    never authority.
    """
    if len(records) <= 1:
        return records, None
    best_rank = min(_authority_rank(r, policy) for r in records)
    top = [r for r in records if _authority_rank(r, policy) == best_rank]
    if len(top) == 1:
        return top, f"conflict_resolved_by_authority:{top[0].get('source_authority')}"
    # Same authority: temporally disjoint records are different states, keep all
    disjoint = all(
        _temporally_disjoint(top[i], top[j]) for i in range(len(top)) for j in range(i + 1, len(top))
    )
    if disjoint:
        return top, "same_authority_temporally_disjoint_states"
    return top, "conflict_unresolved"


def _subject_matches(record: dict[str, Any], claim: ClaimInput) -> bool:
    if claim.subject_id is None:
        return True
    return record.get("subject_id") == claim.subject_id


def _candidate_records(records: list[dict[str, Any]], claim: ClaimInput, features: ClaimFeatures, as_of: datetime) -> list[dict[str, Any]]:
    """Applicable records: subject matches, temporally applicable, has typed field."""
    applicable = [
        r
        for r in records
        if _subject_matches(r, claim) and _record_applicable_at(r, as_of) and r.get("field_name")
    ]
    if features.candidate_fields:
        field_filtered = [r for r in applicable if r.get("field_name") in features.candidate_fields]
        return field_filtered if field_filtered else applicable
    return applicable


def _detect_subject_ambiguity(records: list[dict[str, Any]], claim: ClaimInput) -> bool:
    if claim.subject_id is not None:
        return False
    subjects = {r.get("subject_id") for r in records if r.get("field_name") and r.get("subject_id")}
    return len(subjects) > 1


# --------------------------------------------------------------------------- #
# Element evaluators
# --------------------------------------------------------------------------- #

def _eval_availability(features: ClaimFeatures, candidates: list[dict[str, Any]], policy: Policy) -> ElementResult:
    typed = [r for r in candidates if r.get("field_type") == "availability"]
    rule_ids = [RULE_AVAILABILITY_COMPARISON, RULE_NO_TEXT_UPGRADE, RULE_SUPPORT_CONTRACT]
    if not typed:
        # Only string business_hours or nothing: missing required typed field.
        stringy = [r for r in candidates if r.get("field_name") in features.candidate_fields]
        reasons = [REQUIRED_FIELD_MISSING, RULE_NO_TEXT_UPGRADE]
        return ElementResult(
            element="value", kind="availability", status="UNSUPPORTED",
            reasons=reasons, rule_ids=rule_ids,
            evidence_ids=[r["id"] for r in stringy],
            detail={"claim_availability": features.availability,
                    "note": "availability requires an availability-typed field; text alone is insufficient"},
        )
    resolved, note = _resolve_conflict(typed, policy)
    if note == "conflict_unresolved":
        return ElementResult(
            element="value", kind="availability", status="UNRESOLVED",
            reasons=[EVIDENCE_CONFLICT, SOURCE_AUTHORITY_UNRESOLVED],
            rule_ids=rule_ids + [RULE_CONFLICT_AUTHORITY],
            evidence_ids=[r["id"] for r in resolved],
            detail={"conflict_records": [r["id"] for r in resolved]},
        )
    if features.availability == "always":
        for r in resolved:
            schedule = r.get("availability_schedule") or {}
            if schedule.get("always") is True:
                return ElementResult(
                    element="value", kind="availability", status="SUPPORTED",
                    reasons=[SUPPORTED_BY_TYPED_FIELD],
                    rule_ids=rule_ids,
                    evidence_ids=[r["id"]],
                    detail={"schedule": schedule, "conflict_resolution": note},
                )
        for r in resolved:
            schedule = r.get("availability_schedule") or {}
            if schedule.get("always") is False or schedule.get("days"):
                return ElementResult(
                    element="value", kind="availability", status="CONTRADICTED",
                    reasons=[VALUE_MISMATCH],
                    rule_ids=rule_ids,
                    evidence_ids=[r["id"]],
                    detail={"schedule": schedule, "claim": "always"},
                )
    else:  # limited availability claim
        for r in resolved:
            schedule = r.get("availability_schedule") or {}
            if schedule.get("always") is False or schedule.get("days") or schedule.get("start"):
                return ElementResult(
                    element="value", kind="availability", status="SUPPORTED",
                    reasons=[SUPPORTED_BY_TYPED_FIELD], rule_ids=rule_ids,
                    evidence_ids=[r["id"]], detail={"schedule": schedule},
                )
        for r in resolved:
            schedule = r.get("availability_schedule") or {}
            if schedule.get("always") is True:
                return ElementResult(
                    element="value", kind="availability", status="CONTRADICTED",
                    reasons=[VALUE_MISMATCH], rule_ids=rule_ids,
                    evidence_ids=[r["id"]], detail={"schedule": schedule, "claim": "limited"},
                )
    return ElementResult(
        element="value", kind="availability", status="UNSUPPORTED",
        reasons=[REQUIRED_FIELD_MISSING], rule_ids=rule_ids,
        evidence_ids=[r["id"] for r in resolved],
        detail={"note": "no applicable availability-typed value matched"},
    )


def _eval_numeric(number, comparator: str, features: ClaimFeatures, candidates: list[dict[str, Any]], policy: Policy) -> ElementResult:
    typed = [r for r in candidates if r.get("field_type") == "number"]
    rule_ids = [RULE_NUMERIC_COMPARISON, RULE_NO_TEXT_UPGRADE, RULE_SUPPORT_CONTRACT]
    if not typed:
        stringy = [r for r in candidates if r.get("field_name") in features.candidate_fields]
        return ElementResult(
            element="value", kind="numeric", status="UNSUPPORTED",
            reasons=[REQUIRED_FIELD_MISSING, RULE_NO_TEXT_UPGRADE], rule_ids=rule_ids,
            evidence_ids=[r["id"] for r in stringy],
            detail={"claim_value": number.value, "claim_unit": number.unit,
                    "note": "numeric claims require a number-typed field; text overlap cannot verify numbers"},
        )
    unit = number.unit
    same_unit = [r for r in typed if (r.get("field_unit") or None) == unit]
    if unit is not None and not same_unit:
        return ElementResult(
            element="value", kind="numeric", status="UNRESOLVED",
            reasons=[UNIT_NOT_RESOLVABLE], rule_ids=rule_ids,
            evidence_ids=[r["id"] for r in typed],
            detail={"claim_unit": unit, "evidence_units": sorted({r.get("field_unit") for r in typed}),
                    "note": "no configured unit conversion policy covers this unit pair"},
        )
    pool = same_unit if same_unit else typed
    resolved, note = _resolve_conflict(pool, policy)
    if note == "conflict_unresolved":
        return ElementResult(
            element="value", kind="numeric", status="UNRESOLVED",
            reasons=[EVIDENCE_CONFLICT, SOURCE_AUTHORITY_UNRESOLVED],
            rule_ids=rule_ids + [RULE_CONFLICT_AUTHORITY],
            evidence_ids=[r["id"] for r in resolved],
            detail={"conflict_records": [r["id"] for r in resolved]},
        )
    def _compare(evidence_value: float) -> bool:
        if comparator == "at least":
            return evidence_value >= number.value
        if comparator == "up to":
            return evidence_value <= number.value
        return evidence_value == number.value

    for r in resolved:
        ev = r.get("field_value")
        if isinstance(ev, (int, float)) and _compare(float(ev)):
            return ElementResult(
                element="value", kind="numeric", status="SUPPORTED",
                reasons=[SUPPORTED_BY_TYPED_FIELD], rule_ids=rule_ids,
                evidence_ids=[r["id"]],
                detail={"evidence_value": ev, "evidence_unit": r.get("field_unit"),
                        "comparator": comparator, "conflict_resolution": note},
            )
    for r in resolved:
        ev = r.get("field_value")
        if isinstance(ev, (int, float)) and not _compare(float(ev)):
            return ElementResult(
                element="value", kind="numeric", status="CONTRADICTED",
                reasons=[VALUE_MISMATCH], rule_ids=rule_ids,
                evidence_ids=[r["id"]],
                detail={"evidence_value": ev, "claim_value": number.value,
                        "comparator": comparator},
            )
    return ElementResult(
        element="value", kind="numeric", status="UNSUPPORTED",
        reasons=[REQUIRED_FIELD_MISSING], rule_ids=rule_ids,
        evidence_ids=[r["id"] for r in resolved],
        detail={"note": "no numeric-typed value applicable"},
    )


def _eval_quantifier(features: ClaimFeatures, candidates: list[dict[str, Any]], policy: Policy) -> ElementResult:
    typed = [r for r in candidates if r.get("field_type") == "quantified_text"]
    rule_ids = [RULE_QUANTIFIER_COMPARISON, RULE_NO_TEXT_UPGRADE, RULE_SUPPORT_CONTRACT]
    if not typed:
        return ElementResult(
            element="scope", kind="quantifier", status="UNSUPPORTED",
            reasons=[REQUIRED_FIELD_MISSING, RULE_NO_TEXT_UPGRADE], rule_ids=rule_ids,
            evidence_ids=[],
            detail={"quantifier": features.quantifier,
                    "note": "quantifier scope requires structured quantified_text evidence"},
        )
    resolved, note = _resolve_conflict(typed, policy)
    if note == "conflict_unresolved":
        return ElementResult(
            element="scope", kind="quantifier", status="UNRESOLVED",
            reasons=[EVIDENCE_CONFLICT, SOURCE_AUTHORITY_UNRESOLVED],
            rule_ids=rule_ids + [RULE_CONFLICT_AUTHORITY],
            evidence_ids=[r["id"] for r in resolved],
            detail={"conflict_records": [r["id"] for r in resolved]},
        )
    for r in resolved:
        scope = r.get("quantifier_scope") or {}
        if scope.get("quantifier") == features.quantifier:
            return ElementResult(
                element="scope", kind="quantifier", status="SUPPORTED",
                reasons=[SUPPORTED_BY_TYPED_FIELD], rule_ids=rule_ids,
                evidence_ids=[r["id"]], detail={"quantifier_scope": scope},
            )
    return ElementResult(
        element="scope", kind="quantifier", status="UNSUPPORTED",
        reasons=[VALUE_MISMATCH], rule_ids=rule_ids,
        evidence_ids=[r["id"] for r in resolved],
        detail={"note": "structured quantifier evidence did not match the claim"},
    )


def _eval_geo(claim_region: str, features: ClaimFeatures, candidates: list[dict[str, Any]], policy: Policy) -> ElementResult:
    typed = [r for r in candidates if r.get("field_type") == "geography"]
    rule_ids = [RULE_GEO_COMPARISON, RULE_NO_TEXT_UPGRADE, RULE_SUPPORT_CONTRACT]
    target = claim_region.strip().lower()
    if not typed:
        return ElementResult(
            element="scope", kind="geography", status="UNSUPPORTED",
            reasons=[REQUIRED_FIELD_MISSING, RULE_NO_TEXT_UPGRADE], rule_ids=rule_ids,
            evidence_ids=[],
            detail={"claim_region": claim_region,
                    "note": "geographic scope requires geo-typed evidence"},
        )
    resolved, note = _resolve_conflict(typed, policy)
    if note == "conflict_unresolved":
        return ElementResult(
            element="scope", kind="geography", status="UNRESOLVED",
            reasons=[EVIDENCE_CONFLICT, SOURCE_AUTHORITY_UNRESOLVED],
            rule_ids=rule_ids + [RULE_CONFLICT_AUTHORITY],
            evidence_ids=[r["id"] for r in resolved],
            detail={"conflict_records": [r["id"] for r in resolved]},
        )
    for r in resolved:
        geo = r.get("geo_scope") or {}
        for region in geo.get("regions", []):
            values = {str(v).lower() for v in region.values() if v}
            if target in values:
                return ElementResult(
                    element="scope", kind="geography", status="SUPPORTED",
                    reasons=[SUPPORTED_BY_TYPED_FIELD], rule_ids=rule_ids,
                    evidence_ids=[r["id"]], detail={"matched_region": region},
                )
    return ElementResult(
        element="scope", kind="geography", status="CONTRADICTED",
        reasons=[VALUE_MISMATCH, SCOPE_INCOMPATIBLE], rule_ids=rule_ids,
        evidence_ids=[r["id"] for r in resolved],
        detail={"claim_region": claim_region,
                "evidence_regions": [g for r in resolved for g in (r.get("geo_scope") or {}).get("regions", [])]},
    )


def _eval_date(claim_date: str, features: ClaimFeatures, candidates: list[dict[str, Any]], policy: Policy) -> ElementResult:
    typed = [
        r for r in candidates if r.get("field_type") in ("date", "datetime")
    ]
    rule_ids = [RULE_TYPED_FIELD_MATCH, RULE_NO_TEXT_UPGRADE, RULE_SUPPORT_CONTRACT]
    claim_norm = claim_date.strip()
    if not typed:
        return ElementResult(
            element="value", kind="date", status="UNSUPPORTED",
            reasons=[REQUIRED_FIELD_MISSING, RULE_NO_TEXT_UPGRADE], rule_ids=rule_ids,
            evidence_ids=[],
            detail={"claim_date": claim_date},
        )
    resolved, note = _resolve_conflict(typed, policy)
    if note == "conflict_unresolved":
        return ElementResult(
            element="value", kind="date", status="UNRESOLVED",
            reasons=[EVIDENCE_CONFLICT, SOURCE_AUTHORITY_UNRESOLVED],
            rule_ids=rule_ids + [RULE_CONFLICT_AUTHORITY],
            evidence_ids=[r["id"] for r in resolved],
            detail={"conflict_records": [r["id"] for r in resolved]},
        )
    for r in resolved:
        if str(r.get("field_value", "")).strip() == claim_norm:
            return ElementResult(
                element="value", kind="date", status="SUPPORTED",
                reasons=[SUPPORTED_BY_TYPED_FIELD], rule_ids=rule_ids,
                evidence_ids=[r["id"]], detail={"evidence_date": r.get("field_value")},
            )
    return ElementResult(
        element="value", kind="date", status="CONTRADICTED",
        reasons=[VALUE_MISMATCH], rule_ids=rule_ids,
        evidence_ids=[r["id"] for r in resolved],
        detail={"claim_date": claim_date,
                "evidence_dates": [r.get("field_value") for r in resolved]},
    )


def _eval_service_presence(features: ClaimFeatures, candidates: list[dict[str, Any]], policy: Policy) -> ElementResult:
    """Negated claim: '<subject> does not offer <service>'."""
    rule_ids = [RULE_NEGATION_COMPARISON, RULE_NO_TEXT_UPGRADE, RULE_SUPPORT_CONTRACT]
    typed = [r for r in candidates if r.get("field_type") in ("availability", "boolean", "string")]
    if not typed:
        return ElementResult(
            element="value", kind="service_presence", status="UNSUPPORTED",
            reasons=[REQUIRED_FIELD_MISSING, RETRIEVAL_NO_MATCH, RULE_NO_TEXT_UPGRADE],
            rule_ids=rule_ids, evidence_ids=[],
            detail={"note": "negation cannot be verified by text overlap"},
        )
    resolved, note = _resolve_conflict(typed, policy)
    if note == "conflict_unresolved":
        return ElementResult(
            element="value", kind="service_presence", status="UNRESOLVED",
            reasons=[EVIDENCE_CONFLICT, SOURCE_AUTHORITY_UNRESOLVED],
            rule_ids=rule_ids + [RULE_CONFLICT_AUTHORITY],
            evidence_ids=[r["id"] for r in resolved],
            detail={"conflict_records": [r["id"] for r in resolved]},
        )
    for r in resolved:
        ftype = r.get("field_type")
        value = r.get("field_value")
        if ftype == "boolean":
            if value is True:
                return ElementResult(
                    element="value", kind="service_presence", status="CONTRADICTED",
                    reasons=[VALUE_MISMATCH], rule_ids=rule_ids, evidence_ids=[r["id"]],
                    detail={"evidence_boolean": True, "claim": "not offered"},
                )
            return ElementResult(
                element="value", kind="service_presence", status="SUPPORTED",
                reasons=[SUPPORTED_BY_TYPED_FIELD], rule_ids=rule_ids, evidence_ids=[r["id"]],
                detail={"evidence_boolean": False, "claim": "not offered"},
            )
        if ftype == "availability":
            schedule = r.get("availability_schedule") or {}
            if schedule.get("always") is True or schedule.get("days"):
                return ElementResult(
                    element="value", kind="service_presence", status="CONTRADICTED",
                    reasons=[VALUE_MISMATCH], rule_ids=rule_ids, evidence_ids=[r["id"]],
                    detail={"schedule": schedule, "claim": "not offered"},
                )
    return ElementResult(
        element="value", kind="service_presence", status="UNSUPPORTED",
        reasons=[REQUIRED_FIELD_MISSING], rule_ids=rule_ids,
        evidence_ids=[r["id"] for r in resolved],
        detail={"note": "no applicable typed evidence for the negated service"},
    )


# --------------------------------------------------------------------------- #
# Claim evaluation
# --------------------------------------------------------------------------- #

def evaluate_claim(
    claim: ClaimInput,
    retrieved_records: list[dict[str, Any]],
    policy: Policy,
    as_of: datetime,
) -> tuple[ClaimEvaluation | None, str | None]:
    """Evaluate one claim. Returns (evaluation, ambiguity_code_or_None)."""
    # Extraction must never crash verification: a pathological claim text is a
    # claim-level safe failure (UNRESOLVED), not a stack trace (§5E: verification
    # failure => abstain; §9 safe failures).
    try:
        features = extract_features(claim.text, caller_field_hint=claim.field_name)
    except Exception:
        features = ClaimFeatures(claim_type="unmapped")
        return (
            ClaimEvaluation(
                claim=claim,
                features=features,
                evaluation_status="UNRESOLVED",
                deterministic_verdict=None,
                reasons=[FEATURE_EXTRACTION_FAILED],
                rule_ids=[RULE_SUPPORT_CONTRACT],
                evidence_ids=[],
                evidence_set_digest=evidence_set_digest(retrieved_records),
                elements=[],
                materiality=claim.materiality,
                materiality_origin="caller",
            ),
            None,
        )

    # Unsupported reasoning types are never forced through generic regex (§5B).
    if features.unsupported_reasoning or features.claim_type == "unmapped":
        reason = FEATURE_UNVERIFIABLE if features.unsupported_reasoning else CLAIM_AMBIGUOUS
        return (
            ClaimEvaluation(
                claim=claim,
                features=features,
                evaluation_status="UNRESOLVED",
                deterministic_verdict=None,
                reasons=[reason],
                rule_ids=[RULE_SUPPORT_CONTRACT],
                evidence_ids=[],
                evidence_set_digest=evidence_set_digest(retrieved_records),
                elements=[],
                materiality=claim.materiality,
                materiality_origin="caller",
            ),
            None,
        )

    candidates = _candidate_records(retrieved_records, claim, features, as_of)
    if _detect_subject_ambiguity(candidates, claim):
        return None, CLAIM_AMBIGUOUS

    elements: list[ElementResult] = []
    if features.claim_type == "negated_service":
        # Negated claims evaluate only the presence element: other feature
        # elements would misread negated scope (documented v1 behavior).
        elements.append(_eval_service_presence(features, candidates, policy))
    if features.availability and not features.negated:
        elements.append(_eval_availability(features, candidates, policy))
    for number in features.numbers:
        if features.negated:
            continue
        comparator = "exact"
        if features.quantifier == "at least":
            comparator = "at least"
        elif features.quantifier == "up to":
            comparator = "up to"
        elements.append(_eval_numeric(number, comparator, features, candidates, policy))
    if features.quantifier and features.quantifier not in ("at least", "up to"):
        elements.append(_eval_quantifier(features, candidates, policy))
    for region in features.geos:
        elements.append(_eval_geo(region, features, candidates, policy))
    if features.claim_type == "date_assertion" and features.dates:
        elements.append(_eval_date(features.dates[0], features, candidates, policy))

    if not elements:
        return (
            ClaimEvaluation(
                claim=claim,
                features=features,
                evaluation_status="UNRESOLVED",
                deterministic_verdict=None,
                reasons=[FEATURE_UNVERIFIABLE],
                rule_ids=[RULE_SUPPORT_CONTRACT],
                evidence_ids=[],
                evidence_set_digest=evidence_set_digest(retrieved_records),
                elements=[],
                materiality=claim.materiality,
                materiality_origin="caller",
            ),
            None,
        )

    statuses = [e.status for e in elements]
    evidence_ids = sorted({eid for e in elements for eid in e.evidence_ids})
    rule_ids = [rid for e in elements for rid in e.rule_ids]

    if "UNRESOLVED" in statuses:
        verdict = None
        status = "UNRESOLVED"
        reasons = sorted({r for e in elements if e.status == "UNRESOLVED" for r in e.reasons})
    elif "CONTRADICTED" in statuses:
        verdict = "CONTRADICTED"
        status = "EVALUATED"
        reasons = sorted({r for e in elements if e.status == "CONTRADICTED" for r in e.reasons})
    elif all(s == "SUPPORTED" for s in statuses):
        verdict = "SUPPORTED"
        status = "EVALUATED"
        reasons = [SUPPORTED_BY_TYPED_FIELD]
    elif any(s == "SUPPORTED" for s in statuses):
        verdict = "PARTIALLY_SUPPORTED"
        status = "EVALUATED"
        reasons = sorted({r for e in elements if e.status == "UNSUPPORTED" for r in e.reasons}) or [REQUIRED_FIELD_MISSING]
    else:
        verdict = "UNSUPPORTED"
        status = "EVALUATED"
        reasons = sorted({r for e in elements for r in e.reasons}) or [RETRIEVAL_NO_MATCH]

    return (
        ClaimEvaluation(
            claim=claim,
            features=features,
            evaluation_status=status,
            deterministic_verdict=verdict,
            reasons=reasons,
            rule_ids=rule_ids,
            evidence_ids=evidence_ids,
            evidence_set_digest=evidence_set_digest(retrieved_records),
            elements=elements,
            materiality=claim.materiality,
            materiality_origin="caller",
        ),
        None,
    )


def compose_overall(evaluations: list[ClaimEvaluation]) -> dict[str, Any]:
    """Overall decision per §5E. Material = material|unknown (unknown defaults)."""
    material = [e for e in evaluations if e.materiality in ("material", "unknown")]
    non_material = [e for e in evaluations if e.materiality == "non_material"]
    if not material:
        return {
            "overall_decision": "ABSTAIN",
            "overall_reasons": ["NO_MATERIAL_CLAIMS"],
            "overall_scope": "submitted_claims_only",
            "material_claim_ids": [],
            "non_material_claim_ids": [e.claim.claim_id for e in non_material],
        }

    def _state(e: ClaimEvaluation) -> str:
        if e.evaluation_status == "UNRESOLVED":
            return "UNRESOLVED"
        return e.deterministic_verdict or "UNRESOLVED"

    material_states = [_state(e) for e in material]
    if all(s == "SUPPORTED" for s in material_states):
        decision, reasons = "PASS", ["ALL_MATERIAL_CLAIMS_SUPPORTED"]
    elif all(s in ("SUPPORTED", "PARTIALLY_SUPPORTED", "CONTRADICTED") for s in material_states) and any(
        s in ("PARTIALLY_SUPPORTED", "CONTRADICTED") for s in material_states
    ):
        decision = "REVISE"
        reasons = sorted({s for s in material_states if s in ("PARTIALLY_SUPPORTED", "CONTRADICTED")})
        reasons = [f"MATERIAL_CLAIM_{r}" for r in reasons]
    else:
        decision = "ABSTAIN"
        reasons = sorted({f"MATERIAL_CLAIM_{s}" for s in material_states if s in ("UNSUPPORTED", "UNRESOLVED")})
        if not reasons:
            reasons = ["ABSTENTION_CONDITION"]

    return {
        "overall_decision": decision,
        "overall_reasons": reasons,
        "overall_scope": "submitted_claims_only",
        "material_claim_ids": [e.claim.claim_id for e in material],
        "non_material_claim_ids": [e.claim.claim_id for e in non_material],
    }
