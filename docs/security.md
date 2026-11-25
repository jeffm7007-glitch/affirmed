# Affirmed — Security and Threat Model

This document mirrors the normative threat-model table (spec §9) and records
the concrete controls implemented in this build (implementation plan §8).

## Threat-model table

| Adversary / failure | In scope? | Primary control |
|---|---|---|
| Malicious or injected database content | Yes | Untrusted-evidence isolation, strict output schema, no tool access, deterministic verdict isolation |
| Malicious MCP client | Partially | Input validation, size limits, no secrets in tool args, no arbitrary SQL |
| Malicious local user | No; documented | Local user owns the machine and local environment |
| OpenRouter/provider data exposure | Yes | Two-key opt-in, disclosure, payload minimization, no secrets in receipts |
| Network attacker in semantic mode | Yes | TLS, pinned base URL by default, timeout and retry bounds |
| Concurrent source writer | Yes | Read transaction, snapshot identity, locking/WAL tests, explicit warnings |
| Sensitive claim/evidence retention | Yes | Stdout/explicit local output only, no hidden persistence, payload logging off by default |
| Misconfigured policy | Yes | Versioned policy, validation, safe defaults, receipt disclosure |
| Incomplete claim submission | Yes | Coverage fields, caller attestation, no whole-answer assurance by implication |

## Concrete controls in this build

- **Input validation and size limits.** All tool payloads pass strict
  top-level field allowlists; unknown fields are rejected (`INVALID_INPUT`).
  Query, claim-text, identifier, and aggregate size bounds are enforced by
  the configured `Policy` before any processing.
- **No secrets in tool arguments.** Tools accept only evidence/query data;
  the two-key semantic gate reads environment variables only.
- **No arbitrary SQL.** The source adapter uses parameterized queries only;
  clients can supply no SQL. The database is opened read-only
  (`mode=ro`, `query_only`) and every verification runs in a single
  read transaction against an immutable in-memory snapshot.
- **Safe failures.** Corrupt, schema-mismatched, or unsupported databases
  fail closed with a documented error envelope. The engine never silently
  falls back to a different database or to relaxed checks.
- **Receipt and log handling.** Receipts go to the tool response or stdout;
  a local receipt file is written only at an explicit user-supplied path.
  No hidden receipt database, telemetry, analytics, or automatic upload.
  Raw semantic request/response logging is disabled by default.
- **Error-envelope stability.** Errors are returned as stable, documented
  envelopes (`code`, `message`, `retryable`, `details`) — never stack
  traces, never internal messages that could carry paths or secrets.
- **Zero network in deterministic mode.** No outbound calls of any kind,
  including telemetry; the acceptance suite mocks sockets and asserts no
  network activity (deterministic runs and the demo).

## Two-key semantic gate

Semantic advisory requires **both**:

- `OPENROUTER_API_KEY`
- `AFFIRMED_ALLOW_SEMANTIC=true`

Without both:

- `audit_mode: deterministic` runs normally without a provider call.
- `audit_mode: auto` falls back to deterministic-only with an operation warning.
- An explicit semantic request preserves deterministic results and returns
  `advisory_status: ADVISORY_NOT_CONFIGURED` with an operation warning; it is
  not a transport error and does not force overall abstention.

## Key handling

- Environment variables only.
- Never in receipts.
- Never in MCP tool arguments.
- Never in logs.
- Never included in semantic payloads.

## Receipt content warning

Receipts may contain claim and evidence text. Apply appropriate local file
permissions and retention practices to any receipt files you explicitly write.

## Network policy

- Zero outbound calls in deterministic mode, including telemetry.
- Semantic mode discloses exactly what is transmitted: only the claim and
  minimum relevant evidence snippets/IDs needed for advisory interpretation.
- No automatic provider fallback. TLS required. The provider base URL is
  pinned by default; custom endpoints require explicit configuration.

## SQLite hardening

- Database opened read-only; writes are refused at the connection level.
- Schema and required columns are validated before verification.
- Parameterized queries only; no client-supplied SQL.
- WAL behavior, locking, symlink/path assumptions, and concurrent-writer
  behavior are exercised by the test suite (locking/WAL/concurrent-writer/
  corrupt/schema-mismatch cases); concurrent writers are surfaced through
  explicit warnings, never silent stale reads.
