"""Vendored ND-JSON JSON-RPC stdio MCP transport (spec §13).

Base path uses only the standard library: newline-delimited JSON-RPC 2.0
messages on stdin/stdout. Exactly three tools — retrieve_evidence,
verify_answer, get_source_status — wired to service.AffirmedService.

An optional official-SDK path (FastMCP) is provided when the ``mcp`` extra
is installed; it exposes the same three tools and nothing else.

No network I/O occurs in either path. Diagnostics never go to stdout
(would corrupt the protocol); no debug payload logging (#63).
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Callable

from . import SOFTWARE_VERSION
from .config import Policy
from .errors import ServiceError, internal_error
from .service import AffirmedService, validate_tool_payload

PROTOCOL_VERSION = "2024-11-05"
JSONRPC = "2.0"

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "retrieve_evidence",
        "description": (
            "Lexical BM25 retrieval over the pinned evidence source. "
            "Returns records with record digests plus source snapshot identity. "
            "Scores are ranking signals, never calibrated probabilities."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Non-blank query text"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                "expected_source_snapshot_id": {"type": "string"},
                "as_of": {"type": "string", "description": "ISO 8601 UTC timestamp"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "verify_answer",
        "description": (
            "Verify an answer's submitted atomic claims against the pinned "
            "evidence source. Deterministic engine always on; optional semantic "
            "advisory can never change evidence-backed verdicts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "claims": {"type": "array", "items": {"type": "object"}},
                "audit_mode": {"type": "string", "enum": ["deterministic", "semantic", "auto"]},
                "expected_source_snapshot_id": {"type": "string"},
                "as_of": {"type": "string"},
                "caller_attested_complete": {"type": "boolean"},
                "claims_source": {"type": "string", "enum": ["caller", "suggested_accepted"]},
                "suggestion_set_digest": {"type": "string"},
            },
            "required": ["answer", "claims"],
        },
    },
    {
        "name": "get_source_status",
        "description": (
            "Establish the current source snapshot (full-export digest identity) "
            "and freshness metadata. No arguments."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
]

_TOOL_NAMES = [t["name"] for t in _TOOL_SPECS]


def build_service_from_env() -> AffirmedService:
    """Local configuration only; MCP requests can never carry policy changes (#40)."""
    policy_path = os.environ.get("AFFIRMED_POLICY_PATH") or None
    source_path = os.environ.get("AFFIRMED_SOURCE_PATH") or None
    policy = Policy.load(policy_path, source_path=source_path)
    return AffirmedService(policy)


def _call_tool(service: AffirmedService, tool: str, payload: dict[str, Any]) -> Any:
    if tool == "retrieve_evidence":
        return service.retrieve_evidence(**payload)
    if tool == "verify_answer":
        return service.verify_answer(**payload)
    if tool == "get_source_status":
        return service.get_source_status()
    raise ValueError(f"unknown tool {tool!r}")


class _JsonRpcError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class VendoredStdioServer:
    """Minimal ND-JSON JSON-RPC 2.0 loop: initialize / tools/list / tools/call / ping."""

    def __init__(self, service: AffirmedService, reader=None, writer=None):
        self.service = service
        self._reader = reader or sys.stdin
        self._writer = writer or sys.stdout
        self._handlers: dict[str, Callable[[Any], Any]] = {
            "initialize": self._initialize,
            "tools/list": lambda _p: {"tools": _TOOL_SPECS},
            "tools/call": self._tools_call,
            "ping": lambda _p: {},
        }

    def _initialize(self, _params: Any) -> dict[str, Any]:
        return {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "affirmed-mcp", "version": SOFTWARE_VERSION},
        }

    def _tools_call(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise _JsonRpcError(INVALID_PARAMS, "tools/call params must be an object")
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in _TOOL_NAMES:
            raise _JsonRpcError(INVALID_PARAMS, f"unknown tool {name!r}")
        if not isinstance(arguments, dict):
            raise _JsonRpcError(INVALID_PARAMS, "arguments must be an object")
        # Unknown top-level fields rejected as INVALID_INPUT before dispatch (#40/#51).
        try:
            payload = validate_tool_payload(name, arguments)
        except ServiceError as exc:
            return {
                "content": [
                    {"type": "text", "text": json.dumps({"error": exc.to_envelope()}, sort_keys=True)}
                ],
                "isError": True,
            }
        try:
            result = _call_tool(self.service, name, payload)
        except ServiceError as exc:
            # Stable documented error envelope, safe for ordinary clients (#46).
            return {
                "content": [
                    {"type": "text", "text": json.dumps({"error": exc.to_envelope()}, sort_keys=True)}
                ],
                "isError": True,
            }
        except Exception as exc:  # noqa: BLE001 — never leak stack traces or messages
            envelope = internal_error(details={"reason": type(exc).__name__}).to_envelope()
            return {
                "content": [
                    {"type": "text", "text": json.dumps({"error": envelope}, sort_keys=True)}
                ],
                "isError": True,
            }
        return {
            "content": [
                {"type": "text", "text": json.dumps(result, sort_keys=True, ensure_ascii=False)}
            ],
            "isError": False,
        }

    def _send(self, message: dict[str, Any]) -> None:
        self._writer.write(json.dumps(message, ensure_ascii=False) + "\n")
        self._writer.flush()

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        """Handle one decoded message; returns the response dict or None (notification)."""
        if not isinstance(message, dict) or message.get("jsonrpc") != JSONRPC:
            raise _JsonRpcError(INVALID_REQUEST, "not a JSON-RPC 2.0 request object")
        method = message.get("method")
        if not isinstance(method, str):
            raise _JsonRpcError(INVALID_REQUEST, "missing method")
        if "id" not in message:  # notification — acknowledge silently, never a response
            return None
        if method.startswith("notifications/"):
            return None
        handler = self._handlers.get(method)
        if handler is None:
            raise _JsonRpcError(METHOD_NOT_FOUND, f"unknown method {method!r}")
        return handler(message.get("params"))

    def serve_forever(self) -> int:
        for line in self._reader:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._send({"jsonrpc": JSONRPC, "id": None,
                            "error": {"code": PARSE_ERROR, "message": "parse error"}})
                continue
            request_id = message.get("id") if isinstance(message, dict) else None
            try:
                result = self.handle_message(message)
            except _JsonRpcError as exc:
                self._send({"jsonrpc": JSONRPC, "id": request_id,
                            "error": {"code": exc.code, "message": exc.message}})
                continue
            if result is not None:
                self._send({"jsonrpc": JSONRPC, "id": request_id, "result": result})
        return 0


def serve(service: AffirmedService | None = None) -> int:
    """Run the vendored stdio loop (module entry point)."""
    server = VendoredStdioServer(service or build_service_from_env())
    return server.serve_forever()


# --------------------------------------------------------------------------- #
# Optional official-SDK path (only when the `mcp` extra is installed, #2/#64).
# --------------------------------------------------------------------------- #
def build_sdk_server(service: AffirmedService | None = None):
    """FastMCP wrapper exposing exactly the same three tools.

    Returns None when the SDK is not installed (base package imports cleanly
    without it, #1).
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError:
        return None
    svc = service or build_service_from_env()
    mcp = FastMCP("affirmed-mcp")

    @mcp.tool(name="retrieve_evidence", description=_TOOL_SPECS[0]["description"])
    def retrieve_evidence(query: str, limit: int | None = None,
                          expected_source_snapshot_id: str | None = None,
                          as_of: str | None = None) -> dict[str, Any]:
        return svc.retrieve_evidence(query=query, limit=limit,
                                     expected_source_snapshot_id=expected_source_snapshot_id,
                                     as_of=as_of)

    @mcp.tool(name="verify_answer", description=_TOOL_SPECS[1]["description"])
    def verify_answer(answer: str, claims: list | None = None,
                      audit_mode: str | None = None,
                      expected_source_snapshot_id: str | None = None,
                      as_of: str | None = None,
                      caller_attested_complete: bool | None = None,
                      claims_source: str | None = None,
                      suggestion_set_digest: str | None = None) -> dict[str, Any]:
        return svc.verify_answer(answer=answer, claims=claims, audit_mode=audit_mode,
                                 expected_source_snapshot_id=expected_source_snapshot_id,
                                 as_of=as_of, caller_attested_complete=caller_attested_complete,
                                 claims_source=claims_source,
                                 suggestion_set_digest=suggestion_set_digest)

    @mcp.tool(name="get_source_status", description=_TOOL_SPECS[2]["description"])
    def get_source_status() -> dict[str, Any]:
        return svc.get_source_status()

    return mcp


#: Consumed by `mcp.cli dev affirmed_mcp.mcp_server:server` when the `mcp`
#: extra is installed; None in the base install.
server = build_sdk_server()


if __name__ == "__main__":
    sys.exit(serve())
