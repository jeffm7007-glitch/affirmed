"""Deterministic verifier tests (criteria #16, #27–32, #35, #60, #61)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from affirmed_mcp.claims import parse_and_validate_claims
from affirmed_mcp.config import Policy
from affirmed_mcp.retrieval import LexicalIndex
from affirmed_mcp.source import load_all_records, open_source
from affirmed_mcp.verifier import (
    REQUIRED_FIELD_MISSING,
    RULE_AVAILABILITY_COMPARISON,
    compose_overall,
    evaluate_claim,
    parse_as_of,
)

AS_OF = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _mk(policy, text, materiality="material"):
    claims = [{"claim_id": "c1", "text": text, "materiality": materiality}]
    parsed, _ = parse_and_validate_claims(claims, policy)
    return parsed[0]


def _index(demo_db_path):
    conn = open_source(demo_db_path)
    try:
        records = load_all_records(conn)[0]
    finally:
        conn.close()
    return LexicalIndex(records)


def _eval(policy, index, text, materiality="material"):
    claim = _mk(policy, text, materiality)
    retrieved, _, _ = index.search(claim.text, policy.retrieve_limit)
    evaluation, ambiguity = evaluate_claim(claim, retrieved, policy, AS_OF)
    return evaluation, ambiguity, retrieved


def test_supported_claim_uses_typed_field_with_applicability(policy, demo_db_path):
    """#27: SUPPORTED comes from an applicable typed field, with the rule recorded."""
    index = _index(demo_db_path)
    evaluation, _, _ = _eval(policy, index, "Towing is available 24/7.")
    assert evaluation.deterministic_verdict == "SUPPORTED"
    assert RULE_AVAILABILITY_COMPARISON in evaluation.rule_ids
    assert evaluation.evidence_ids, "evidence IDs must be cited"


def test_scenario_a_missing_typed_field_no_text_upgrade(policy, demo_db_path):
    """#17/#28: 24/7 availability with only a string field -> UNSUPPORTED, never upgraded."""
    index = _index(demo_db_path)
    evaluation, ambiguity, _ = _eval(policy, index, "Cascade offers 24/7 customer support by phone.")
    assert ambiguity is None
    assert evaluation.evaluation_status == "EVALUATED"
    assert evaluation.deterministic_verdict == "UNSUPPORTED"
    assert REQUIRED_FIELD_MISSING in evaluation.reasons


def test_numeric_match_and_contradiction(policy, demo_db_path):
    index = _index(demo_db_path)
    ok, _, _ = _eval(policy, index, "Towing costs $75.")
    assert ok.deterministic_verdict == "SUPPORTED"
    bad, _, _ = _eval(policy, index, "Towing costs $85.")
    assert bad.deterministic_verdict == "CONTRADICTED"
    cmp_up, _, _ = _eval(policy, index, "Fuel delivery costs up to $40.")
    assert cmp_up.deterministic_verdict == "CONTRADICTED"
    cmp_down, _, _ = _eval(policy, index, "Fuel delivery costs at least $40.")
    assert cmp_down.deterministic_verdict == "SUPPORTED"


def test_geo_match_and_contradiction(policy, demo_db_path):
    index = _index(demo_db_path)
    ok, _, _ = _eval(policy, index, "Service is available in Tampa.")
    assert ok.deterministic_verdict == "SUPPORTED"
    bad, _, _ = _eval(policy, index, "Service is available in Miami.")
    assert bad.deterministic_verdict == "CONTRADICTED"


def test_text_overlap_alone_never_verifies_availability(policy, demo_db_path):
    """#29: paraphrase-y text without a typed field cannot verify."""
    index = _index(demo_db_path)
    evaluation, _, _ = _eval(policy, index, "You can get help at any hour, day or night.")
    assert evaluation.deterministic_verdict == "UNSUPPORTED"


def test_unsupported_reasoning_unresolvable(policy, demo_db_path):
    """#60: 'best' claim -> UNRESOLVED with FEATURE_UNVERIFIABLE, no verdict."""
    index = _index(demo_db_path)
    evaluation, ambiguity, _ = _eval(policy, index, "Cascade has the best roadside service in Tampa.")
    assert ambiguity is None
    assert evaluation.evaluation_status == "UNRESOLVED"
    assert evaluation.deterministic_verdict is None
    assert "FEATURE_UNVERIFIABLE" in evaluation.reasons


def test_compose_overall_properties(policy, demo_db_path):
    """#16/#35/#50: monotonic conservative minimum; empty -> non-PASS."""
    index = _index(demo_db_path)
    empty = compose_overall([])
    assert empty["overall_decision"] != "PASS"

    supported, _, _ = _eval(policy, index, "Towing costs $75.")
    material_unsupported, _, _ = _eval(policy, index, "Lockout service is available 24/7.")

    one_pass = compose_overall([supported])
    assert one_pass["overall_decision"] == "PASS"

    # Adding a worse evaluation never improves the outcome (monotonicity).
    both = compose_overall([supported, material_unsupported])
    assert both["overall_decision"] != "PASS"
    rank = {"PASS": 3, "REVISE": 2, "ABSTAIN": 1}
    assert rank[both["overall_decision"]] <= rank[one_pass["overall_decision"]]

    # Idempotence: duplicate evaluations do not change the result.
    assert compose_overall([supported, supported])["overall_decision"] == one_pass["overall_decision"]

    # All-nonmaterial unsupported -> explicit non-PASS outcome.
    nm, _, _ = _eval(policy, index, "Lockout service is available 24/7.", materiality="non_material")
    out = compose_overall([nm])
    assert out["overall_decision"] != "PASS"
    assert out["overall_scope"] == "submitted_claims_only"


def test_materiality_unknown_defaults_material(policy, demo_db_path):
    """#31: unknown materiality is treated as material in overall composition."""
    index = _index(demo_db_path)
    evaluation, _, _ = _eval(policy, index, "Lockout service is available 24/7.", materiality="unknown")
    assert evaluation.materiality == "unknown"
    out = compose_overall([evaluation])
    # Not NO_MATERIAL_CLAIMS: unknown counts as material (mandatory default).
    assert "NO_MATERIAL_CLAIMS" not in out["overall_reasons"]
    assert out["overall_decision"] != "PASS"


def test_as_of_parsing_and_recorded():
    dt, s = parse_as_of("2026-06-01T00:00:00Z")
    assert s == "2026-06-01T00:00:00Z"
    assert dt.tzinfo is not None
    dt2, s2 = parse_as_of(None)
    assert s2  # normalized to a concrete instant string
    with pytest.raises(ValueError):
        parse_as_of("not a timestamp")
