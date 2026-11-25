# Affirmed — Acceptance Criteria Mapping

Normative spec: §14 criteria #1–65. Each criterion maps to at least one
implementing test (`tests/test_*.py::TestClass::test_name`) or to a committed
document section. The mapping is verified by `tests/test_acceptance.py`, which
asserts every criterion ID appears in this file and that every referenced
test file exists.

**No BLOCKED entries.** No criterion required weakening the deterministic
contract; where the spec offers implementation latitude (vendored transport,
snapshot method default), the plan §12 deviations are used and documented
below.

## Deviations exercised (plan §12)

- **Vendored MCP transport** (#2, #64): the base package serves MCP over a
  vendored ND-JSON JSON-RPC stdio loop (`initialize` / `tools/list` /
  `tools/call` / `ping`). The official-SDK path (`mcp` extra) exposes the same
  three tools and is the documented alternative — installing the extra is a
  package download and is **not** covered by the deterministic zero-network
  guarantee (stated in README quickstart).
- **Snapshot method default** (#21, #56): `full_export_sha256` is the fixed
  startup default; `trusted_source_version` is implemented and its trust
  assumption is disclosed on every receipt using it. Method is fixed at
  startup and never switched at runtime.

## Mapping table

| # | Implementing tests / doc section |
|---|---|
| 1 | test_mcp.py::TestBasePackageImports (imports without `mcp`/`semantic` extras); README quickstart |
| 2 | test_mcp.py::TestToolSurface::test_exactly_three_tools |
| 3 | test_service.py::TestRetrieveBounds (query blank/oversize, limit bounds) |
| 4 | test_service.py::TestVerifyBounds (answer bounds, claim-count bounds) |
| 5 | test_service.py::TestAbstentions::test_missing_claims_abstain_claims_required |
| 6 | test_claims.py::TestAtomicity::test_compound_not_split (documented non-PASS outcome) |
| 7 | test_service.py::TestSuggestionFlow::test_suggested_claims_labeled_require_acceptance (#53 same tests) |
| 8 | test_demo.py::test_demo_zero_network_socket_blocked (also #42-partial) |
| 9 | test_semantic.py::TestTwoKeyGate::test_both_keys_required |
| 10 | test_semantic.py::TestNonInterference::test_cannot_change_verdict_materiality_coverage_overall |
| 11 | test_semantic.py::TestSchemaValidation::test_output_strictly_schema_validated |
| 12 | test_semantic.py::TestFabricatedEvidence::test_fabricated_ids_rejected |
| 13 | test_semantic.py::TestDistinctCodes::test_each_failure_mode_distinct_stable_code |
| 14 | test_verifier.py::TestInjectionFixtures::test_injection_cannot_alter_deterministic_results |
| 15 | test_verifier.py::TestInjectionFixtures::test_injection_signals_recorded_no_absence_claim |
| 16 | test_verifier.py::TestCompositionProperties::test_monotonicity_idempotence_conservative_minimum |
| 17 | test_demo.py::TestScenarioA::test_unsupported_and_material_abstain |
| 18 | test_demo.py::TestScenarioB::test_paraphrase_advisory_labeled_simulated_cannot_promote |
| 19 | test_demo.py::TestScenarioC::test_overreach_kept_separate_labeled_simulated |
| 20 | test_demo.py::TestScenarioD::test_untrusted_evidence_safe_advisory_failure |
| 21 | test_service.py::TestSnapshotMismatch::test_verify_abstains_retrieve_stable_no_evidence |
| 22 | test_source.py::TestSnapshotIdentity::test_snapshot_id_query_independent |
| 23 | test_retrieval.py::TestDigestIdentities::test_evidence_set_digest_ordered_records |
| 24 | test_retrieval.py::TestDigestIdentities::test_record_digest_canonical_record |
| 25 | test_source.py::TestTransactions::test_single_read_transaction_verification |
| 26 | test_source.py::TestReadOnlyIntegrity::test_wal_locking_concurrent_writer_corrupt_schema_mismatch |
| 27 | test_verifier.py::TestSupportContract::test_supported_requires_all_5b_conditions |
| 28 | test_verifier.py::TestSupportContract::test_missing_typed_fields_never_lexical_upgraded |
| 29 | test_verifier.py::TestTypedComparisons::test_overlap_alone_never_satisfies (numbers, units, negation, dates, geography, availability, quantifier scope) |
| 30 | test_verifier.py::TestConflicts::test_conflict_authority_policy_or_unresolved_safe_abstain |
| 31 | test_claims.py::TestMateriality::test_unknown_defaults_material |
| 32 | test_semantic.py::TestNonInterference::test_cannot_change_verdict_materiality_coverage_overall |
| 33 | test_service.py::TestCoverageInvariants::test_partial_or_unknown_never_reviewed_complete_scope_submitted_only |
| 34 | test_service.py::TestCoverageInvariants::test_caller_attestation_labeled_caller_provided |
| 35 | test_service.py::TestCoverageInvariants::test_empty_claims_empty_evidence_all_nonmaterial_non_pass |
| 36 | test_receipt.py::TestCompleteness::test_required_fields_present_null_with_reason_not_zero |
| 37 | test_receipt.py::TestDeterministicDigest::test_byte_identical_cold_warm_subprocess_asof_pinned |
| 38 | test_receipt.py::TestSemanticDigest::test_labeled_logged_not_guaranteed_reproducible |
| 39 | test_source.py::TestFreshnessSeparation::test_file_age_warning_disabled_by_default_separately_labeled |
| 40 | test_mcp.py::TestUnknownFields::test_policy_overrides_rejected; test_config.py::TestFailsClosed::test_unsafe_local_policy_cannot_weaken |
| 41 | test_acceptance.py::TestVersionCoupling::test_config_hash_fails_on_behavior_change_without_version_bump |
| 42 | tests/test_demo.py + CLI `demo` subcommand (socket-blocked; scripted advisor; simulated labels) — partial per plan §9 (#42-partial) |
| 43 | test_acceptance.py::TestForbiddenStrings::test_no_forbidden_strings_anywhere |
| 44 | test_eval.py::TestMetrics::test_precision_recall_abstention_coverage_separate |
| 45 | test_eval.py::TestDisclaimer::test_not_a_benchmark_disclaimer_present |
| 46 | test_mcp.py::TestErrorEnvelope::test_stable_no_stack_traces_no_secrets |
| 47 | test_mcp.py::TestNoArbitrarySql::test_no_sql_or_write_reachable |
| 48 | test_semantic.py::TestNoFallback::test_no_automatic_provider_fallback |
| 49 | test_receipt.py::TestCompleteness::test_fixed_limitations_array_present |
| 50 | test_service.py::TestOverallDecision::test_pass_conditions_enforced |
| 51 | test_claims.py::TestUnknownFieldsAndLimits::test_rejected_and_limits_enforced |
| 52 | test_claims.py::TestAtomicity::test_malformed_compound_ambiguous_documented_outcomes |
| 53 | test_service.py::TestSuggestionFlow::test_digest_and_matching_acceptance_metadata |
| 54 | test_errors / test_service error-envelope tests::test_prevalidation_vs_domain_abstention_distinguished |
| 55 | test_service.py::TestAuditMode::test_default_deterministic_auto_trigger_documented_warning_preserved |
| 56 | test_source.py::TestSnapshotMethod::test_fixed_at_startup_same_transaction_trust_disclosed |
| 57 | test_retrieval.py::TestCache::test_cold_warm_byte_identical_keyed_by_snapshot_versions_never_writes_source |
| 58 | test_receipt.py::TestOperationEvidenceDigest::test_changes_with_evidence_set_included_in_deterministic_digest |
| 59 | test_source.py::TestSchemaValidation::test_incomplete_tuples_types_structured_units_rejected |
| 60 | test_verifier.py::TestUnsupportedReasoning::test_feature_unverifiable_not_generic_match |
| 61 | test_service.py::TestAsOf::test_explicit_as_of_recorded_and_digest_pinned |
| 62 | test_semantic.py::TestDisclosure::test_https_certificate_verification_payload_disclosure_no_credentials |
| 63 | test_demo.py / test_acceptance.py::test_no_telemetry_no_hidden_persistence_no_debug_payload_logging |
| 64 | test_mcp.py::TestToolSurface::test_extra_documented_install_explicit (README quickstart wording) |
| 65 | test_source.py::TestAdapterIndependence::test_canonical_adapter_contract_without_external_fixtures |

## How to re-verify

```bash
python3 -m pytest tests/ -q          # full suite, includes this mapping's checks
python3 -m affirmed_mcp.cli demo     # Scenarios A–D, zero network after start
```
