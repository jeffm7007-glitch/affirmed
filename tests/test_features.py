"""Tests for claim-feature extraction (criteria #27–32 support: types, negation, availability)."""

from __future__ import annotations

from affirmed_mcp.features import extract_features


class TestClaimType:
    def test_numeric_assertion(self):
        f = extract_features("Towing costs $75.")
        assert f.claim_type == "numeric_assertion"
        assert any(n.value == 75 for n in f.numbers)

    def test_availability(self):
        f = extract_features("Lockout service is available 24/7.")
        assert f.claim_type == "availability"
        assert f.availability == "always"

    def test_negated_service(self):
        f = extract_features("We do not offer fuel delivery.")
        assert f.negated is True
        assert f.negation_span

    def test_unmapped(self):
        f = extract_features("Reliable service.")
        # 'reliable' trips the unsupported-reasoning rule; both classifications
        # must be treated as unmapped by the verifier (no verdict possible).
        assert f.claim_type in ("unmapped", "unsupported_reasoning")


class TestRulesRecorded:
    def test_numeric_rule_in_rules(self):
        f = extract_features("Towing costs $75.")
        assert "RULE_NUMERIC_TOKEN" in f.rules or any("NUMERIC" in r for r in f.rules)

    def test_to_dict_shape(self):
        f = extract_features("Towing costs $75.")
        d = f.to_dict()
        assert d["claim_type"] == f.claim_type
        assert isinstance(d["numbers"], list)
        assert d["numbers"][0]["value"] == 75


class TestQuantifier:
    def test_quantified_numeric(self):
        f = extract_features("Towing costs at least $50.")
        assert f.claim_type == "quantified_numeric"
        assert f.quantifier == "at least"


class TestCandidateFields:
    def test_towing_field_candidates(self):
        f = extract_features("Towing costs $75.")
        assert any("towing" in c for c in f.candidate_fields)
