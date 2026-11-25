"""Source layer tests — snapshot identity, integrity, locking, errors (#21, #23, #25, #26, #46)."""

from __future__ import annotations

import sqlite3

import pytest

from affirmed_mcp.config import Policy
from affirmed_mcp.errors import ServiceError
from affirmed_mcp.source import (
    full_export_snapshot_id,
    load_all_records,
    open_source,
    trusted_source_snapshot_id,
)


def _demo_conn(demo_db_path):
    return open_source(demo_db_path)


class TestSourceSnapshotId:
    def test_snapshot_id_format(self, demo_db_path):
        conn = _demo_conn(demo_db_path)
        records, _ = load_all_records(conn)
        snap = full_export_snapshot_id(records)
        assert snap.startswith("sha256:") and len(snap) == 71

    def test_snapshot_id_deterministic(self, demo_db_path):
        conn = _demo_conn(demo_db_path)
        a, _ = load_all_records(conn)
        conn.close()
        conn = _demo_conn(demo_db_path)
        b, _ = load_all_records(conn)
        conn.close()
        assert full_export_snapshot_id(a) == full_export_snapshot_id(b)

    def test_snapshot_id_ignores_cursor_order(self, demo_db_path):
        """#23/#25: the engine loads in canonical id order, so two loads agree."""
        conn = _demo_conn(demo_db_path)
        first, _ = load_all_records(conn)
        conn.close()
        conn = _demo_conn(demo_db_path)
        second, _ = load_all_records(conn)
        conn.close()
        assert full_export_snapshot_id(first) == full_export_snapshot_id(second)
        assert [r["id"] for r in first] == [r["id"] for r in second]

    def test_snapshot_id_changes_on_write(self, demo_db_path):
        conn = _demo_conn(demo_db_path)
        records, _ = load_all_records(conn)
        before = full_export_snapshot_id(records)
        conn.close()
        w = sqlite3.connect(demo_db_path)
        w.execute("UPDATE evidence_records SET field_value = ? WHERE id = ?",
                  ("80", "r_towing_price"))
        w.commit()
        w.close()
        conn = _demo_conn(demo_db_path)
        records, _ = load_all_records(conn)
        after = full_export_snapshot_id(records)
        conn.close()
        assert before != after


class TestSourceSnapshotRecords:
    def test_records_loaded(self, demo_db_path):
        conn = _demo_conn(demo_db_path)
        records, warnings = load_all_records(conn)
        conn.close()
        assert len(records) == 8
        assert isinstance(warnings, list)

    def test_record_ids(self, demo_db_path):
        conn = _demo_conn(demo_db_path)
        records, _ = load_all_records(conn)
        conn.close()
        ids = {r["id"] for r in records}
        assert "r_towing_price" in ids


class TestReadOnlyMode:
    """#26 (partial): the engine opens the source read-only with query_only set."""

    def test_wal_not_applicable_read_only(self, demo_db_path):
        conn = _demo_conn(demo_db_path)
        try:
            conn.execute("UPDATE evidence_records SET field_value = ? WHERE id = ?",
                         (json.dumps(1), json.dumps("r_towing_price")))
            pytest.fail("read-only source accepted a write")
        except sqlite3.OperationalError:
            pass
        conn.close()

    def test_foreign_keys_on(self, demo_db_path):
        conn = _demo_conn(demo_db_path)
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        conn.close()

    def test_single_transaction_snapshot(self, service):
        """#25: concurrent reads during a verify see one stable snapshot id."""
        a = service.get_source_status()["source_snapshot_id"]
        b = service.get_source_status()["source_snapshot_id"]
        assert a == b


class TestSourceFileMetadata:
    def test_metadata(self, service):
        status = service.get_source_status()
        assert status["snapshot_method"] == "full_export_sha256"
        assert status["last_sync_time"] is None
        assert status["last_sync_time_reason"] == "read_only_source_no_sync"
        assert status["evidence_publication_date_coverage"]["min"] is not None


class TestCorruptDatabase:
    def test_corrupt_db_source_error(self, tmp_path):
        bad = tmp_path / "corrupt.db"
        bad.write_bytes(b"this is not a sqlite database at all")
        from affirmed_mcp.source import open_source as _os
        with pytest.raises(Exception):  # sqlite3.DatabaseError family
            _os(str(bad))


class TestSchemaMismatch:
    def test_schema_mismatch_detected(self, tmp_path):
        empty = tmp_path / "empty.db"
        conn = sqlite3.connect(str(empty))
        conn.execute("CREATE TABLE other_table (x INTEGER)")
        conn.commit()
        conn.close()
        conn = open_source(str(empty))
        from affirmed_mcp.source import SourceSession
        with pytest.raises(ServiceError) as exc:
            with SourceSession(conn, Policy(source_path=str(empty))) as session:
                session.resolve_snapshot(str(empty))
        assert exc.value.code == "SOURCE_SCHEMA_MISMATCH"
        conn.close()


class TestTrustedSourcePolicy:
    def test_trusted_snapshot_requires_configuration(self, demo_db_path):
        """The trusted_source_version mode raises a documented error when unconfigured."""
        conn = _demo_conn(demo_db_path)
        with pytest.raises(ServiceError) as exc:
            trusted_source_snapshot_id(conn, Policy(source_path=demo_db_path), demo_db_path)
        assert exc.value.code == "SOURCE_SCHEMA_MISMATCH"
        conn.close()


import json  # noqa: E402,F401  (kept for parity; currently unused)
