"""Shared fixtures for the Affirmed test suite (plan §9)."""

from __future__ import annotations

import socket

import pytest

from affirmed_mcp.config import Policy
from affirmed_mcp.demo_data import build_demo_db
from affirmed_mcp.semantic import ScriptedAdvisor
from affirmed_mcp.demo_data import scripted_advisory_script
from affirmed_mcp.service import AffirmedService

AS_OF = "2026-06-01T00:00:00Z"


@pytest.fixture()
def demo_db_path(tmp_path):
    path = str(tmp_path / "demo_evidence.db")
    build_demo_db(path)
    return path


@pytest.fixture()
def demo_db(demo_db_path):
    """Alias used by source-level tests: path to a freshly built demo DB."""
    return demo_db_path


@pytest.fixture()
def policy(demo_db_path):
    return Policy(source_path=demo_db_path)


@pytest.fixture()
def service(policy):
    return AffirmedService(policy)


@pytest.fixture()
def scripted_service(policy):
    return AffirmedService(policy, advisor=ScriptedAdvisor(scripted_advisory_script()))


class _BlockedSocket(socket.socket):
    def connect(self, *args, **kwargs):  # pragma: no cover - trivial
        raise AssertionError("network access attempted in deterministic path")


@pytest.fixture()
def block_sockets(monkeypatch):
    """Hard-block all outbound TCP from this process (#8, #42)."""

    def _no_connect(*args, **kwargs):
        raise AssertionError("network access attempted in deterministic path")

    monkeypatch.setattr(socket.socket, "connect", _no_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", lambda *a, **k: -1)
    monkeypatch.setattr(socket, "create_connection", _no_connect)
    monkeypatch.setattr(socket, "getaddrinfo", _no_connect)
    return True
