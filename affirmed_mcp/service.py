"""Service layer: retrieve_evidence / verify_answer / get_source_status (spec §4).

Pre-validation failures raise ServiceError (INVALID_INPUT) and never start
verification. Domain abstentions after acceptance return receipts.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from . import CONTRACT_VERSION, TOKENIZER_VERSION
from .canonical import digest
from .claims import (
    CLAIM_AMBIGUOUS,
    ClaimAbstention,
    ClaimInput,
    check_atomicity,
    parse_and_validate_claims,
    submitted_claims_digest,
    suggestion_set_digest,
    verify_top_level_request,
)
from .config import Policy
from .errors import SNAPSHOT_MISMATCH, ServiceError, invalid_input
from .receipt import build_receipt
from .retrieval import GLOBAL_INDEX_CACHE, IndexCache, evidence_set_digest, retrieval_metadata
from .schema import record_digest
from .source import SourceSession, open_source, schema_version, source_file_metadata
from .verifier import compose_overall, evaluate_claim, parse_as_of

RETRIEVE_FIELDS = {"query", "limit", "expected_source_snapshot_id", "as_of"}
VERIFY_FIELDS = {
    "answer", "claims", "audit_mode", "expected_source_snapshot_id", "as_of",
    "caller_attested_complete", "claims_source", "suggestion_set_digest",
}
SOURCE_STATUS_FIELDS: set[str] = set()

_AUDIT_MODES = ("deterministic", "semantic", "auto")
_CLAIMS_SOURCES = ("caller", "suggested_accepted")
_AUTO_TRIGGER_VERDICTS = {"PARTIALLY_SUPPORTED", "UNSUPPORTED"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AffirmedService:
    def __init__(self, policy: Policy, advisor=None, index_cache: IndexCache | None = None):
        self.policy = policy
        self.advisor = advisor  # ScriptedAdvisor or OpenRouterAdvisor; None = deterministic only
        self.index_cache = index_cache if index_cache is not None else GLOBAL_INDEX_CACHE

    # ------------------------------------------------------------------ #
    def _get_index(self, snapshot_id: str, records: list[dict[str, Any]]):
        cached = self.index_cache.get(snapshot_id)
        if cached is not None:
            return cached
        from .retrieval import LexicalIndex

        index = LexicalIndex(records, k1=self.policy.bm25_k1, b=self.policy.bm25_b)
        self.index_cache.put(snapshot_id, index)
        return index

    @staticmethod
    def _freshness(source_path: str, records: list[dict[str, Any]] | None,
                   policy: Policy, as_of_str: str, warnings: list[str]) -> dict[str, Any]:
        meta = source_file_metadata(source_path)
        freshness: dict[str, Any] = {
            "source_file": meta,
            "evidence_publication_date_range": None,
            "evidence_effective_date_range": None,
            "file_staleness_warning": None,
            "evidence_freshness_warning": None,
        }
        if records:
            published = sorted({r["source_published_at"] for r in records if r.get("source_published_at")})
            effective = sorted({r["source_effective_at"] for r in records if r.get("source_effective_at")})
            if published:
                freshness["evidence_publication_date_range"] = {"min": published[0], "max": published[-1]}
            if effective:
                freshness["evidence_effective_date_range"] = {"min": effective[0], "max": effective[-1]}
        if policy.source_file_staleness_warning_s is not None and meta.get("file_mtime"):
            age = datetime.now(timezone.utc).timestamp() - meta["file_mtime"]
            if age > policy.source_file_staleness_warning_s:
                warning = {
                    "code": "SOURCE_FILE_AGE_WARNING",
                    "age_s": age,
                    "note": "local file has not changed recently; this says nothing about whether the underlying facts are current or stale",
                }
                freshness["file_staleness_warning"] = warning
                warnings.append("SOURCE_FILE_AGE_WARNING: file age exceeds configured threshold (not a factual freshness judgment)")
        return freshness

    # ------------------------------------------------------------------ #
    def retrieve_evidence(
        self,
        query: str,
        limit: int | None = None,
        expected_source_snapshot_id: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """Spec §4B. Bounds enforced; SNAPSHOT_MISMATCH returns no evidence."""
        if not isinstance(query, str) or not query.strip():
            raise invalid_input("query must be a non-blank string")
        if len(query) > self.policy.retrieve_max_query_chars:
            raise invalid_input("query exceeds maximum length")
        limit = self.policy.retrieve_limit if limit is None else limit
        if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= 50):
            raise invalid_input("limit must be an integer between 1 and 50")
        try:
            _, as_of_str = parse_as_of(as_of)
        except ValueError as exc:
            raise invalid_input("as_of must be an ISO 8601 timestamp", reason=str(exc))
        warnings: list[str] = []

        conn = open_source(self.policy.source_path or "")
        with SourceSession(conn, self.policy) as session:
            snapshot = session.resolve_snapshot(self.policy.source_path or "")
            if (
                expected_source_snapshot_id is not None
                and expected_source_snapshot_id != snapshot["source_snapshot_id"]
            ):
                raise ServiceError(
                    SNAPSHOT_MISMATCH,
                    "expected source snapshot does not match current snapshot",
                    retryable=False,
                    details={
                        "expected": expected_source_snapshot_id,
                        "current": snapshot["source_snapshot_id"],
                    },
                )
            records = snapshot["records"] or []
            warnings.extend(snapshot["load_warnings"])
            index = self._get_index(snapshot["source_snapshot_id"], records)
            retrieved, scores, diagnostics = index.search(query, limit)

        conn.close()

        records_out = []
        for rec in retrieved:
            entry = {
                "id": rec["id"],
                "text": rec["text"],
                "source": rec["source"],
                "tags": rec.get("tags", []),
                "record_digest": record_digest(rec),
            }
            for optional in (
                "subject_id", "subject_name", "field_name", "field_value", "field_type",
                "field_unit", "valid_from", "valid_to", "geo_scope", "availability_schedule",
                "quantifier_scope", "exceptions", "source_published_at", "source_effective_at",
                "source_name", "source_authority", "source_url_or_reference", "source_record_version",
            ):
                if rec.get(optional) is not None:
                    entry[optional] = rec[optional]
            records_out.append(entry)

        freshness = self._freshness(self.policy.source_path or "", records, self.policy, as_of_str, warnings)
        return {
            "contract_version": CONTRACT_VERSION,
            "source_snapshot_id": snapshot["source_snapshot_id"],
            "evidence_set_digest": evidence_set_digest(retrieved),
            "records": records_out,
            "retrieval": {
                **retrieval_metadata(query, limit, diagnostics),
                "scores": scores,
            },
            "freshness": freshness,
            "as_of": as_of_str,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------ #
    def _abstention_receipt(
        self,
        *,
        abstention: ClaimAbstention,
        answer_digest_value: str | None,
        submitted_claims_digest_value: str | None,
        submitted_digest_reason: str | None,
        claims_source: str,
        suggestion_digest: str | None,
        as_of_str: str,
        timestamp: str,
        verification_class: str = "deterministic_only",
        source: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        coverage = {
            "status": self.policy.claim_coverage_default,
            "method": "submitted_claims_only",
            "caller_attested_complete": False,
            "unassessed_assertions": None,
            "note": "Affirmed verifies submitted claims only; completeness is not inferred",
        }
        return build_receipt(
            policy=self.policy,
            timestamp=timestamp,
            as_of=as_of_str,
            answer_digest=answer_digest_value,
            submitted_claims_digest=submitted_claims_digest_value,
            claim_coverage=coverage,
            claims_source=claims_source,
            suggestion_set_digest=suggestion_digest,
            claims=[],
            retrieval=None,
            operation_evidence_digest=None,
            operation_evidence_digest_reason="no_claim_reached_evidence_retrieval",
            source=source or {
                "source_snapshot_id": None,
                "snapshot_method": self.policy.source_snapshot_method,
                "snapshot_trust": None,
                "identity": None,
                "reason": "verification_not_started",
            },
            semantic=None,
            injection_suspected=False,
            advisory_status=None,
            freshness={"source_file": None, "note": "verification_not_started"},
            overall_decision="ABSTAIN",
            overall_reasons=[abstention.code],
            overall_scope="submitted_claims_only",
            verification_class=verification_class,
            warnings=warnings or [],
            abstention={
                "code": abstention.code,
                "message": abstention.message,
                "affected_claim_ids": abstention.affected_claim_ids,
                "suggested_claims": abstention.suggested_claims,
                "suggestion_set_digest": abstention.suggestion_set_digest,
            },
        )

    def verify_answer(
        self,
        answer: str,
        claims: Any = None,
        audit_mode: str | None = None,
        expected_source_snapshot_id: str | None = None,
        as_of: str | None = None,
        caller_attested_complete: bool | None = None,
        claims_source: str | None = None,
        suggestion_set_digest: str | None = None,
    ) -> dict[str, Any]:
        """Spec §4C."""
        timestamp = _utc_now()
        warnings: list[str] = []

        # --- Input contract -------------------------------------------- #
        if not isinstance(answer, str) or not answer.strip():
            raise invalid_input("answer must be a non-blank string")
        if len(answer) > self.policy.verify_max_answer_chars:
            raise invalid_input("answer exceeds maximum length")
        audit_mode = audit_mode if audit_mode is not None else self.policy.audit_default_mode
        if audit_mode not in _AUDIT_MODES:
            raise invalid_input("audit_mode must be deterministic | semantic | auto")
        claims_source = claims_source or "caller"
        if claims_source not in _CLAIMS_SOURCES:
            raise invalid_input("claims_source must be caller | suggested_accepted")
        if claims_source == "suggested_accepted":
            if not suggestion_set_digest:
                raise invalid_input("suggestion_set_digest is required when claims_source is suggested_accepted")
        else:
            if suggestion_set_digest is not None:
                raise invalid_input("suggestion_set_digest is forbidden unless claims_source is suggested_accepted")
        attested = bool(caller_attested_complete) if caller_attested_complete is not None else False
        try:
            _, as_of_str = parse_as_of(as_of)
        except ValueError as exc:
            raise invalid_input("as_of must be an ISO 8601 timestamp", reason=str(exc))
        answer_digest_value = digest({"answer": answer})

        # --- Claim contract -------------------------------------------- #
        parsed, abstention = parse_and_validate_claims(claims, self.policy)
        if abstention is not None:
            return self._abstention_receipt(
                abstention=abstention,
                answer_digest_value=answer_digest_value,
                submitted_claims_digest_value=None,
                submitted_digest_reason=(
                    "no_claims_submitted" if abstention.code == "CLAIMS_REQUIRED" else "claims_malformed"
                ),
                claims_source=claims_source,
                suggestion_digest=suggestion_set_digest,
                as_of_str=as_of_str,
                timestamp=timestamp,
            )
        assert parsed is not None

        if isinstance(claims, list) and len(claims) > self.policy.verify_max_claims:
            raise invalid_input("claims exceed maximum count")

        # suggested_accepted: canonical submitted set must match the suggestion set
        if claims_source == "suggested_accepted":
            from .claims import suggestion_texts_digest

            submitted_text_digest = suggestion_texts_digest([c.text for c in parsed])
            if submitted_text_digest != suggestion_set_digest:
                raise invalid_input(
                    "suggestion_set_digest does not match the submitted claim set",
                    expected_matching="resubmit the suggested claims unedited, or use claims_source: caller",
                )

        atomicity = check_atomicity(parsed)
        if atomicity is not None:
            return self._abstention_receipt(
                abstention=atomicity,
                answer_digest_value=answer_digest_value,
                submitted_claims_digest_value=submitted_claims_digest(parsed),
                submitted_digest_reason=None,
                claims_source=claims_source,
                suggestion_digest=atomicity.suggestion_set_digest,
                as_of_str=as_of_str,
                timestamp=timestamp,
            )

        # --- Source snapshot + verification ----------------------------- #
        conn = open_source(self.policy.source_path or "")
        with SourceSession(conn, self.policy) as session:
            snapshot = session.resolve_snapshot(self.policy.source_path or "")
            warnings.extend(snapshot["load_warnings"])
            source_block = {
                "source_snapshot_id": snapshot["source_snapshot_id"],
                "snapshot_method": snapshot["snapshot_method"],
                "snapshot_trust": snapshot["snapshot_trust"],
                "identity": {"source_path": self.policy.source_path},
                "schema_version": schema_version(conn),
            }
            if (
                expected_source_snapshot_id is not None
                and expected_source_snapshot_id != snapshot["source_snapshot_id"]
            ):
                abstain = ClaimAbstention(
                    code=SNAPSHOT_MISMATCH,
                    message="expected source snapshot does not match current snapshot",
                    affected_claim_ids=[c.claim_id for c in parsed],
                    suggested_claims=[],
                    suggestion_set_digest=None,
                )
                receipt = self._abstention_receipt(
                    abstention=abstain,
                    answer_digest_value=answer_digest_value,
                    submitted_claims_digest_value=submitted_claims_digest(parsed),
                    submitted_digest_reason=None,
                    claims_source=claims_source,
                    suggestion_digest=None,
                    as_of_str=as_of_str,
                    timestamp=timestamp,
                    source=source_block,
                )
                return {"contract_version": CONTRACT_VERSION, "receipt": receipt, "warnings": warnings}

            records = snapshot["records"] or []
            index = self._get_index(snapshot["source_snapshot_id"], records)
            as_of_dt, _ = parse_as_of(as_of)
            evaluations = []
            ambiguous_ids: list[str] = []
            per_claim_records: dict[str, list[dict[str, Any]]] = {}
            for claim in parsed:
                retrieved, _, _ = index.search(claim.text, self.policy.retrieve_limit)
                per_claim_records[claim.claim_id] = retrieved
                evaluation, ambiguity = evaluate_claim(claim, retrieved, self.policy, as_of_dt)
                if ambiguity == CLAIM_AMBIGUOUS:
                    ambiguous_ids.append(claim.claim_id)
                    continue
                assert evaluation is not None
                evaluations.append(evaluation)

            if ambiguous_ids:
                abstain = ClaimAbstention(
                    code=CLAIM_AMBIGUOUS,
                    message="one or more claims could not be mapped safely to a single subject",
                    affected_claim_ids=sorted(ambiguous_ids),
                    suggested_claims=[],
                    suggestion_set_digest=None,
                )
                receipt = self._abstention_receipt(
                    abstention=abstain,
                    answer_digest_value=answer_digest_value,
                    submitted_claims_digest_value=submitted_claims_digest(parsed),
                    submitted_digest_reason=None,
                    claims_source=claims_source,
                    suggestion_digest=None,
                    as_of_str=as_of_str,
                    timestamp=timestamp,
                    source=source_block,
                )
                return {"contract_version": CONTRACT_VERSION, "receipt": receipt, "warnings": warnings}

        conn.close()

        # --- Overall composition ---------------------------------------- #
        overall = compose_overall(evaluations)
        operation_map = sorted(
            (e.claim.claim_id, e.evidence_set_digest) for e in evaluations
        )
        operation_evidence_digest_value = digest(
            {"operation_evidence": operation_map}
        ) if evaluations else None
        operation_reason = None if evaluations else "no_claim_reached_evidence_retrieval"

        coverage = {
            "status": "caller_declared" if attested else self.policy.claim_coverage_default,
            "method": "submitted_claims_only_with_caller_attestation" if attested else "submitted_claims_only",
            "caller_attested_complete": attested,
            "unassessed_assertions": None,
            "note": (
                "caller attestation recorded as caller-provided, not system-verified"
                if attested
                else "Affirmed verifies submitted claims only; completeness is not inferred"
            ),
        }

        # --- Semantic advisory (advisory only, Option A) ------------------ #
        semantic_block = None
        injection_suspected = False
        advisory_status = None
        verification_class = "deterministic_only"
        trigger_met = any(
            e.materiality in ("material", "unknown")
            and e.deterministic_verdict in _AUTO_TRIGGER_VERDICTS
            for e in evaluations
        )
        advisory_requested = audit_mode == "semantic" or (audit_mode == "auto" and trigger_met)
        if advisory_requested:
            verification_class = "deterministic_with_semantic_advisory"
            from .semantic import AdvisoryFailure, OpenRouterAdvisor, run_advisory

            advisor = self.advisor
            if advisor is None:
                try:
                    advisor = OpenRouterAdvisor(self.policy)
                except AdvisoryFailure as exc:
                    warnings.append(f"advisory unavailable: {exc.code}")
                    advisory_status = exc.code
                    per_claim = [
                        {
                            "claim_id": e.claim.claim_id,
                            "advisory_status": exc.code,
                            "advisory_result": None,
                            "rationale": None,
                            "cited_evidence_ids": [],
                            "injection_suspected": False,
                            "limitations": [],
                            "payload_disclosure": None,
                            "payload_digest": None,
                        }
                        for e in evaluations
                    ]
                    semantic_block = {
                        "advisor_execution": None,
                        "provider": None,
                        "model": None,
                        "prompt_version": None,
                        "simulated_label": None,
                        "per_claim": per_claim,
                        "semantic_digest": None,
                        "semantic_digest_label": "logged-not-reproducible",
                    }
            if advisor is not None:
                per_claim_evidence = {
                    e.claim.claim_id: [
                        (r["id"], (r.get("text") or "")[:600]) for r in per_claim_records[e.claim.claim_id]
                    ]
                    for e in evaluations
                }
                semantic_block, injection_suspected = run_advisory(
                    advisor, [e.claim for e in evaluations], per_claim_evidence, warnings
                )
                if semantic_block is not None:
                    statuses = {c["advisory_status"] for c in semantic_block["per_claim"]}
                    advisory_status = "ADVISORY_OK" if statuses == {"ADVISORY_OK"} else sorted(statuses)[0]

        retrieval_block = {
            "method": "lexical_bm25",
            "parameters": {"k1": self.policy.bm25_k1, "b": self.policy.bm25_b,
                           "per_claim_limit": self.policy.retrieve_limit},
            "tokenizer_version": TOKENIZER_VERSION,
            "score_meaning": "retrieval_ranking_signal_not_probability",
        }
        freshness = self._freshness(self.policy.source_path or "", records, self.policy, as_of_str, warnings)

        # Attach retrieved records (with record digests) per claim — spec §8C:
        # "Per-claim evidence IDs, record digests, source identifiers, and
        # relevant dates."
        claim_dicts = []
        for evaluation in evaluations:
            claim_dict = evaluation.to_dict()
            retrieved = per_claim_records[evaluation.claim.claim_id]
            claim_dict["records"] = [
                {
                    "id": r["id"],
                    "record_digest": record_digest(r),
                    "source": r["source"],
                    "source_name": r.get("source_name"),
                    "source_authority": r.get("source_authority"),
                    "source_published_at": r.get("source_published_at"),
                    "source_effective_at": r.get("source_effective_at"),
                }
                for r in retrieved
            ]
            claim_dicts.append(claim_dict)

        receipt = build_receipt(
            policy=self.policy,
            timestamp=timestamp,
            as_of=as_of_str,
            answer_digest=answer_digest_value,
            submitted_claims_digest=submitted_claims_digest(parsed),
            claim_coverage=coverage,
            claims_source=claims_source,
            suggestion_set_digest=None,
            claims=claim_dicts,
            retrieval=retrieval_block,
            operation_evidence_digest=operation_evidence_digest_value,
            operation_evidence_digest_reason=operation_reason,
            source=source_block,
            semantic=semantic_block,
            injection_suspected=injection_suspected,
            advisory_status=advisory_status,
            freshness=freshness,
            overall_decision=overall["overall_decision"],
            overall_reasons=overall["overall_reasons"],
            overall_scope=overall["overall_scope"],
            verification_class=verification_class,
            warnings=warnings,
        )
        return {"contract_version": CONTRACT_VERSION, "receipt": receipt, "warnings": warnings}

    # ------------------------------------------------------------------ #
    def get_source_status(self) -> dict[str, Any]:
        """Spec §4D. Establishes the current snapshot on every call."""
        warnings: list[str] = []
        conn = open_source(self.policy.source_path or "")
        with SourceSession(conn, self.policy) as session:
            snapshot = session.resolve_snapshot(self.policy.source_path or "")
        conn.close()
        freshness = self._freshness(self.policy.source_path or "", snapshot["records"], self.policy, _utc_now(), warnings)
        records = snapshot["records"] or []
        published = sorted({r["source_published_at"] for r in records if r.get("source_published_at")})
        effective = sorted({r["source_effective_at"] for r in records if r.get("source_effective_at")})
        return {
            "contract_version": CONTRACT_VERSION,
            "source_snapshot_id": snapshot["source_snapshot_id"],
            "snapshot_method": snapshot["snapshot_method"],
            "snapshot_trust": snapshot["snapshot_trust"],
            "file_mtime": freshness["source_file"].get("file_mtime"),
            "schema_version": schema_version(conn),
            "evidence_publication_date_coverage": {"min": published[0], "max": published[-1]} if published else None,
            "evidence_effective_date_coverage": {"min": effective[0], "max": effective[-1]} if effective else None,
            "file_staleness_warning": freshness["file_staleness_warning"],
            "evidence_freshness_warning": freshness["evidence_freshness_warning"],
            "last_sync_time": None,
            "last_sync_time_reason": "read_only_source_no_sync",
            "warnings": warnings,
        }


def validate_tool_payload(tool: str, payload: Any) -> dict[str, Any]:
    allowed = {"retrieve_evidence": RETRIEVE_FIELDS, "verify_answer": VERIFY_FIELDS}.get(tool)
    if allowed is None:
        raise invalid_input(f"unknown tool {tool!r}")
    return verify_top_level_request(payload, allowed, tool)
