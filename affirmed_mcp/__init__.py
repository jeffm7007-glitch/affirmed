"""Affirmed — evidence-checking MCP server and CLI for AI agents.

Deterministic verifier always on; optional semantic advisory; inspectable receipts.
"""

SOFTWARE_VERSION = "0.1.0"
VERIFIER_VERSION = "1"
SCHEMA_VERSION = "1"
TOKENIZER_VERSION = "1"
RETRIEVAL_VERSION = "1"
CANONICALIZATION_VERSION = "1"
POLICY_VERSION = "1"
CONTRACT_VERSION = "1"
ADVISORY_PROMPT_VERSION = "1"
RECEIPT_SCHEMA_VERSION = "1"

# Fixed limitations array carried by every receipt (spec §8D, verbatim).
FIXED_LIMITATIONS = [
    "Affirmed checks submitted claims only; unsubmitted assertions may remain unchecked.",
    "A PASS means the submitted material claims met the configured deterministic checks against the identified evidence source; it is not a guarantee of universal truth.",
    "Lexical retrieval may miss relevant paraphrases or terminology.",
    "Evidence quality, completeness, authority, and freshness depend on the configured source and policy.",
    "Semantic advisory is non-authoritative and cannot change the evidence-backed verdict; live advisory output is provider-dependent.",
    "A result may be limited by ambiguous instructions, incomplete claims, missing source data, or retrieval limitations.",
]

# Forbidden in user-facing product text, README, docs, demo output, receipts (spec §0).
FORBIDDEN_STRINGS = [
    "truth guarantee",
    "zero hallucinations",
    "proven true",
    "verified fact",
]
