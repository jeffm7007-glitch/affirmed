"""CLI demo tests — Scenarios A–D (criteria #17–20, #42-partial)."""

from __future__ import annotations

import json
import os
import subprocess
import sys


def _run_cli(args, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, "-m", "affirmed_mcp.cli", *args],
        capture_output=True, text=True, env=env, timeout=120,
    )


def _scenario_blocks(proc):
    """Split demo stdout into per-scenario blocks."""
    blocks = {}
    current = None
    for line in proc.stdout.splitlines():
        if line.startswith("=== Scenario"):
            current = line.split("Scenario")[1].split("—")[0].strip().rstrip("-").strip()
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return {k: "\n".join(v) for k, v in blocks.items()}


def test_demo_runs_all_scenarios():
    proc = _run_cli(["demo"])
    assert proc.returncode == 0, proc.stderr
    blocks = _scenario_blocks(proc)
    assert sorted(blocks) == ["A", "B", "C", "D"], f"expected Scenarios A–D, got: {sorted(blocks)}"


def test_scenario_a():
    """#17: missing 24/7 typed evidence -> UNSUPPORTED/ABSTAIN."""
    proc = _run_cli(["demo"])
    block = _scenario_blocks(proc)["A"]
    assert "deterministic_verdict: UNSUPPORTED" in block
    assert "overall_decision: ABSTAIN" in block


def test_scenario_b():
    """#18: paraphrase stays UNSUPPORTED; advisory flagged as simulated."""
    proc = _run_cli(["demo"])
    blocks = _scenario_blocks(proc)
    assert "deterministic_verdict: UNSUPPORTED" in blocks["B"]
    assert "overall_decision: ABSTAIN" in blocks["B"]
    assert "POSSIBLE_PARAPHRASE" in blocks["B"]
    assert "SIMULATED" in blocks["B"]


def test_scenario_c():
    """#19: scripted overreach kept separate; deterministic verdict unchanged."""
    proc = _run_cli(["demo"])
    blocks = _scenario_blocks(proc)
    assert "deterministic_verdict: UNSUPPORTED" in blocks["C"]
    assert "overall_decision: ABSTAIN" in blocks["C"]
    assert "POSSIBLE_ALIGNMENT" in blocks["C"]
    assert "SIMULATED" in blocks["C"]


def test_scenario_d():
    """#20: untrusted evidence -> deterministic SUPPORTED unaffected; advisory fails safe."""
    proc = _run_cli(["demo"])
    blocks = _scenario_blocks(proc)
    assert "deterministic_verdict: SUPPORTED" in blocks["D"]
    assert "overall_decision: PASS" in blocks["D"]
    assert "ADVISORY_UNTRUSTED" in blocks["D"]


def test_demo_output_labels_simulated_and_fictional():
    proc = _run_cli(["demo"])
    assert "SIMULATED" in proc.stdout
    assert "fictional" in proc.stdout.lower()


def test_demo_subprocess_socket_blocked():
    """#8/#42: the demo completes with all sockets blocked after start."""
    guard = (
        "import socket\n"
        "def _blocked(*a, **k): raise RuntimeError('network blocked')\n"
        "socket.socket.connect = _blocked\n"
        "socket.create_connection = _blocked\n"
        "socket.getaddrinfo = _blocked\n"
        "import runpy, sys\n"
        "sys.argv = ['affirmed-mcp', 'demo']\n"
        "runpy.run_module('affirmed_mcp.cli', run_name='__main__')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", guard],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    assert sorted(_scenario_blocks(proc)) == ["A", "B", "C", "D"]


def test_install_config_print():
    proc = _run_cli(["install-config", "--print"])
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    policy = out["policy"]
    assert policy["materiality_unknown_default"] == "material"
    assert "config_hash" in out
    assert out["mcp_servers"]["affirmed"]["command"] == "affirmed-mcp"


def test_suggest_claims_cli(tmp_path):
    answer = tmp_path / "answer.txt"
    answer.write_text("Towing costs $75 and fuel delivery costs $45.")
    proc = _run_cli(["suggest-claims", "--file", str(answer)])
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    suggestions = out["suggestions"]
    assert out["label"] == "suggested_claims_not_verified"
    assert len(suggestions) >= 2
    assert all(s["label"] == "suggestion" for s in suggestions)
    assert out["suggestion_set_digest"].startswith("sha256:")


def test_get_source_status_cli(demo_db_path):
    proc = _run_cli(["get-source-status", "--source", demo_db_path])
    assert proc.returncode == 0
    out = json.loads(proc.stdout)
    assert out["snapshot_method"] == "full_export_sha256"
    assert out["schema_version"] == "1"


def test_verify_cli(demo_db_path, tmp_path):
    answer = tmp_path / "answer.txt"
    answer.write_text("Towing costs $75.")
    proc = _run_cli([
        "verify", "--source", demo_db_path, "--file", str(answer),
        "--claims", json.dumps([{"claim_id": "c1", "text": "Towing costs $75.", "materiality": "material"}]),
        "--as-of", "2026-06-01T00:00:00Z",
    ])
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["receipt"]["overall_decision"] == "PASS"
    assert out["receipt"]["deterministic_digest"].startswith("sha256:")
