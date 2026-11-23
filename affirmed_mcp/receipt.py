"""Receipt renderer and deterministic digest (spec §8).

Required fields stay present on early domain abstention; fields that cannot be
established are null with an explicit reason. Zero/empty digests are never
substituted as though source or evidence work occurred.
"""

from __future__ import annotations

from typing import Any

from . import (
    CANONICALIZATION_VERSION,
    CONTRACT_VERSION,
    FIXED_LIMITATIONS,
    RECEIPT_SCHEMA_VERSION,
    RETRIEVAL_VERSION,
    SCHEMA_VERSION,
    SOFTWARE_VERSION,
    TOKENIZER_VERSION,
    VERIFIER_VERSION,
)
from .canonical import digest
from .config import Policy

DETERMINISTIC_REPRODUCIBILITY = "byte-identical-for-identical-pinned-inputs"
SEMANTIC_REPRODUCIBILITY = "logged-not-guaranteed-reproducible"


def build_versions(policy: Policy) -> dict[str, str]:
    return {
        "software_version": SOFTWARE_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "tokenizer_version": TOKENIZER_VERSION,
        "retrieval_version": RETRIEVAL_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "policy_version": policy.policy_version,
        "contract_version": CONTRACT_VERSION,
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
    }


def build_policy_block(policy: Policy, name: str = "default") -> dict[str, Any]:
    return {
        "policy_name": name,
        "policy_version": policy.policy_version,
        "accepted_config": policy.to_dict(),
        "config_hash": policy.config_hash,
        "request_overrides": "none",
    }


def deterministic_digest_block(receipt: dict[str, Any]) -> str:
    """SHA-256 over the deterministic verification identity (spec §8B).

    Excludes wall-clock receipt timestamps, semantic data, and incidental log
    metadata. Included: contract version, code/verifier version, as_of,
    answer/submitted-claims digests, coverage attestation, materiality origins,
    source snapshot ID, operation evidence digest, policy identity, settings,
    schema/tokenizer/retrieval/canonicalization versions, accepted config hash.
    """
    identity = {
        "contract_version": receipt["contract_version"],
        "software_version": SOFTWARE_VERSION,
        "verifier_version": VERIFIER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "tokenizer_version": TOKENIZER_VERSION,
        "retrieval_version": RETRIEVAL_VERSION,
        "canonicalization_version": CANONICALIZATION_VERSION,
        "policy_version": receipt["policy"]["policy_version"],
        "policy_config_hash": receipt["policy"]["config_hash"],
        "as_of": receipt["as_of"],
        "answer_digest": receipt["answer_digest"],
        "submitted_claims_digest": receipt["submitted_claims_digest"],
        "claim_coverage": receipt["claim_coverage"],
        "materiality_origins": {
            c["claim_id"]: c["materiality_origin"] for c in receipt.get("claims", [])
        },
        "source_snapshot_id": receipt["source"]["source_snapshot_id"],
        "operation_evidence_digest": receipt["operation_evidence_digest"],
        "overall_scope": receipt["overall_scope"],
    }
    return digest(identity)


def build_receipt(
    *,
    policy: Policy,
    timestamp: str,
    as_of: str,
    answer_digest: str | None,
    submitted_claims_digest: str | None,
    claim_coverage: dict[str, Any],
    claims_source: str,
    suggestion_set_digest: str | None,
    claims: list[dict[str, Any]],
    retrieval: dict[str, Any] | None,
    operation_evidence_digest: str | None,
    operation_evidence_digest_reason: str | None,
    source: dict[str, Any],
    semantic: dict[str, Any] | None,
    injection_suspected: bool,
    advisory_status: str | None,
    freshness: dict[str, Any],
    overall_decision: str,
    overall_reasons: list[str],
    overall_scope: str,
    verification_class: str,
    warnings: list[str],
    abstention: dict[str, Any] | None = None,
) -> dict[str, Any]:
    receipt: dict[str, Any] = {
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
        "timestamp": timestamp,
        "contract_version": CONTRACT_VERSION,
        "answer_digest": answer_digest,
        "submitted_claims_digest": submitted_claims_digest,
        "claim_coverage": claim_coverage,
        "claims_source": claims_source,
        "suggestion_set_digest": suggestion_set_digest,
        "claims": claims,
        "retrieval": retrieval,
        "operation_evidence_digest": operation_evidence_digest,
        "operation_evidence_digest_reason": operation_evidence_digest_reason,
        "source": source,
        "as_of": as_of,
        "versions": build_versions(policy),
        "semantic": semantic,
        "injection_suspected": injection_suspected,
        "advisory_status": advisory_status,
        "policy": build_policy_block(policy),
        "freshness": freshness,
        "overall_decision": overall_decision,
        "overall_reasons": overall_reasons,
        "overall_scope": overall_scope,
        "verification_class": verification_class,
        "limitations": list(FIXED_LIMITATIONS),
        "reproducibility": {
            "deterministic": DETERMINISTIC_REPRODUCIBILITY,
            "semantic": SEMANTIC_REPRODUCIBILITY,
        },
        "warnings": warnings,
    }
    if abstention is not None:
        receipt["abstention"] = abstention
    receipt["deterministic_digest"] = deterministic_digest_block(receipt)
    return receipt


def null_reason(field: str, reason: str) -> dict[str, Any]:
    return {"field": field, "value": None, "reason": reason}
