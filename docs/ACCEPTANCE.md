# Acceptance Map — v4 spec §14, criteria #1–65

Every criterion maps to a test (`tests/<file>::<test>`), a documented behavior, or is marked **BLOCKED** with rationale. The deterministic contract was never weakened to pass a test; where the engine's real behavior differs from a naive reading of a criterion, the honest behavior is documented instead.

| # | Criterion | Mapping |
|---|---|---|
| 1 | Base install imports without extras | `test_acceptance.py::test_base_import_has_no_optional_dependency` (import affirmed_mcp with zero runtime deps per pyproject); verified via `pip install .` stdlib-only build |
| 2 | MCP extra exposes exactly three tools | `test_mcp.py::test_tools_list_exactly_three` |
| 3 | retrieve_evidence query/limit bounds | `test_service.py::test_retrieve_evidence_bounds` |
| 4 | verify_answer answer/claim-count bounds | `test_service.py::test_verify_answer_bounds` |
| 5 | Missing claims → ABSTAIN/CLAIMS_REQUIRED | `test_claims.py::test_missing_claims_abstain`; `test_service.py::test_missing_claims_abstain_receipt` |
| 6 | Non-atomic claims not silently split/verified | `test_claims.py::test_non_atomic_claims_not_silently_split` |
| 7 | Suggestions labeled, require caller acceptance | `test_claims.py::test_suggestions_labeled_and_digest_stable` |
| 8 | Zero outbound incl. telemetry after install | `test_acceptance.py::test_socket_blocked_deterministic_paths` (block_sockets fixture across retrieve/verify/demo) |
| 9 | Advisory requires both keys | `test_semantic.py::test_two_key_gate` |
| 10 | Advisory cannot change verdicts/status/materiality/coverage/overall | `test_semantic.py::test_advisory_cannot_change_deterministic_block`; `test_service.py::test_scripted_overreach_cannot_promote` |
| 11 | Provider output strictly schema-validated | `test_semantic.py::test_validate_advisory_output_rejects_bad_payloads` |
| 12 | Fabricated evidence IDs rejected | `test_semantic.py::test_fabricated_evidence_ids_rejected` |
| 13 | Distinct stable handling per failure class | `test_semantic.py::test_failure_codes_distinct_and_stable` |
| 14 | Prompt-injection fixtures cannot alter deterministic results | `test_semantic.py::test_injection_discards_advisory_not_result`; `test_service.py::test_scenario_d_untrusted_evidence_safe_failure` |
| 15 | Injection signals recorded; absence ≠ safety | `test_semantic.py::test_injection_signal_recorded`; documented in `docs/security.md` |
| 16 | Composition monotonicity/idempotence/conservative minimum | `test_verifier.py::test_compose_overall_properties` |
| 17 | Scenario A UNSUPPORTED/ABSTAIN | `test_demo.py::test_scenario_a` |
| 18 | Scenario B paraphrase cannot promote, labeled simulated | `test_demo.py::test_scenario_b` |
| 19 | Scenario C overreach kept separate, labeled simulated | `test_demo.py::test_scenario_c` |
| 20 | Scenario D untrusted evidence + safe advisory failure | `test_demo.py::test_scenario_d` |
| 21 | Snapshot mismatch → SNAPSHOT_MISMATCH abstentions | `test_service.py::test_snapshot_mismatch_abstentions` |
| 22 | source_snapshot_id query-independent | `test_service.py::test_snapshot_id_query_independent` |
| 23 | evidence_set_digest identifies exact ordered records | `test_retrieval.py::test_evidence_set_digest_identifies_ordered_records`; `test_canonical.py::test_evidence_set_digest_identifies_exact_ordered_set` |
| 24 | record_digest identifies canonical record | `test_canonical.py::test_record_digest_identifies_canonical_record`; `test_schema.py` digest tests |
| 25 | One verification = one consistent read transaction | `test_source.py::test_single_transaction_snapshot_consistency` |
| 26 | WAL/locking/concurrent-writer/corrupt/mismatch/unsupported | `test_source.py` (corrupt, mismatch, missing columns, concurrent writer); WAL/locking exercised implicitly by concurrent-writer + read-only tests |
| 27 | SUPPORTED requires every applicable §5B condition | `test_verifier.py::test_supported_claim_uses_typed_field_with_applicability` |
| 28 | Missing typed fields never upgraded by similarity/advisory | `test_verifier.py::test_scenario_a_missing_typed_field_no_text_upgrade` |
| 29 | No text-overlap verification of typed conditions | `test_verifier.py::test_numeric_match_and_contradiction`, `test_geo_match_and_contradiction`, `test_text_overlap_alone_never_verifies_availability` |
| 30 | Conflicting evidence → policy or UNRESOLVED + safe abstain | `test_service.py::test_conflict_abstains_safely` |
| 31 | Unknown materiality defaults material | `test_verifier.py::test_materiality_unknown_defaults_material` |
| 32 | Advisor cannot change materiality | `test_semantic.py::test_advisory_cannot_change_deterministic_block` |
| 33 | Coverage defaults partial/unknown; never reviewed_complete; submitted_claims_only | `test_service.py::test_coverage_invariants` |
| 34 | Completeness attestation labeled caller-provided | `test_service.py::test_completeness_attestation_caller_labeled` |
| 35 | Empty evidence / all-nonmaterial → explicit non-PASS | `test_verifier.py::test_compose_overall_properties` (empty + all-nonmaterial) |
| 36 | Receipt completeness (digests, snapshot, versions, policy, rules, limitations) | `test_receipt.py::test_receipt_required_fields_present` |
| 37 | Deterministic digest byte-identical across processes | `test_canonical.py::test_deterministic_digest_byte_identical_across_subprocesses` |
| 38 | Semantic digest labeled not-reproducible | `test_receipt.py::test_semantic_digest_labeled_logged_not_guaranteed` |
| 39 | File-age warning disabled/separately labeled | `test_service.py::test_file_age_disabled_by_default` |
| 40 | policy_overrides rejected; unsafe config fails closed | `test_claims.py::test_top_level_unknown_fields_rejected`; `test_config.py::test_unsafe_policy_values_rejected` |
| 41 | Config-hash/version coupling | `test_config.py::test_config_hash_covers_accepted_config`; version constants asserted in receipt tests |
| 42 | uvx demo in clean container + socket-block | `test_acceptance.py::test_demo_subprocess_socket_blocked`; install-from-clean-env verified manually (documented) |
| 43 | Forbidden-string grep | `test_acceptance.py::test_forbidden_strings_grep` |
| 44 | Precision/recall/abstention/coverage reported separately | `test_eval.py::test_metrics_reported_separately` |
| 45 | 12-example set not represented as benchmark | `test_eval.py::test_disclaimer_present` |
| 46 | Stable error envelopes, no stack traces/secrets | `test_mcp.py::test_error_envelopes_stable`; `test_service.py::test_error_envelope_no_stack_trace` |
| 47 | No arbitrary SQL/writes via MCP | `test_acceptance.py::test_no_write_paths_in_source`; read-only enforced in `test_source.py` |
| 48 | No automatic provider fallback | `test_semantic.py::test_no_fallback_provider` |
| 49 | Fixed limitations array in every verification receipt | `test_receipt.py::test_receipt_required_fields_present` (limitations asserted) |
| 50 | PASS impossible without material SUPPORTED claims etc. | `test_verifier.py::test_compose_overall_properties` |
| 51 | Unknown fields + text/count/uniqueness limits | `test_claims.py::test_claim_text_and_id_bounds`, `test_unknown_claim_fields_rejected`; service bounds tests |
| 52 | Malformed/compound/ambiguous claims non-PASS, never repaired | `test_claims.py` (malformed, non-atomic); `test_verifier.py::test_unsupported_reasoning_unresolvable` |
| 53 | Suggestion-set digest + reviewed resubmission; no completeness | `test_claims.py::test_suggestion_text_digest_matches_only_unedited_set`; `test_service.py::test_suggestions_require_acceptance` |
| 54 | Error envelope distinguishes pre-validation vs domain abstention | `test_service.py::test_prevalidation_vs_abstention_distinct` |
| 55 | audit_mode default deterministic; auto only on trigger; advisory unavailability preserves results + warning | `test_semantic.py::test_audit_mode_defaults`; `test_service.py::test_advisory_unavailable_warning` |
| 56 | Snapshot method fixed at startup; full hash in same transaction; trust disclosed | `test_source.py::test_single_transaction_snapshot_consistency`; trust statement asserted in `test_service.py` receipt snapshot block |
| 57 | Cold/warm cache byte-identical; snapshot+version keyed; no source writes | `test_retrieval.py::test_index_cache_keyed_by_snapshot_and_never_mutates_source` |
| 58 | operation_evidence_digest changes with any claim's ordered evidence | `test_receipt.py::test_operation_evidence_digest_tracks_evidence` |
| 59 | Typed schema validation rejections | `test_schema.py::test_incomplete_tuple_rejected`, `test_invalid_field_type_rejected`, `test_wrong_value_shape_rejected` |
| 60 | Unsupported reasoning → FEATURE_UNVERIFIABLE | `test_verifier.py::test_unsupported_reasoning_unresolvable`; `test_features.py::test_unsupported_reasoning_never_forced_through_regex` |
| 61 | Explicit as_of controls temporality, recorded + digested | `test_verifier.py::test_as_of_parsing_and_recorded`; `test_service.py::test_as_of_recorded_in_receipt` |
| 62 | HTTPS + cert verification; payload disclosure; no credentials | `test_semantic.py::test_https_only_and_no_credentials_in_payload` |
| 63 | No telemetry/persistence/debug logging | `test_acceptance.py::test_no_telemetry_strings`; documented `docs/security.md` |
| 64 | Inspector quickstart installs extra explicitly | `test_acceptance.py::test_readme_documents_extra_install` (README quickstart states pip install of extra) |
| 65 | No Ignorance2.Fact compatibility claim without fixtures; adapter tested independently | `test_acceptance.py::test_no_unwarranted_compatibility_claim` + canonical adapter tests across `test_schema.py`/`test_source.py` |

## Notes and honest deviations

- **#26 (WAL/locking):** the source is opened read-only via URI with `query_only=ON`; WAL-mode-specific behavior is exercised through the concurrent-writer test rather than by asserting journal-mode internals, which SQLite controls.
- **#42:** the socket-blocked demo is tested via a subprocess running the real CLI (`test_acceptance.py::test_demo_subprocess_socket_blocked`). A literal `uvx` clean-container run is validated manually at release time; the test substitutes the equivalent blocked-network subprocess so CI needs no container and no network.
- **#62 (live HTTPS):** unit tests assert HTTPS-only URL validation and payload contents; no live provider call is made in tests (two-key gate is off by default), consistent with the zero-network guarantee.

No criterion required weakening the deterministic contract; there are no BLOCKED criteria.
