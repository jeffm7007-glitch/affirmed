"""Receipt construction + verification tests (criteria #36, #37, #38, #49, #58)."""

from __future__ import annotations

import pytest

from affirmed_mcp.receipt_verify import VERIFICATION_FAILED, VERIFICATION_OK, verify_receipt
from affirmed_mcp.semantic import SEMANTIC_REPRODUCIBILITY_LABEL


def _verify(service, **kw):
    return service.verify_answer(
        answer=kw.pop("answer", "Towing costs $75."),
        claims=kw.pop("claims", [{"claim_id": "c1", "text": "Towing costs $75.", "materiality": "material"}]),
        as_of=kw.pop("as_of", "2026-06-01T00:00:00Z"),
        **kw,
    )


def test_receipt_required_fields_present(service):
    """#36/#49: receipt carries digests, snapshot, per-claim evidence digests, versions, policy, rules, limitations."""
    result = _verify(service)
    receipt = result["receipt"]
    assert receipt["answer_digest"].startswith("sha256:")
    assert receipt["submitted_claims_digest"].startswith("sha256:")
    assert receipt["source"]["source_snapshot_id"].startswith("sha256:")
    assert receipt["source"]["snapshot_method"] == "full_export_sha256"
    claim = receipt["claims"][0]
    assert claim["evidence_set_digest"].startswith("sha256:")
    assert claim["rule_ids"], "rules must be recorded"
    assert receipt["operation_evidence_digest"].startswith("sha256:")
    assert receipt["as_of"] == "2026-06-01T00:00:00Z"
    assert receipt["versions"]
    assert receipt["policy"]["config_hash"].startswith("sha256:")
    assert receipt["limitations"], "fixed limitations array must be present"
    assert receipt["deterministic_digest"].startswith("sha256:")


def test_verify_receipt_ok_and_tamper(service):
    """#37: an unmodified receipt verifies; any content change fails."""
    result = _verify(service)
    receipt = result["receipt"]
    assert verify_receipt(receipt)["status"] == VERIFICATION_OK
    import copy

    tampered = copy.deepcopy(receipt)
    tampered["as_of"] = "2027-01-01T00:00:00Z"
    assert verify_receipt(tampered)["status"] == VERIFICATION_FAILED


def test_deterministic_digest_excludes_timestamp(service, monkeypatch):
    """#37: two runs with different wall-clock timestamps but pinned inputs share the digest."""
    from affirmed_mcp import service as service_mod

    result1 = _verify(service)
    monkeypatch.setattr(service_mod, "_utc_now", lambda: "2099-01-01T00:00:00Z")
    result2 = _verify(service)
    assert result1["receipt"]["timestamp"] != result2["receipt"]["timestamp"]
    assert result1["receipt"]["deterministic_digest"] == result2["receipt"]["deterministic_digest"]


def test_semantic_digest_labeled_logged_not_guaranteed(scripted_service):
    """#38: with advisory present, the semantic component is labeled not-reproducible."""
    result = scripted_service.verify_answer(
        answer="Towing costs $75.",
        claims=[{"claim_id": "c1", "text": "Towing costs $75.", "materiality": "material"}],
        audit_mode="semantic",
        as_of="2026-06-01T00:00:00Z",
    )
    semantic = result["receipt"]["semantic"]
    assert semantic is not None
    # The semantic component is labeled not-reproducible in both places.
    assert semantic["semantic_digest_label"] == SEMANTIC_REPRODUCIBILITY_LABEL
    from affirmed_mcp.receipt import SEMANTIC_REPRODUCIBILITY
    assert result["receipt"]["reproducibility"]["semantic"] == SEMANTIC_REPRODUCIBILITY


def test_operation_evidence_digest_tracks_evidence(service):
    """#58: the operation digest changes when an evaluated claim's ordered evidence set changes."""
    r1 = _verify(service)
    r2 = _verify(service, claims=[
        {"claim_id": "c1", "text": "Towing costs $75.", "materiality": "material"},
        {"claim_id": "c2", "text": "Fuel delivery costs at least $40.", "materiality": "material"},
    ])
    assert r1["receipt"]["operation_evidence_digest"] != r2["receipt"]["operation_evidence_digest"]


def test_abstention_receipt_still_verifiable(service):
    result = service.verify_answer(answer="x.", claims=[], as_of="2026-06-01T00:00:00Z")
    assert result["receipt"]["abstention"]["code"] == "CLAIMS_REQUIRED"
    assert result["receipt"]["overall_decision"] == "ABSTAIN"
    assert verify_receipt(result["receipt"])["status"] == VERIFICATION_OK
