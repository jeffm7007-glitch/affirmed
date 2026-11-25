"""MCP transport tests (criteria #2, #40, #46, #47, #64-partial)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from affirmed_mcp.mcp_server import PROTOCOL_VERSION, VendoredStdioServer, _TOOL_SPECS

TOOL_NAMES = ["retrieve_evidence", "verify_answer", "get_source_status"]


class _Harness:
    """Drives the vendored server in-process for request/response tests."""

    def __init__(self, service):
        self.server = VendoredStdioServer(service)
        self._next_id = 0

    def request(self, method, params=None):
        self._next_id += 1
        response = self.server.handle_message({
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params or {},
        })
        return response

    def notify(self, method, params=None):
        return self.server.handle_message({"jsonrpc": "2.0", "method": method, "params": params or {}})


@pytest.fixture()
def harness(service):
    return _Harness(service)


def test_initialize(harness):
    response = harness.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}})
    assert response["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert response["result"]["serverInfo"]["name"] == "affirmed-mcp"
    assert response["result"]["capabilities"]["tools"] == {}


def test_tools_list_exactly_three(harness):
    """#2: the MCP surface is exactly the three documented tools."""
    response = harness.request("tools/list")
    tools = response["result"]["tools"]
    assert sorted(t["name"] for t in tools) == sorted(TOOL_NAMES)
    assert len(tools) == 3


def test_ping(harness):
    assert harness.request("ping")["result"] == {}


def test_notifications_acknowledged_silently(harness):
    assert harness.notify("notifications/initialized") is None
    assert harness.notify("notifications/cancelled") is None


def test_tools_call_roundtrip(harness, demo_db_path):
    status = harness.request("tools/call", {"name": "get_source_status", "arguments": {}})
    assert status["result"]["structuredContent"]["source_snapshot_id"].startswith("sha256:")

    retr = harness.request("tools/call", {"name": "retrieve_evidence", "arguments": {"query": "towing"}})
    assert len(retr["result"]["structuredContent"]["records"]) > 0

    verify = harness.request("tools/call", {
        "name": "verify_answer",
        "arguments": {
            "answer": "Towing costs $75.",
            "claims": [{"claim_id": "c1", "text": "Towing costs $75.", "materiality": "material"}],
            "as_of": "2026-06-01T00:00:00Z",
        },
    })
    assert verify["result"]["structuredContent"]["receipt"]["overall_decision"] == "PASS"


def test_policy_overrides_rejected_as_iserror(harness):
    """#40: no per-request policy changes; surfaced as a stable tool error."""
    response = harness.request("tools/call", {
        "name": "verify_answer",
        "arguments": {
            "answer": "Towing costs $75.",
            "claims": [{"claim_id": "c1", "text": "Towing costs $75.", "materiality": "material"}],
            "policy_overrides": {"materiality_unknown_default": "non_material"},
        },
    })
    assert response["result"]["isError"] is True
    text = response["result"]["content"][0]["text"]
    envelope = json.loads(text)
    assert envelope["error"]["code"] == "INVALID_INPUT"
    assert "policy_overrides" in str(envelope["error"]["details"])


def test_error_envelopes_stable(harness):
    """#46: malformed input and unknown methods return documented error shapes."""
    bad_params = harness.request("tools/call", {"name": "retrieve_evidence", "arguments": {"limit": 0}})
    assert bad_params["result"]["isError"] is True
    unknown_method = harness.request("nope/method")
    assert unknown_method["error"]["code"] == -32601
    unknown_tool = harness.request("tools/call", {"name": "sql_exec", "arguments": {}})
    assert unknown_tool["result"]["isError"] is True


def test_no_arbitrary_sql_reachable(harness):
    """#47: only the three fixed tools exist; nothing accepting SQL."""
    assert set(_TOOL_SPECS) == set(TOOL_NAMES)
    for name in TOOL_NAMES:
        spec = _TOOL_SPECS[name]
        assert "sql" not in json.dumps(spec).lower()
    response = harness.request("tools/call", {"name": "get_source_status", "arguments": {"sql": "DROP TABLE x"}})
    assert response["result"]["isError"] is True


def test_stdio_subprocess_roundtrip(tmp_path):
    """End-to-end over real pipes: initialize -> tools/list -> tools/call -> ping."""
    from affirmed_mcp.demo_data import build_demo_db

    db = str(tmp_path / "mcp.db")
    build_demo_db(db)
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "get_source_status", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 4, "method": "ping"},
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "affirmed_mcp.mcp_server"],
        input="\n".join(json.dumps(m) for m in messages) + "\n",
        capture_output=True, text=True,
        env={"AFFIRMED_SOURCE_PATH": db, "PATH": "/usr/bin:/bin"},
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert [line["id"] for line in lines] == [1, 2, 3, 4]
    assert lines[1]["result"]["tools"].__len__() == 3
    assert lines[2]["result"]["structuredContent"]["schema_version"] == "1"
    assert lines[3]["result"] == {}


def test_parse_error_line_is_stable(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "affirmed_mcp.mcp_server"],
        input="{not json\n",
        capture_output=True, text=True,
        env={"AFFIRMED_SOURCE_PATH": str(tmp_path / "none.db"), "PATH": "/usr/bin:/bin"},
        timeout=60,
    )
    assert proc.returncode == 0
    response = json.loads(proc.stdout.strip().splitlines()[0])
    assert response["error"]["code"] == -32700
    assert response["id"] is None
