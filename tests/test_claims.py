"""Claim contract tests (criteria #5, #6, #7, #51, #52, #53, #54-partial)."""

from __future__ import annotations

import pytest

from affirmed_mcp.claims import (
    check_atomicity,
    parse_and_validate_claims,
    suggest_claims_for_answer,
    submitted_claims_digest,
    suggestion_set_digest,
    suggestion_texts_digest,
    verify_top_level_request,
)
from affirmed_mcp.config import Policy
from affirmed_mcp.errors import ServiceError


def test_missing_claims_abstain():
    parsed, abstention = parse_and_validate_claims(None, Policy())
    assert parsed is None
    assert abstention.code == "CLAIMS_REQUIRED"
    parsed, abstention = parse_and_validate_claims([], Policy())
    assert abstention.code == "CLAIMS_REQUIRED"


def test_malformed_claims_abstain_with_affected_ids():
    claims = [
        {"claim_id": "ok-1", "text": "Towing costs $75.", "materiality": "material"},
        {"claim_id": "bad-1", "text": "", "materiality": "material"},
    ]
    parsed, abstention = parse_and_validate_claims(claims, Policy())
    assert parsed is None
    assert abstention.code == "CLAIMS_MALFORMED"
    assert "bad-1" in abstention.affected_claim_ids


def test_unknown_claim_fields_rejected():
    claims = [{"claim_id": "c1", "text": "x.", "materiality": "material", "trust_me": True}]
    parsed, abstention = parse_and_validate_claims(claims, Policy())
    assert parsed is None
    assert abstention.code == "CLAIMS_MALFORMED"


def test_claim_text_and_id_bounds():
    policy = Policy()
    too_long = [{"claim_id": "c1", "text": "x" * 1001, "materiality": "material"}]
    parsed, abstention = parse_and_validate_claims(too_long, policy)
    assert abstention is not None and abstention.code == "CLAIMS_MALFORMED"
    bad_id = [{"claim_id": "no spaces allowed", "text": "x.", "materiality": "material"}]
    parsed, abstention = parse_and_validate_claims(bad_id, policy)
    assert abstention is not None


def test_non_atomic_claims_not_silently_split():
    """#6/#52: compound claims abstain with suggestions; never auto-split+verified."""
    claims = [{"claim_id": "c1", "text": "Towing costs $75 and fuel delivery costs $45.", "materiality": "material"}]
    parsed, abstention = parse_and_validate_claims(claims, Policy())
    assert abstention is None  # structurally valid
    atomicity = check_atomicity(parsed)
    assert atomicity is not None
    assert atomicity.code == "CLAIMS_NOT_ATOMIC"
    assert len(atomicity.suggested_claims) >= 2
    assert atomicity.suggestion_set_digest


def test_suggestions_labeled_and_digest_stable():
    suggestions = suggest_claims_for_answer("Towing costs $75. Fuel delivery costs $45.")
    assert suggestions, "expected atomic suggestions"
    for s in suggestions:
        assert s["label"] == "suggestion"
        assert s["text"].strip()
    d1 = suggestion_set_digest(suggestions)
    assert d1 == suggestion_set_digest(list(suggestions))
    assert d1.startswith("sha256:")


def test_suggestion_text_digest_matches_only_unedited_set():
    suggestions = suggest_claims_for_answer("Towing costs $75. Fuel delivery costs $45.")
    texts = [s["text"] for s in suggestions]
    assert suggestion_texts_digest(texts) == suggestion_texts_digest(list(texts))
    assert suggestion_texts_digest(texts) != suggestion_texts_digest(texts[:1])


def test_submitted_claims_digest_covers_canonical_claims():
    claims = [{"claim_id": "c1", "text": "Towing costs $75.", "materiality": "material"}]
    parsed, _ = parse_and_validate_claims(claims, Policy())
    d1 = submitted_claims_digest(parsed)
    assert d1.startswith("sha256:")
    parsed2, _ = parse_and_validate_claims(claims, Policy())
    assert submitted_claims_digest(parsed2) == d1


def test_top_level_unknown_fields_rejected():
    with pytest.raises(ServiceError) as exc:
        verify_top_level_request({"query": "x", "policy_overrides": {}}, {"query"}, "retrieve_evidence")
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details["unknown_fields"] == ["policy_overrides"]
    assert verify_top_level_request({"query": "x"}, {"query"}, "retrieve_evidence") == {"query": "x"}
    with pytest.raises(ServiceError):
        verify_top_level_request(["not", "a", "dict"], {"query"}, "retrieve_evidence")
