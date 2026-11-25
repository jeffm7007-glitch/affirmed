"""Local Policy configuration tests (criteria #40, #41, #51-partial)."""

from __future__ import annotations

import pytest

from affirmed_mcp.config import Policy, versioned_component_versions
from affirmed_mcp.errors import ServiceError


def test_default_policy_validates():
    policy = Policy()
    assert policy.config_hash.startswith("sha256:")
    assert policy.semantic_can_promote_verdict is False
    assert policy.claim_coverage_default == "partial_or_unknown"
    assert policy.materiality_unknown_default == "material"


def test_unknown_policy_fields_fail_closed():
    with pytest.raises(ServiceError) as exc:
        Policy.from_dict({"not_a_real_field": 1})
    assert exc.value.code == "INVALID_INPUT"
    assert exc.value.details["unknown_fields"] == ["not_a_real_field"]


def test_unsafe_policy_values_rejected():
    with pytest.raises(ServiceError):
        Policy(retrieve_limit=0)
    with pytest.raises(ServiceError):
        Policy(retrieve_limit=10_000)
    with pytest.raises(ServiceError):
        Policy(audit_default_mode="trust_the_model")
    with pytest.raises(ServiceError):
        Policy(source_snapshot_method="whatever")
    with pytest.raises(ServiceError):
        Policy(semantic_can_promote_verdict=True)  # hard invariant
    with pytest.raises(ServiceError):
        Policy(claim_coverage_default="reviewed_complete")
    with pytest.raises(ServiceError):
        Policy(materiality_unknown_default="non_material")
    with pytest.raises(ServiceError):
        Policy(audit_max_retries=99)


def test_policy_load_from_file_and_override(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text('{"retrieve_limit": 3}')
    policy = Policy.load(str(path))
    assert policy.retrieve_limit == 3
    policy = Policy.load(str(path), retrieve_limit=7)
    assert policy.retrieve_limit == 7
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ServiceError):
        Policy.load(str(bad))
    missing = tmp_path / "missing.json"
    with pytest.raises(ServiceError):
        Policy.load(str(missing))


def test_config_hash_covers_accepted_config():
    a = Policy(retrieve_limit=5)
    b = Policy(retrieve_limit=6)
    assert a.config_hash != b.config_hash
    assert Policy(retrieve_limit=5).config_hash == a.config_hash


def test_component_version_map_complete():
    versions = versioned_component_versions()
    for key in ("tokenizer_version", "retrieval_version", "canonicalization_version", "policy_version"):
        assert key in versions
