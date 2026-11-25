"""Read-only SQLite source adapter and snapshot manager (spec §3, §8A, §9).

- Opened with URI ``mode=ro`` and ``PRAGMA query_only=ON``.
- ``immutable=1`` is NOT used (concurrent writers are in scope).
- Explicit transaction management: one consistent read transaction for the
  snapshot resolution and all evidence reads.
- Malformed, corrupt, or unsupported databases are safe failures; never a
  silent fallback to a different database.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import digest
from .config import Policy
from .errors import ServiceError, SOURCE_ERROR, SOURCE_SCHEMA_MISMATCH, SOURCE_UNAVAILABLE
from .schema import ALL_FIELDS, REQUIRED_COLUMNS, row_to_record, RecordValidationError

META_TABLE = "affirmed_meta"
EVIDENCE_TABLE = "evidence_records"

TRUSTED_SOURCE_VERSION_TRUST_STATEMENT = (
    "Trust assumption: the source maintainer changes the configured version "
    "identifier for every logical source change."
)


@dataclass
class SourceIdentity:
    path: str
    schema_version: str | None


def open_source(path: str) -> sqlite3.Connection:
    """Open the configured SQLite source read-only."""
    if not path:
        raise ServiceError(SOURCE_UNAVAILABLE, "no source path configured", retryable=False)
    if not os.path.exists(path):
        raise ServiceError(
            SOURCE_UNAVAILABLE, "source database does not exist", retryable=False, details={"path": path}
        )
    uri = f"file:{Path(path).absolute()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA foreign_keys=ON")
        # Fail closed on corrupt/unreadable headers instead of lazily erroring later.
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as exc:
        raise ServiceError(
            SOURCE_ERROR, "could not open source read-only", retryable=False,
            details={"reason": type(exc).__name__},
        ) from exc
    return conn


def schema_version(conn: sqlite3.Connection) -> str | None:
    try:
        row = conn.execute(
            f"SELECT value FROM {META_TABLE} WHERE key = 'schema_version'"
        ).fetchone()
    except sqlite3.Error:
        return None
    return row["value"] if row else None


def validate_schema(conn: sqlite3.Connection) -> None:
    """Fail closed on schema mismatch; never silently interpret unknown columns."""
    try:
        rows = conn.execute(f"PRAGMA table_info({EVIDENCE_TABLE})").fetchall()
    except sqlite3.DatabaseError as exc:
        raise ServiceError(
            SOURCE_ERROR, "source database is malformed or corrupt", retryable=False,
            details={"reason": type(exc).__name__},
        ) from exc
    if not rows:
        raise ServiceError(
            SOURCE_SCHEMA_MISMATCH,
            f"source table {EVIDENCE_TABLE!r} is missing",
            retryable=False,
            details={"table": EVIDENCE_TABLE},
        )
    present = {row["name"] for row in rows}
    missing = sorted(set(REQUIRED_COLUMNS) - present)
    if missing:
        raise ServiceError(
            SOURCE_SCHEMA_MISMATCH,
            "source schema missing required columns",
            retryable=False,
            details={"missing_columns": missing},
        )


def load_all_records(conn: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[str]]:
    """Load every record ordered by id; invalid typed tuples are rejected with warnings."""
    columns = ", ".join(ALL_FIELDS)
    rows = conn.execute(f"SELECT {columns} FROM {EVIDENCE_TABLE} ORDER BY id ASC").fetchall()
    records, warnings = [], []
    for row in rows:
        try:
            records.append(row_to_record(row))
        except RecordValidationError as exc:
            warnings.append(f"rejected invalid evidence record: {exc}")
    return records, warnings


def full_export_snapshot_id(records: list[dict[str, Any]]) -> str:
    """SHA-256 over a canonical export of the complete logical source."""
    canonical = [
        {k: rec.get(k) for k in ALL_FIELDS if rec.get(k) is not None or k == "tags"}
        for rec in records
    ]
    return digest({"snapshot_method": "full_export_sha256", "records": canonical})


def trusted_source_snapshot_id(conn: sqlite3.Connection, policy: Policy, source_path: str) -> str:
    table = policy.trusted_source_version_table
    column = policy.trusted_source_version_column
    if not table or not column:
        raise ServiceError(
            SOURCE_SCHEMA_MISMATCH,
            "trusted_source_version snapshot requires configured table and column",
            retryable=False,
        )
    # Identifier quote-wrap against injection; identifiers are local config, not client input.
    if not (table.replace("_", "").isalnum() and column.replace("_", "").isalnum()):
        raise ServiceError(
            SOURCE_SCHEMA_MISMATCH, "trusted source version identifiers must be alphanumeric",
            retryable=False,
        )
    try:
        row = conn.execute(f'SELECT "{column}" AS v FROM "{table}" LIMIT 1').fetchone()
    except sqlite3.Error as exc:
        raise ServiceError(
            SOURCE_SCHEMA_MISMATCH,
            "trusted source version table/column unreadable",
            retryable=False,
            details={"reason": type(exc).__name__},
        ) from exc
    version_value = row["v"] if row else None
    if version_value is None or str(version_value) == "":
        raise ServiceError(
            SOURCE_SCHEMA_MISMATCH,
            "trusted source version identifier is empty",
            retryable=False,
        )
    return digest(
        {
            "snapshot_method": "trusted_source_version",
            "source_path": str(Path(source_path).absolute()),
            "schema_version": schema_version(conn),
            "version": str(version_value),
        }
    )


class SourceSession:
    """One consistent read transaction over the source.

    The first read establishes the SQLite snapshot; full-source export,
    trusted-version reads, and evidence reads share this transaction.
    """

    def __init__(self, conn: sqlite3.Connection, policy: Policy):
        self.conn = conn
        self.policy = policy
        self._active = False

    def __enter__(self) -> "SourceSession":
        try:
            self.conn.execute("BEGIN")
        except sqlite3.Error as exc:
            raise ServiceError(
                SOURCE_ERROR, "could not begin source read transaction", retryable=True,
                details={"reason": type(exc).__name__},
            ) from exc
        self._active = True
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._active:
            try:
                if exc_type is None:
                    self.conn.execute("COMMIT")
                else:
                    self.conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            self._active = False
        return False

    def resolve_snapshot(self, source_path: str) -> dict[str, Any]:
        """Resolve the current logical snapshot INSIDE this transaction."""
        validate_schema(self.conn)
        if self.policy.source_snapshot_method == "full_export_sha256":
            records, warnings = load_all_records(self.conn)
            return {
                "source_snapshot_id": full_export_snapshot_id(records),
                "snapshot_method": "full_export_sha256",
                "snapshot_trust": None,
                "records": records,
                "load_warnings": warnings,
            }
        snapshot_id = trusted_source_snapshot_id(self.conn, self.policy, source_path)
        return {
            "source_snapshot_id": snapshot_id,
            "snapshot_method": "trusted_source_version",
            "snapshot_trust": TRUSTED_SOURCE_VERSION_TRUST_STATEMENT,
            "records": None,
            "load_warnings": [],
        }


def source_file_metadata(path: str) -> dict[str, Any]:
    try:
        st = os.stat(path)
    except OSError:
        return {"path": path, "file_mtime": None}
    return {"path": path, "file_mtime": st.st_mtime, "file_size_bytes": st.st_size}
