# Security Model — Affirmed MCP

This document mirrors spec §9 (security posture) and IMPLEMENTATION_PLAN §8 (controls). It is the human-readable companion to the acceptance map in `docs/ACCEPTANCE.md`.

## Threat model

| Threat | Control | Where |
|---|---|---|
| Agent asserts unsupported claims as fact | Deterministic §5B typed-field contract; text overlap never verifies; unsupported reasoning returns `FEATURE_UNVERIFIABLE` | `verifier.py`, `features.py` |
| Semantic model output corrupts results | Strict schema validation, fabricated evidence-ID rejection, advisory failure recorded never propagated, can never change verdicts/materiality/coverage/overall | `semantic.py`, `service.py` |
| Prompt injection via evidence text | Injection signal scan on evidence + rationale; untrusted advisory output discarded without affecting deterministic results; absence of signal ≠ safety (documented) | `semantic.py` |
| Hidden network egress / telemetry | Zero runtime deps; stdlib only; deterministic paths make zero outbound calls — covered by socket-blocked tests | `tests/` (blocked-socket fixtures) |
| Malicious or drifted source DB | Read-only open (`mode=ro`, `query_only=ON`), no `immutable` (concurrent writers in scope), single read transaction per op, fail-closed on corrupt/mismatched | `source.py` |
| SQL injection | No arbitrary SQL reachable; MCP surface is three fixed tools; identifier quote-wrapping for trusted-version config | `source.py`, `service.py` |
| Unauthorized data exfiltration via advisory | HTTPS-only provider calls, exact payload disclosure + payload digest in receipts, no credentials, no unrelated context, two-key opt-in | `semantic.py` |
| Policy tampering at request time | No per-request overrides; unknown request fields rejected; unsafe/unknown local config fails closed at startup | `config.py`, `claims.py`, `service.py` |
| Non-reproducible results | Canonical digests, receipt timestamps excluded from deterministic digest, versions + config hash in every receipt | `canonical.py`, `receipt.py` |
| Secret leakage to clients | Stable error envelopes without stack traces; provider failures mapped to stable reason codes | `errors.py`, `service.py`, `mcp_server.py` |
| Data writes / persistence | Source is read-only; receipts are returned, not persisted; no debug payload logging | `source.py`, `receipt.py` |

## Deterministic guarantee

After installation, deterministic retrieval, verification, and demo operations make **zero outbound network calls, including telemetry**. Package installation itself may need network; that is outside the guarantee (spec §8). This is enforced in tests by hard-blocking sockets and running the demo + verify paths (criteria #8, #42).

## Semantic advisory isolation

- Two-key opt-in: `OPENROUTER_API_KEY` **and** `AFFIRMED_ALLOW_SEMANTIC=true` (spec #9). No fallback provider (spec #48).
- Provider output must pass the same strict schema as live data; fabricated evidence IDs are rejected (spec #12).
- Timeout, refusal, malformed, auth failure, rate limit, network failure, missing config, and suspected injection each map to a distinct, stable handling/reason code; none propagate into the deterministic path (spec #13).
- Receipts disclose the exact payload fields and payload digest; never credentials or unrelated context (spec #62).

## Fail-closed posture

Any of: malformed request, unknown top-level field, unsafe policy value, corrupt source file, schema mismatch, non-atomic claims — produce a safe failure or a documented abstention with reasons. They are never silently repaired, split, or verified (spec #52).

## Documented limitations that affect security expectations

- Advisory is a second opinion only; it is visibly labeled and simulated in demos.
- Absence of an injection signal is not proof of safety.
- Lexical retrieval is a ranking signal, not relevance truth.
- Whole-answer verification is never implied; coverage is caller-scoped.
