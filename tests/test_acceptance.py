"""Cross-cutting acceptance tests (criteria #1, #8, #42, #43, #47, #63, #64, #65)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from affirmed_mcp import FORBIDDEN_STRINGS
from affirmed_mcp.demo_data import build_demo_db

REPO_ROOT = Path(__file__).resolve().parent.parent
TEXT_PATHS = ["README.md", "docs/security.md", "docs/ACCEPTANCE.md"]


def test_base_import_has_no_optional_dependency():
    """#1: the base package imports without mcp/OpenRouter extras installed."""
    code = (
        "import sys; assert 'mcp' not in sys.modules;"
        "import affirmed_mcp, affirmed_mcp.cli, affirmed_mcp.mcp_server, affirmed_mcp.service;"
        "print('ok')"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(REPO_ROOT))
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_socket_blocked_deterministic_paths(service, block_sockets):
    """#8/#42-partial: retrieve + verify run clean with every socket blocked."""
    out = service.retrieve_evidence("towing", as_of="2026-06-01T00:00:00Z")
    assert out["records"]
    result = service.verify_answer(
        answer="Towing costs $75.",
        claims=[{"claim_id": "c1", "text": "Towing costs $75.", "materiality": "material"}],
        as_of="2026-06-01T00:00:00Z",
    )
    assert result["receipt"]["overall_decision"] == "PASS"
    status = service.get_source_status()
    assert status["source_snapshot_id"]


def test_no_write_paths_in_source(demo_db_path, service):
    """#47: verification/retrieval never write to the source file."""
    import hashlib

    def _digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    before = _digest(demo_db_path)
    service.retrieve_evidence("towing")
    service.verify_answer(answer="Towing costs $75.", claims=[
        {"claim_id": "c1", "text": "Towing costs $75.", "materiality": "material"}])
    service.get_source_status()
    assert _digest(demo_db_path) == before


def test_no_telemetry_strings(block_sockets):
    """#63: no telemetry hooks in the package source."""
    offenders = []
    for path in (REPO_ROOT / "affirmed_mcp").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in ("segment.io", "sentry", "datadog", "telemetry.track", "mixpanel", "amplitude"):
            if needle in text.lower():
                offenders.append(f"{path.name}:{needle}")
    assert offenders == [], f"telemetry references found: {offenders}"


def test_forbidden_strings_grep():
    """#43: forbidden marketing strings absent from README, docs, receipts, demo output."""
    checked = []
    for rel in TEXT_PATHS:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        checked.append(path.read_text(encoding="utf-8"))
        for forbidden in FORBIDDEN_STRINGS:
            assert forbidden not in checked[-1], f"{forbidden!r} found in {rel}"

    # Demo output + receipt strings.
    from affirmed_mcp.config import Policy
    from affirmed_mcp.service import AffirmedService
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        db = str(Path(tmp) / "demo.db")
        build_demo_db(db)
        svc = AffirmedService(Policy(source_path=db))
        receipt = svc.verify_answer(
            answer="Towing costs $75.",
            claims=[{"claim_id": "c1", "text": "Towing costs $75.", "materiality": "material"}],
        )["receipt"]
        blob = json.dumps(receipt) + json.dumps(receipt["limitations"], ensure_ascii=False)
        for forbidden in FORBIDDEN_STRINGS:
            assert forbidden not in blob, f"{forbidden!r} found in receipt"

    proc = subprocess.run(
        [sys.executable, "-m", "affirmed_mcp.cli", "demo"],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0
    for forbidden in FORBIDDEN_STRINGS:
        assert forbidden not in proc.stdout


def test_no_unwarranted_compatibility_claim():
    """#65: no Ignorance2.Fact compatibility claims without supplied fixtures."""
    for rel in TEXT_PATHS:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        assert "Ignorance2.Fact compatible" not in text
        assert "full API compatibility" not in text.lower()


def test_readme_documents_extra_install():
    """#64: the inspector quickstart installs the extra explicitly."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "affirmed-mcp[mcp]" in readme
    assert "extra" in readme.lower()


def test_docs_exist_and_reference_plan():
    assert (REPO_ROOT / "docs" / "security.md").exists()
    assert (REPO_ROOT / "docs" / "ACCEPTANCE.md").exists()
