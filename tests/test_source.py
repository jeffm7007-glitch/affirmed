"""Tests for evidence source snapshot + locking (spec §7; criteria #25, #26, #39)."""

from __future__ import annotations

import sqlite3

import pytest

from affirmed_mcp.config import Policy
from affirmed_mcp.errors import ServiceError
from affirmed_mcp.schema import ALL_FIELDS, validate_typed_tuple
from affirmed_mcp.source import (
    SourceIdentity,
    SourceSession,
    full_export_snapshot_id,
    open_source,
    source_file_metadata,
)


def _snapshot(db_path):
    conn = open_source(db_path)
    with SourceSession(conn, Policy()) as session:
        snap = session.resolve_snapshot(db_path)
    conn.close()
    return snap


class TestSourceSnapshotId:
    def test_snapshot_id_format(self, demo_db):
        snap = _snapshot(demo_db)
        assert snap["source_snapshot_id"].startswith("sha256:")
        assert len(snap["source_snapshot_id"]) == 7 + 64
        assert snap["snapshot_method"] == "full_export_sha256"

    def test_snapshot_id_deterministic(self, demo_db):
        s1 = _snapshot(demo_db)["source_snapshot_id"]
        s2 = _snapshot(demo_db)["source_snapshot_id"]
        assert s1 == s2

    def test_snapshot_id_changes_on_write(self, demo_db):
        s1 = _snapshot(demo_db)["source_snapshot_id"]
        conn = sqlite3.connect(demo_db)
        conn.execute(
            "INSERT INTO evidence_records (id,text,source,tags) VALUES ('extra','t','s','[]')"
        )
        conn.commit()
        conn.close()
        s2 = _snapshot(demo_db)["source_snapshot_id"]
        assert s1 != s2

    def test_snapshot_id_ignores_cursor_order(self, tmp_path):
        db = str(tmp_path / "order.db")
        conn = sqlite3.connect(db)
        columns = ", ".join(f"{f} TEXT" for f in ALL_FIELDS)
        conn.execute(f"CREATE TABLE evidence_records ({columns})")
        conn.execute(
            "CREATE TABLE affirmed_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO affirmed_meta (key, value) VALUES ('schema_version', '1')"
        )
        conn.execute(
            "INSERT INTO evidence_records (id,text,source,tags) VALUES ('b','text b','src','[]')"
        )
        conn.commit()
        conn.close()
        snap1 = _snapshot(db)["source_snapshot_id"]
        # Delete and re-insert in reverse order
        conn2 = sqlite3.connect(db)
        conn2.execute("DELETE FROM evidence_records")
        conn2.execute(
            "INSERT INTO evidence_records (id,text,source,tags) VALUES ('b','text b','src','[]')"
        )
        conn2.execute(
            "INSERT INTO evidence_records (id,text,source,tags) VALUES ('a','text a','src','[]')"
        )
        conn2.commit()
        conn2.close()
        snap2 = _snapshot(db)["source_snapshot_id"]
        assert snap1 == snap2


class TestSourceSnapshotRecords:
    def test_records_loaded(self, demo_db):
        snap = _snapshot(demo_db)
        assert len(snap["records"]) > 0

    def test_record_ids(self, demo_db):
        snap = _snapshot(demo_db)
        ids = [r["id"] for r in snap["records"]]
        assert "r_towing_price" in ids
        assert "r_towing_availability" in ids


class TestWALMode:
    def test_wal_mode(self, demo_db):
        conn = sqlite3.connect(demo_db)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode == "wal"

    def test_foreign_keys_on(self, demo_db):
        conn = open_source(demo_db)
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        conn.close()
        assert fk == 1


class TestCorruptDatabase:
    def test_corrupt_db_source_error(self, tmp_path):
        bad = tmp_path / "corrupt.db"
        bad.write_bytes(b"this is not a sqlite database")
        with pytest.raises(ServiceError) as exc_info:
            open_source(str(bad))
        assert exc_info.value.code == "SOURCE_ERROR"


class TestSchemaMismatch:
    def test_wrong_schema_version(self, tmp_path):
        db = str(tmp_path / "wrong.db")
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE affirmed_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO affirmed_meta (key, value) VALUES ('schema_version', '999')"
        )
        conn.execute(
            "CREATE TABLE evidence_records (id TEXT PRIMARY KEY,text TEXT NOT NULL)"
        )
        conn.commit()
        conn.close()
        conn2 = open_source(db)
        with pytest.raises(ServiceError) as exc_info:
            with SourceSession(conn2, Policy()) as session:
                session.resolve_snapshot(db)
        assert exc_info.value.code == "SOURCE_SCHEMA_MISMATCH"
        conn2.close()


class TestSourceFileMetadata:
    def test_metadata(self, demo_db):
        meta = source_file_metadata(demo_db)
        assert "file_size_bytes" in meta
        assert meta["file_size_bytes"] > 0
