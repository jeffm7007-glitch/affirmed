# Affirmed MCP

**Evidence-checking MCP server and CLI for AI agents.** Deterministic verifier, optional semantic advisory, inspectable receipts.

Affirmed answers one question: *can this specific claim be supported, contradicted, or neither — by this specific evidence source, right now, reproducibly?* The deterministic core has **zero runtime dependencies** and makes **zero outbound network calls** (including telemetry). A semantic advisor (OpenRouter) is an optional, strictly isolated second opinion that can never change deterministic results.

## Why

AI agents make claims. Affirmed lets them check each atomic claim against a versioned, read-only evidence database and returns a **receipt** — digests, versions, rules, and limitations — that a human, an auditor, or another agent can re-verify byte-for-byte.

## Quickstart

```bash
# 1. Run the fictional demo (Scenarios A–D, zero network, scripted advisor)
uvx affirmed-mcp demo

# 2. Print the default local policy
affirmed-mcp install-config --print

# 3. Inspect the source snapshot status
affirmed-mcp get-source-status   # add --source /path/to/evidence.db

# 4. Verify an answer against your own source
echo -n "Towing costs $75." > /tmp/answer.txt
export AFFIRMED_SOURCE_PATH=/path/to/evidence.db
affirmed-mcp verify --file /tmp/answer.txt \
  --claims '[{"claim_id":"c1","text":"Towing costs $75.","materiality":"material"}]'

# 5. (optional) Serve over MCP stdio
affirmed-mcp serve
# or via MCP extra: pip install 'affirmed-mcp[mcp]'

# 6. (optional) Launch the MCP inspector (requires the mcp extra, #64)
affirmed-mcp inspect
```

See **docs/security.md** for the threat model and **docs/ACCEPTANCE.md** for the criterion-by-criterion verification map.

## The three tools

| Tool | What it does |
|---|---|
| `retrieve_evidence` | Lexical retrieval over the configured source; returns records, scores, diagnostics, and a query-independent `source_snapshot_id`. |
| `verify_answer` | Validates claims, retrieves evidence, evaluates each claim deterministically, optionally attaches a semantic advisory, and returns a receipt. |
| `get_source_status` | Schema version, snapshot method/id, record count, file metadata. |

There are exactly three tools. MCP requests cannot carry policy changes (no `policy_overrides`); local policy is file/env-only, validated at startup, and fails closed.

## Architecture

`affirmed_mcp/` is a stdlib-only package:

- `config.py` — versioned `Policy`, validated once at load, no per-request overrides.
- `source.py` — read-only SQLite adapter (`mode=ro`, `query_only=ON`); one consistent read transaction per operation; full-export or trusted-version snapshot; corrupt/mismatched sources fail closed.
- `schema.py` — canonical `EvidenceRecord` model with typed-field validation (units, ISO dates, availability schedules); unknown columns never interpreted.
- `retrieval.py` — deterministic lexical index, snapshot-keyed cache, documented non-probability scores.
- `claims.py` / `features.py` / `verifier.py` — atomic claim contract; rule-based feature extraction (numbers, units, negation, dates, geography, availability, quantifiers); typed-field verdict composition. Text overlap alone never verifies.
- `semantic.py` — two-key opt-in advisory (OpenRouter, HTTPS); output schema-validated, fabricated evidence IDs rejected, injection signals recorded, failure recorded never propagated.
- `receipt.py` / `receipt_verify.py` — canonical receipts with deterministic digests (timestamps excluded) and independent re-verification.
- `service.py` — the three-tool surface, pre-validation before any state, stable error envelopes.
- `cli.py` — `demo`, `suggest-claims`, `install-config`, `inspect`, `get-source-status`, `verify`, `eval`.
- `mcp_server.py` — vendored ND-JSON JSON-RPC stdio transport (~150 lines); optional FastMCP path when the `mcp` extra is installed.

Verdict semantics: `SUPPORTED` requires an applicable typed field for every condition in the claim (§5B contract). Missing typed fields are never upgraded by lexical similarity or advisory opinion. Unsupported reasoning types (superlatives, comparisons) return `FEATURE_UNVERIFIABLE`, never a regex guess.

## Limitations

The demo provider, data, and 12-example eval set are **fictional**; the eval set is a demonstration, not a benchmark. Affirmed does not measure hallucination rates. Retrieval is lexical, not semantic; it is a ranking signal, not relevance truth. Claim-checking coverage is caller-scoped (`submitted_claims_only`) — overall PASS never implies whole-answer verification, and the MVP never emits `reviewed_complete`. Conflict handling defaults to deterministic-first: conflicting applicable evidence yields documented abstention (`EVIDENCE_CONFLICT` / `UNRESOLVED`) rather than authority-weighted guessing. Trusted-source-version snapshots trust the source maintainer's version identifier (disclosed in receipts). Full Ignorance2.Fact API compatibility is not claimed without supplied external schemas/fixtures; the canonical `EvidenceRecord` adapter is tested independently. Source file-age is not evidence freshness and is disabled by default.

## Security summary

Read-only by construction (no write path in the MCP surface); fail-closed on schema mismatch, corruption, or malformed input; no arbitrary SQL reachable; semantic calls are HTTPS-only with disclosed payload digests and no credentials or unrelated context; no telemetry, no receipt persistence, no debug payload logging. See **docs/security.md**.

## Development

```bash
pip install pytest   # dev-only; runtime is stdlib-only
python3 -m pytest
```

## License

MIT
