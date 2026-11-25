"""Affirmed CLI (spec §2, §13).

Subcommands: demo / suggest-claims / install-config / inspect /
get-source-status / verify / eval.

Zero runtime dependencies beyond the standard library. Deterministic paths
make no network calls.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from . import SOFTWARE_VERSION
from .config import Policy
from .demo_data import (
    EVAL_SET,
    EVAL_SET_DISCLAIMER,
    SCENARIO_A_CLAIM,
    SCENARIO_B_CLAIM,
    SCENARIO_C_CLAIM,
    SCENARIO_D_CLAIM,
    build_demo_db,
    scripted_advisory_script,
)
from .errors import ServiceError
from .service import AffirmedService


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# demo
# --------------------------------------------------------------------------- #
def _run_demo() -> int:
    """Run Scenarios A–D against a temp demo DB with the scripted advisor."""
    print(f"Affirmed v{SOFTWARE_VERSION} — demo")
    print("Fictional roadside-assistance provider. All data is fictional.")
    print("Scripted advisor double used for Scenarios B, C, D — no live provider.")
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "demo_evidence.db")
        build_demo_db(db_path)
        from .semantic import ScriptedAdvisor

        advisor = ScriptedAdvisor(scripted_advisory_script())
        policy = Policy(source_path=db_path)
        service = AffirmedService(policy, advisor=advisor)

        scenarios = [
            (
                "Scenario A — missing required field",
                SCENARIO_A_CLAIM,
                "deterministic",
            ),
            (
                "Scenario B — paraphrase gap",
                SCENARIO_B_CLAIM,
                "auto",
            ),
            (
                "Scenario C — auditor overreach",
                SCENARIO_C_CLAIM,
                "auto",
            ),
            (
                "Scenario D — direct prompt injection",
                SCENARIO_D_CLAIM,
                "semantic",  # force advisory so untrusted-evidence handling + safe advisory failure are demonstrated (#20)
            ),
        ]

        for title, claim_text, mode in scenarios:
            print(f"=== {title} ===")
            print(f"  claim: {claim_text!r}")
            result = service.verify_answer(
                answer=claim_text,
                claims=[{"claim_id": "c1", "text": claim_text, "materiality": "material"}],
                audit_mode=mode,
                as_of="2026-06-01T00:00:00Z",
            )
            receipt = result["receipt"]
            claims_block = receipt.get("claims") or []
            if claims_block:
                for c in claims_block:
                    verdict = c.get("deterministic_verdict")
                    status = c.get("evaluation_status")
                    print(f"  deterministic_verdict: {verdict}  ({status})")
                    for el in c.get("elements", []):
                        print(
                            f"    element {el['element']!r} kind={el['kind']}"
                            f" status={el['status']} reasons={el['reasons']}"
                        )
            else:
                print(f"  abstention: {receipt.get('abstention', {}).get('code')}")
            print(f"  overall_decision: {receipt['overall_decision']}")
            semantic = receipt.get("semantic")
            if semantic:
                for pc in semantic.get("per_claim", []):
                    label = semantic.get("simulated_label") or ""
                    print(
                        f"  advisory: {pc.get('advisory_status')}"
                        f" result={pc.get('advisory_result')} {label}"
                    )
            print(f"  deterministic_digest: {receipt['deterministic_digest']}")
            print()

    print("Demo complete. All data fictional; scripted advisor — not live provider results.")
    return 0


# --------------------------------------------------------------------------- #
# suggest-claims
# --------------------------------------------------------------------------- #
def _run_suggest_claims(args: argparse.Namespace) -> int:
    from .claims import suggest_claims_for_answer, suggestion_set_digest

    text = Path(args.file).read_text(encoding="utf-8")
    suggestions = suggest_claims_for_answer(text)
    digest_val = suggestion_set_digest(suggestions)
    _print_json(
        {
            "suggestions": suggestions,
            "suggestion_set_digest": digest_val,
            "label": "suggested_claims_not_verified",
            "note": "Review and resubmit via verify_answer with claims_source=suggested_accepted",
        }
    )
    return 0


# --------------------------------------------------------------------------- #
# install-config
# --------------------------------------------------------------------------- #
def _run_install_config(args: argparse.Namespace) -> int:
    if args.print_config:
        policy = Policy()
        _print_json(
            {
                "policy": policy.to_dict(),
                "config_hash": policy.config_hash,
                "mcp_servers": {
                    "affirmed": {
                        "command": "affirmed-mcp",
                        "args": ["serve"],
                        "env": {
                            "AFFIRMED_SOURCE_PATH": "/absolute/path/to/evidence.db"
                        },
                    }
                },
                "note": (
                    "Copy the mcp_servers block into your MCP client config."
                    " Set AFFIRMED_SOURCE_PATH to your evidence database."
                ),
            }
        )
        return 0
    print("install-config requires --print", file=sys.stderr)
    return 2


# --------------------------------------------------------------------------- #
# inspect
# --------------------------------------------------------------------------- #
def _run_inspect(args: argparse.Namespace) -> int:
    """Launch the MCP inspector (requires the optional 'mcp' extra)."""
    try:
        import mcp  # noqa: F401
    except ImportError:
        print(
            "The 'mcp' extra is required for the inspector.\n"
            "Install with:  pipx install 'affirmed-mcp[mcp]'\n"
            "Then run:     affirmed-mcp inspect",
            file=sys.stderr,
        )
        return 1
    # If we get here the SDK is available; the actual inspector launch is
    # delegated to the MCP SDK's CLI entry point.
    import subprocess

    cmd = [sys.executable, "-m", "mcp.cli", "dev", "affirmed_mcp.mcp_server:server"]
    if args.source:
        env = {"AFFIRMED_SOURCE_PATH": args.source}
    else:
        env = {}
    return subprocess.call(cmd, env={**__import__("os").environ, **env})


# --------------------------------------------------------------------------- #
# get-source-status
# --------------------------------------------------------------------------- #
def _run_get_source_status(args: argparse.Namespace) -> int:
    policy = Policy.load(source_path=args.source) if args.source else Policy()
    service = AffirmedService(policy)
    try:
        status = service.get_source_status()
    except ServiceError as exc:
        _print_json({"error": exc.to_envelope()})
        return 1
    _print_json(status)
    return 0


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #
def _run_verify(args: argparse.Namespace) -> int:
    answer = Path(args.file).read_text(encoding="utf-8")
    claims = json.loads(args.claims) if args.claims else None
    policy = Policy.load(source_path=args.source) if args.source else Policy()
    service = AffirmedService(policy)
    try:
        result = service.verify_answer(
            answer=answer,
            claims=claims,
            audit_mode=args.audit_mode,
            as_of=args.as_of,
        )
    except ServiceError as exc:
        _print_json({"error": exc.to_envelope()})
        return 1
    _print_json(result)
    return 0


# --------------------------------------------------------------------------- #
# eval
# --------------------------------------------------------------------------- #
def _run_eval(args: argparse.Namespace) -> int:
    """Run the 12-example fictional labeled demo set."""
    print(EVAL_SET_DISCLAIMER)
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "eval_evidence.db")
        build_demo_db(db_path)
        policy = Policy(source_path=db_path)
        # Deterministic eval only — no advisor needed (spec #44).
        service = AffirmedService(policy)

        results: list[dict[str, Any]] = []
        correct = 0
        total = 0

        for example in EVAL_SET:
            claim = {
                "claim_id": example["id"],
                "text": example["claim"],
                "subject_id": example.get("subject_id"),
                "materiality": "material",
            }
            result = service.verify_answer(
                answer=example["claim"],
                claims=[claim],
                audit_mode="deterministic",
                as_of="2026-06-01T00:00:00Z",
            )
            receipt = result["receipt"]
            overall = receipt["overall_decision"]
            claims_block = receipt.get("claims") or []
            verdict = None
            eval_status = None
            if claims_block:
                verdict = claims_block[0].get("deterministic_verdict")
                eval_status = claims_block[0].get("evaluation_status")
            else:
                eval_status = "UNRESOLVED"

            expected_verdict = example.get("expected_verdict")
            expected_overall = example.get("expected_overall")
            expected_status = example.get("expected_evaluation_status", "EVALUATED")

            ok = overall == expected_overall
            if expected_verdict is not None:
                ok = ok and verdict == expected_verdict
            else:
                ok = ok and eval_status == expected_status

            total += 1
            if ok:
                correct += 1

            results.append(
                {
                    "id": example["id"],
                    "claim": example["claim"],
                    "expected_overall": expected_overall,
                    "actual_overall": overall,
                    "expected_verdict": expected_verdict,
                    "actual_verdict": verdict,
                    "evaluation_status": eval_status,
                    "expected_reason": example["reason"],
                    "match": ok,
                }
            )

        # Confusion-matrix-style tallies
        supported_correct = sum(
            1 for r in results if r["actual_verdict"] == "SUPPORTED" and r["expected_verdict"] == "SUPPORTED"
        )
        supported_total_pred = sum(1 for r in results if r["actual_verdict"] == "SUPPORTED")
        contradicted_correct = sum(
            1 for r in results
            if r["actual_verdict"] == "CONTRADICTED" and r["expected_verdict"] == "CONTRADICTED"
        )
        contradicted_total_actual = sum(1 for r in results if r["expected_verdict"] == "CONTRADICTED")
        abstain_correct = sum(1 for r in results if r["actual_overall"] == "ABSTAIN" and r["expected_overall"] == "ABSTAIN")
        abstain_total_actual = sum(1 for r in results if r["expected_overall"] == "ABSTAIN")

        _print_json(
            {
                "disclaimer": EVAL_SET_DISCLAIMER,
                "total": total,
                "correct": correct,
                "accuracy": round(correct / total, 4) if total else 0,
                "metrics": {
                    "supported_precision": (
                        round(supported_correct / supported_total_pred, 4) if supported_total_pred else None
                    ),
                    "contradiction_recall": (
                        round(contradicted_correct / contradicted_total_actual, 4)
                        if contradicted_total_actual
                        else None
                    ),
                    "abstention_rate": (
                        round(abstain_correct / abstain_total_actual, 4) if abstain_total_actual else None
                    ),
                    "coverage": "submitted_claims_only",
                },
                "results": results,
            }
        )
    return 0


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="affirmed-mcp",
        description="Evidence-checking MCP server and CLI for AI agents.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {SOFTWARE_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("demo", help="Run Scenarios A–D demo with scripted advisor")

    p_suggest = sub.add_parser("suggest-claims", help="Suggest atomic claims from an answer file")
    p_suggest.add_argument("--file", required=True, help="Path to answer text file")

    p_install = sub.add_parser("install-config", help="Print MCP client configuration")
    p_install.add_argument("--print", dest="print_config", action="store_true", help="Print default policy + MCP config")

    p_inspect = sub.add_parser("inspect", help="Launch MCP inspector (requires mcp extra)")
    p_inspect.add_argument("--source", help="Path to evidence database")

    p_status = sub.add_parser("get-source-status", help="Print source snapshot status")
    p_status.add_argument("--source", help="Path to evidence database")

    p_verify = sub.add_parser("verify", help="Verify an answer against claims")
    p_verify.add_argument("--file", required=True, help="Path to answer text file")
    p_verify.add_argument("--claims", help="JSON array of claim objects")
    p_verify.add_argument("--audit-mode", default="deterministic", choices=["deterministic", "semantic", "auto"])
    p_verify.add_argument("--as-of", help="ISO 8601 UTC timestamp")
    p_verify.add_argument("--source", help="Path to evidence database")

    p_eval = sub.add_parser("eval", help="Run the 12-example fictional demo set")
    p_eval.add_argument("--source", help="Path to evidence database (defaults to temp demo DB)")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "demo": lambda a: _run_demo(),
        "suggest-claims": _run_suggest_claims,
        "install-config": _run_install_config,
        "inspect": _run_inspect,
        "get-source-status": _run_get_source_status,
        "verify": _run_verify,
        "eval": lambda a: _run_eval(a),
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    try:
        return handler(args)
    except ServiceError as exc:
        _print_json({"error": exc.to_envelope()})
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
