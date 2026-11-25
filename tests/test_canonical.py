"""Canonicalization + digest identity tests (criteria #23, #24, #37, #58)."""

from __future__ import annotations

import json
import subprocess
import sys

from affirmed_mcp.canonical import canonical_bytes, canonical_dumps, digest, digest_bytes, sha256_hex
from affirmed_mcp.retrieval import evidence_set_digest
from affirmed_mcp.schema import canonical_record, record_digest


def test_digest_is_stable_and_key_order_independent():
    a = digest({"b": 2, "a": 1, "nested": {"y": [3, 2, 1], "x": "s"}})
    b = digest({"nested": {"x": "s", "y": [3, 2, 1]}, "a": 1, "b": 2})
    assert a == b
    assert a.startswith("sha256:")


def test_canonical_dumps_byte_stable():
    assert canonical_dumps({"z": 1, "a": [True, None]}) == canonical_dumps({"a": [True, None], "z": 1})
    assert canonical_bytes({"k": "v"}) == b'{"k":"v"}'


def test_sha256_hex_and_digest_bytes_agree():
    data = b"affirmed"
    assert sha256_hex(data) == digest_bytes(data).removeprefix("sha256:")


def test_record_digest_identifies_canonical_record():
    rec = {"id": "r1", "text": "hello", "source": "s", "tags": ["a"]}
    assert record_digest(rec) == record_digest(dict(rec))
    assert record_digest(rec) != record_digest({**rec, "text": "changed"})
    assert record_digest(canonical_record(rec)) == record_digest(rec)


def test_evidence_set_digest_identifies_exact_ordered_set():
    recs = [
        {"id": "a", "text": "t1", "source": "s", "tags": []},
        {"id": "b", "text": "t2", "source": "s", "tags": []},
    ]
    same = evidence_set_digest(list(recs))
    assert same == evidence_set_digest(list(recs))
    # Order matters: the digest identifies the exact ordered records used.
    assert evidence_set_digest(list(reversed(recs))) != same


def test_deterministic_digest_byte_identical_across_subprocesses(tmp_path, service):
    """#37: identical pinned inputs + as_of in a fresh process reproduce the digest."""
    claims = [{"claim_id": "c1", "text": "Towing costs $75.", "materiality": "material"}]
    r1 = service.verify_answer(answer="Towing costs $75.", claims=claims, as_of="2026-06-01T00:00:00Z")
    code = (
        "import json,sys;"
        "from affirmed_mcp.config import Policy;"
        "from affirmed_mcp.service import AffirmedService;"
        f"svc=AffirmedService(Policy(source_path={json.dumps(service.policy.source_path)}));"
        "r=svc.verify_answer(answer='Towing costs $75.',"
        " claims=[{'claim_id':'c1','text':'Towing costs $75.','materiality':'material'}],"
        " as_of='2026-06-01T00:00:00Z');"
        "print(r['receipt']['deterministic_digest'])"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True,
        cwd="/root/.openclaw/workspace/affirmed",
    )
    assert out.stdout.strip() == r1["receipt"]["deterministic_digest"]
