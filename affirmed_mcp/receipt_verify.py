"""Receipt integrity verification (spec §8E — independent inspection).

Recomputes every deterministic digest from the receipt's own content and
compares against the recorded values. Timestamps, semantic blocks, and log
metadata are excluded from the deterministic digest, so verification is
byte-stable. Verification checks receipt integrity; it does not re-run
verification and does not establish the truth of the underlying evidence.
"""

from __future__ import annotations

from typing import Any

from .canonical import digest
from .receipt import deterministic_digest_block
from .retrieval import evidence_set_digest
from .schema import record_digest

VERIFICATION_OK = "RECEIPT_VERIFIED"
VERIFICATION_FAILED = "RECEIPT_DIGEST_MISMATCH"

# Fields that must survive round-trip canonicalization to recompute digests.
_RECORD_FIELDS = (
    "id", "text", "source", "tags", "subject_id", "subject_name",
    "field_name", "field_value", "field_type", "field_unit",
    "valid_from", "valid_to", "geo_scope", "availability_schedule",
    "quantifier_scope", "exceptions", "source_published_at",
    "source_effective_at", "source_name", "source_authority",
    "source_url_or_reference", "source_record_version",
)


def _reconstruct_record(entry: dict[str, Any]) -> dict[str, Any]:
    """Best-effort reconstruction of the canonical record from receipt fields."""
    record: dict[str, Any] = {}
    for field in _RECORD_FIELDS:
        if field in entry and entry[field] is not None:
            record[field] = entry[field]
    return record


def verify_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Recompute deterministic digests; return per-check results."""
    checks: list[dict[str, Any]] = []

    def check(name: str, recorded: Any, recomputed: Any) -> None:
        checks.append({
            "field": name,
            "recorded": recorded,
            "recomputed": recomputed,
            "match": recorded == recomputed,
        })

    # --- Whole-receipt deterministic digest --------------------------- #
    recomputed_deterministic = deterministic_digest_block(receipt)
    check("deterministic_digest", receipt.get("deterministic_digest"), recomputed_deterministic)

    # --- Per-claim digests --------------------------------------------- #
    # Record-level digests can only be recomputed when the receipt embeds the
    # full canonical record fields (spec §8E). Our compact receipts embed
    # stable IDs, digests, source references and dates only — those record
    # digests are integrity anchors that require access to the identified
    # source snapshot to re-derive, and we say so rather than faking a check.
    requires_source_access: list[str] = []
    for claim in receipt.get("claims", []) or []:
        cid = claim.get("claim_id")
        records = claim.get("records", []) or []
        full_records = [r for r in records if r.get("text")]
        if full_records and len(full_records) == len(records):
            recomputed_esd = evidence_set_digest([_reconstruct_record(r) for r in records])
            check(f"claim[{cid}].evidence_set_digest",
                  claim.get("evidence_set_digest"), recomputed_esd)
            for entry in records:
                recomputed_rd = record_digest(_reconstruct_record(entry))
                check(f"claim[{cid}].record[{entry.get('id')}].record_digest",
                      entry.get("record_digest"), recomputed_rd)
        elif records:
            requires_source_access.append(cid)

    all_match = all(c["match"] for c in checks)
    return {
        "status": VERIFICATION_OK if all_match else VERIFICATION_FAILED,
        "receipt_schema_version": receipt.get("receipt_schema_version"),
        "note": (
            "Digest integrity verified against receipt content. This checks "
            "integrity relative to recorded inputs; it does not establish the "
            "truth or authority of the underlying evidence, and it does not "
            "re-run verification."
        ),
        "deterministic_digest_excludes": ["timestamp", "semantic", "log", "advisory_metadata"],
        "record_digests_require_source_snapshot": requires_source_access,
        "checks": checks,
        "mismatches": [c["field"] for c in checks if not c["match"]],
        "limitations": [
            "Compact receipts embed record IDs, digests, source references and dates, "
            "not full source text; reconstructing those record digests requires access "
            "to the identified source snapshot.",
        ],
    }
