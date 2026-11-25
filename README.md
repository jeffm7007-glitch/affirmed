# Affirmed

**Evidence-checking MCP server and CLI for AI agents.** A deterministic
verification engine with an optional, strictly isolated semantic advisory —
and inspectable receipts for every run.

- Deterministic verdicts from a pinned, read-only evidence source — the same
  inputs always produce the same result digests.
- Abstains on ambiguous, incomplete, or unsupported claims instead of
  guessing; coverage and materiality are explicit in every receipt.
- Zero runtime dependencies (Python 3.10+, standard library only); zero
  network access in deterministic mode, including telemetry.

## Quickstart

```bash
# Run the self-contained demo (temporary DB, Scenarios A–D, scripted advisor double)
uvx affirmed-mcp demo

# Print the default policy and a ready-to-paste MCP client config block
uvx affirmed-mcp install-config --print

# Inspect the running server with the MCP inspector (requires the mcp extra)
uvx --with affirmed-mcp[mcp] affirmed-mcp inspect

# Verify an answer against a set of atomic claims
affirmed-mcp verify --answer answer.txt --claims claims.json

# Check the pinned source snapshot identity and freshness
affirmed-mcp get-source-status --source evidence.db

# Run the fictional 12-example demonstration set (NOT a benchmark)
affirmed-mcp eval
```

Point the server at an evidence database with the `AFFIRMED_SOURCE_PATH`
environment variable (see `install-config --print` output).

## Architecture

Affirmed layers a small, fully deterministic pipeline over a pinned SQLite
evidence source: a canonical read-only source adapter snapshots the database
in a single transaction and stamps it with a full-export digest identity;
lexical BM25 retrieval fetches candidate records; a claims normalizer turns
submitted answer text into atomic claims with typed features (availability,
numeric+unit, date, boolean/string match, negation, geography, quantifier
scope); the verifier evaluates each claim against typed evidence fields
under a versioned support contract and conservative composition rules, never
raising assurance beyond what the evidence states; an optional semantic
advisory (two-key opt-in, network only when explicitly enabled) may suggest
but can never change an evidence-backed verdict; and every run emits a
complete, self-contained receipt whose deterministic digest is byte-identical
across processes for identical pinned inputs. The MCP surface exposes exactly
three tools — `retrieve_evidence`, `verify_answer`, `get_source_status` —
over a vendored ND-JSON JSON-RPC stdio transport, with an optional path via
the official `mcp` SDK when the `mcp` extra is installed.

## Limitations

- BM25 lexical retrieval only; paraphrase gaps are expected and surface as
  abstentions rather than being chased with a vector database.
- Atomicity/ambiguity heuristics are documented deterministic rules, not
  language understanding; uncertain cases route to review outcomes.
- Deterministic claim-type coverage is a closed set (availability,
  numeric+unit, date, boolean/string field match, negation, geography,
  quantifier scope); other reasoning types return `FEATURE_UNVERIFIABLE`.
- `trusted_source_version` snapshot trust depends on the configured
  maintainer's discipline, and this is disclosed in receipts.
- The vendored MCP transport implements the core JSON-RPC surface
  (initialize, tools/list, tools/call, ping); the official-SDK path is
  available via the `mcp` extra.
- The demo and eval sets are fictional illustrations, not measurements of
  production reliability.

## Security

Deterministic mode makes no outbound calls at all (the test suite blocks
sockets and asserts this). The evidence database is opened read-only with
parameterized queries only; malformed or schema-mismatched sources fail
closed. Errors are stable documented envelopes — no stack traces, no
secrets. The semantic advisory requires both an API key and an explicit
opt-in flag, sends only minimized claim/evidence snippets, and never places
keys in receipts, logs, or tool arguments. See
[docs/security.md](docs/security.md) for the full threat model.

## License

MIT. See below.

```
MIT License

Copyright (c) 2026 ProPlum Network

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
