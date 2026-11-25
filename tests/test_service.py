"""Service-layer tests (criteria #3, #4, #5, #21, #22, #30, #33–35, #39, #46, #50, #53–56, #61)."""

from __future__ import annotations

import sqlite3

import pytest

from affirmed_mcp.errors import SNAPSHOT_MISMATCH, ServiceError
from affirmed_mcp.source import open_source

AS_OF = "2026-06-01T00:00:00Z"
CLAIM = [{"claim_id": "c1", "text": "Towing costs $75.", "materiality": "material"}]


def test_retrieve_evidence_bounds(service):
    with pytest.raises(ServiceError) as exc:
        service.retrieve_evidence("")
    assert exc.value.code == "INVALID_INPUT"
    with pytest.raises(ServiceError):
        service.retrieve_evidence("x" * 5001)
    with pytest.raises(ServiceError):
        service.retrieve_evidence("towing", limit=0)
    with pytest.raises(ServiceError):
        service.retrieve_evidence("towing", limit=51)
    with pytest.raises(ServiceError):
        service.retrieve_evidence("towing", limit=True)  # bool is not an int here
    out = service.retrieve_evidence("towing", limit=2, as_of=AS_OF)
    assert out["source_snapshot_id"].startswith("sha256:")
    assert len(out["records"]) == 2


def test_snapshot_id_query_independent(service):
    """#22: the snapshot identity does not depend on the query."""
    a = service.retrieve_evidence("towing", as_of=AS_OF)
    b = service.retrieve_evidence("fuel delivery costs", as_of=AS_OF)
    c = service.get_source_status()
    assert a["source_snapshot_id"] == b["source_snapshot_id"] == c["source_snapshot_id"]


def test_snapshot_mismatch_abstentions(service):
    """#21: verify_answer -> ABSTAIN/SNAPSHOT_MISMATCH; retrieve_evidence -> stable error, no evidence."""
    status = service.get_source_status()
    current = status["source_snapshot_id"]

    with pytest.raises(ServiceError) as exc:
        service.retrieve_evidence("towing", expected_source_snapshot_id="sha256:deadbeef")
    assert exc.value.code == SNAPSHOT_MISMATCH
    assert exc.value.details["current"] == current

    out = service.verify_answer(
        answer="Towing costs $75.",
        claims=CLAIM,
        expected_source_snapshot_id="sha256:deadbeef",
        as_of=AS_OF,
    )
    receipt = out["receipt"]
    assert receipt["overall_decision"] == "ABSTAIN"
    assert receipt["abstention"]["code"] == SNAPSHOT_MISMATCH
    assert receipt["claims"] == [] or all(c["deterministic_verdict"] is None for c in receipt["claims"])


def test_missing_claims_abstain_receipt(service):
    out = service.verify_answer(answer="Something.", claims=None, as_of=AS_OF)
    assert out["receipt"]["overall_decision"] == "ABSTAIN"
    assert out["receipt"]["abstention"]["code"] == "CLAIMS_REQUIRED"


def test_verify_answer_bounds(service):
    with pytest.raises(ServiceError):
        service.verify_answer(answer="")
    with pytest.raises(ServiceError):
        service.verify_answer(answer="x" * 8001)
    with pytest.raises(ServiceError):
        service.verify_answer(answer="x.", claims=CLAIM, audit_mode="trust_me")
    with pytest.raises(ServiceError):
        service.verify_answer(answer="x.", claims=CLAIM, as_of="not a time")
    too_many = [dict(CLAIM[0], claim_id=f"c{i}") for i in range(65)]  # HARD_MAX_CLAIMS = 64
    with pytest.raises(ServiceError) as exc:
        service.verify_answer(answer="x.", claims=too_many, as_of=AS_OF)
    assert "maximum" in str(exc.value.message)


def test_error_envelope_no_stack_trace(service):
    """#46: stable envelope, no internals leaked."""
    try:
        service.retrieve_evidence("")
        pytest.fail("expected ServiceError")
    except ServiceError as exc:
        env = exc.to_envelope()
    blob = str(env)
    assert "Traceback" not in blob
    assert "File \"" not in blob
    assert env["code"] == "INVALID_INPUT"


def test_prevalidation_vs_abstention_distinct(service):
    """#54: pre-validation errors raise; domain abstentions return receipts."""
    with pytest.raises(ServiceError):
        service.verify_answer(answer="", as_of=AS_OF)  # pre-validation
    out = service.verify_answer(answer="x.", claims=[], as_of=AS_OF)  # abstention w/ receipt
    assert out["receipt"]["abstention"]["code"] == "CLAIMS_REQUIRED"


def test_coverage_invariants(service):
    """#33: never reviewed_complete; always submitted_claims_only."""
    out = service.verify_answer(answer="Towing costs $75.", claims=CLAIM, as_of=AS_OF)
    receipt = out["receipt"]
    assert receipt["overall_scope"] == "submitted_claims_only"
    coverage = receipt["claim_coverage"]
    assert coverage["status"] in ("partial_or_unknown", "unknown")
    assert "complete" not in coverage["status"]
    assert coverage["method"] == "submitted_claims_only"


def test_completeness_attestation_caller_labeled(service):
    """#34: caller attestation is labeled caller-provided, never system-verified."""
    out = service.verify_answer(
        answer="Towing costs $75.", claims=CLAIM,
        caller_attested_complete=True, as_of=AS_OF,
    )
    coverage = out["receipt"]["claim_coverage"]
    assert coverage["caller_attested_complete"] is True
    assert "caller" in coverage["method"]
    assert "not system-verified" in coverage["note"]


def test_as_of_recorded_in_receipt(service):
    """#61: as_of is recorded and pinned."""
    out = service.verify_answer(answer="Towing costs $75.", claims=CLAIM, as_of=AS_OF)
    assert out["receipt"]["as_of"] == AS_OF


def test_file_age_disabled_by_default(service):
    """#39: file-age warning off by default; freshness is a warning, not a fact."""
    status = service.get_source_status()
    assert status["file_staleness_warning"] is None or status["file_staleness_warning"].get("enabled") is False
    out = service.retrieve_evidence("towing", as_of=AS_OF)
    assert "evidence_freshness_warning" in out["freshness"]


def test_suggestions_require_acceptance(service):
    """#53: suggested claims need claims_source=suggested_accepted + matching digest."""
    out = service.verify_answer(
        answer="Towing costs $75 and fuel delivery costs $45.",
        claims=[
            {"claim_id": "s1", "text": "Towing costs $75.", "materiality": "material", "label": "suggestion"},
            {"claim_id": "s2", "text": "Fuel delivery costs $45.", "materiality": "material", "label": "suggestion"},
        ],
        as_of=AS_OF,
    )
    # Suggestions came back labeled and overall cannot PASS on raw suggestions.
    assert out["receipt"]["overall_decision"] != "PASS"
    # Explicit resubmission with claims_source=suggested_accepted + digest works.
    from affirmed_mcp.claims import suggest_claims_for_answer, suggestion_texts_digest
    suggestions = suggest_claims_for_answer("Towing costs $75.")
    digest_value = suggestion_texts_digest([s["text"] for s in suggestions])
    claims = [{"claim_id": s["suggestion_id"], "text": s["text"], "materiality": "material"}
                for s in suggestions]
    out2 = service.verify_answer(
        answer="Towing costs $75.", claims=claims,
        claims_source="suggested_accepted", suggestion_set_digest=digest_value, as_of=AS_OF,
    )
    assert out2["receipt"]["overall_decision"] == "PASS"
    with pytest.raises(ServiceError):
        service.verify_answer(answer="x.", claims=claims, claims_source="suggested_accepted",
                              suggestion_set_digest="sha256:nope", as_of=AS_OF)


def test_conflict_abstains_safely(tmp_path):
    """#30: two applicable same-authority records with different values -> no PASS."""
    import json

    from affirmed_mcp.demo_data import build_demo_db

    path = str(tmp_path / "conflict.db")
    build_demo_db(path)
    w = sqlite3.connect(path)
    w.execute(
        "INSERT INTO evidence_records (id, text, source, tags, subject_id, field_name, field_value,"
        " field_type, field_unit, source_authority) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("r_conflict", "Towing costs $90 according to a second primary sheet.",
         "second sheet", json.dumps([]), "cascade", "towing_price",
         "90", "number", "USD", "primary_official"),
    )
    w.commit()
    w.close()

    from affirmed_mcp.config import Policy
    from affirmed_mcp.service import AffirmedService

    svc = AffirmedService(Policy(source_path=path))
    out = svc.verify_answer(answer="Towing costs $75.", claims=CLAIM, as_of=AS_OF)
    receipt = out["receipt"]
    assert receipt["overall_decision"] != "PASS"
    claim = receipt["claims"][0]
    # Unresolvable same-authority conflict must not yield a positive verdict.
    assert claim["deterministic_verdict"] in ("UNSUPPORTED", None)


def test_get_source_status_shape(service):
    status = service.get_source_status()
    assert status["schema_version"] == "1"
    assert status["snapshot_method"] == "full_export_sha256"
    assert status["last_sync_time"] is None
    assert status["last_sync_time_reason"] == "read_only_source_no_sync"


def test_advisory_unavailable_warning(service):
    """#55: default audit mode is deterministic and needs no provider."""
    out = service.verify_answer(answer="Towing costs $75.", claims=CLAIM, as_of=AS_OF)
    assert out["receipt"]["advisory_status"] in (None, "ADVISORY_NOT_RUN")
    assert out["receipt"]["semantic"] is None or out["receipt"]["semantic"].get("simulated_label") is None


def test_scripted_overreach_cannot_promote(scripted_service):
    """#10/#19: scripted POSSIBLE_ALIGNMENT cannot turn UNSUPPORTED into anything else."""
    out = scripted_service.verify_answer(
        answer="Lockout service is available 24/7.",
        claims=[{"claim_id": "c1", "text": "Lockout service is available 24/7.", "materiality": "material"}],
        audit_mode="semantic",
        as_of=AS_OF,
    )
    receipt = out["receipt"]
    claim = receipt["claims"][0]
    assert claim["deterministic_verdict"] in ("UNSUPPORTED", None)
    assert receipt["overall_decision"] != "PASS"
    assert receipt["semantic"]["simulated_label"]


def test_scenario_d_untrusted_evidence_safe_failure(scripted_service):
    """#14/#20: injection markers in evidence keep the deterministic result; advisory untrusted."""
    out = scripted_service.verify_answer(
        answer="Towing is available 24/7.",
        claims=[{"claim_id": "c1", "text": "Towing is available 24/7.", "materiality": "material"}],
        audit_mode="semantic",
        as_of=AS_OF,
    )
    receipt = out["receipt"]
    assert receipt["claims"][0]["deterministic_verdict"] == "SUPPORTED"  # deterministic unaffected
    assert receipt["injection_suspected"] is True
    assert receipt["semantic"]["per_claim"][0]["advisory_status"] == "ADVISORY_UNTRUSTED"
