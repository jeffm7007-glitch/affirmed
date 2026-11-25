"""Eval-command tests (criteria #44, #45)."""

from __future__ import annotations

import json
import subprocess
import sys

from affirmed_mcp.demo_data import EVAL_SET, EVAL_SET_DISCLAIMER


def _run_eval_cli(extra_args=None):
    return subprocess.run(
        [sys.executable, "-m", "affirmed_mcp.cli", "eval", *(extra_args or [])],
        capture_output=True, text=True, timeout=180,
    )


def test_eval_set_is_fictional_labeled_twelve():
    assert len(EVAL_SET) == 12
    assert "NOT a benchmark" in EVAL_SET_DISCLAIMER


def _parse_report(proc):
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert "NOT a benchmark" in lines[0]
    return json.loads("\n".join(lines[1:]))


def test_metrics_reported_separately():
    """#44: precision, recall, abstention, coverage are distinct reported metrics."""
    report = _parse_report(_run_eval_cli())
    metrics = report["metrics"]
    for key in ("supported_precision", "contradiction_recall", "abstention_rate", "coverage"):
        assert key in metrics, f"missing metric {key}"
    assert metrics["coverage"] == "submitted_claims_only"
    assert report["accuracy"] == 1.0
    assert report["correct"] == 12


def test_disclaimer_present():
    """#45: the disclaimer is printed before the JSON report and embedded in it."""
    report = _parse_report(_run_eval_cli())
    assert "NOT a benchmark" in report["disclaimer"]


def test_eval_matches_expected_labels():
    """Every labeled fictional example must match its expected verdict/overall."""
    report = _parse_report(_run_eval_cli())
    assert all(r["match"] for r in report["results"])
    by_id = {r["id"]: r for r in report["results"]}
    assert by_id["demo-04"]["actual_verdict"] == "UNSUPPORTED"  # Scenario A slice
    assert by_id["demo-03"]["actual_verdict"] == "CONTRADICTED"
    assert by_id["demo-01"]["actual_overall"] == "PASS"


def test_eval_with_explicit_source(demo_db_path):
    report = _parse_report(_run_eval_cli(["--source", demo_db_path]))
    assert report["correct"] == 12
