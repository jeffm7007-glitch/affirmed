"""Canonical EvidenceRecord model and typed-field validation (spec §6A).

The ``evidence_records`` table is the self-contained MVP compatibility
contract. Unknown source columns are never interpreted as evidence features.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .canonical import digest

FIELD_TYPES = (
    "string",
    "number",
    "boolean",
    "date",
    "datetime",
    "duration",
    "availability",
    "geography",
    "quantified_text",
)

UNIT_BEARING_TYPES = ("number", "duration")

_BASE_FIELDS = ("id", "text", "source", "tags")
_OPTIONAL_FIELDS = (
    "subject_id",
    "subject_name",
    "field_name",
    "field_value",
    "field_type",
    "field_unit",
    "valid_from",
    "valid_to",
    "geo_scope",
    "availability_schedule",
    "quantifier_scope",
    "exceptions",
    "source_published_at",
    "source_effective_at",
    "source_name",
    "source_authority",
    "source_url_or_reference",
    "source_record_version",
)
ALL_FIELDS = _BASE_FIELDS + _OPTIONAL_FIELDS
REQUIRED_COLUMNS = _BASE_FIELDS

_WEEKDAYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_QUANTIFIERS = {"all", "only", "except", "excluding", "at_least", "up_to"}
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?)?$")


class RecordValidationError(ValueError):
    """A typed evidence tuple is invalid and must be rejected (spec §14 #59)."""


def _parse_json_column(value, column: str, record_id: str):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        raise RecordValidationError(
            f"record {record_id!r}: column {column!r} is not valid JSON"
        )


def _validate_availability(value, record_id: str) -> None:
    if not isinstance(value, dict):
        raise RecordValidationError(f"record {record_id!r}: availability_schedule must be an object")
    allowed = {"always", "days", "start", "end", "timezone", "notes"}
    unknown = set(value) - allowed
    if unknown:
        raise RecordValidationError(
            f"record {record_id!r}: availability_schedule unknown keys {sorted(unknown)}"
        )
    if "always" in value and not isinstance(value["always"], bool):
        raise RecordValidationError(f"record {record_id!r}: availability_schedule.always must be boolean")
    if "days" in value:
        days = value["days"]
        if not isinstance(days, list) or any(d.lower() not in _WEEKDAYS for d in days if isinstance(d, str)) or any(not isinstance(d, str) for d in days):
            raise RecordValidationError(f"record {record_id!r}: availability_schedule.days invalid")


def _validate_geo(value, record_id: str) -> None:
    if not isinstance(value, dict):
        raise RecordValidationError(f"record {record_id!r}: geo_scope must be an object")
    regions = value.get("regions")
    if not isinstance(regions, list) or not regions:
        raise RecordValidationError(f"record {record_id!r}: geo_scope.regions must be a non-empty list")
    allowed = {"country", "state", "city", "county"}
    for region in regions:
        if not isinstance(region, dict) or not region:
            raise RecordValidationError(f"record {record_id!r}: geo_scope region must be a non-empty object")
        unknown = set(region) - allowed
        if unknown:
            raise RecordValidationError(
                f"record {record_id!r}: geo_scope unknown keys {sorted(unknown)}"
            )


def _validate_quantifier(value, record_id: str) -> None:
    if not isinstance(value, dict):
        raise RecordValidationError(f"record {record_id!r}: quantifier_scope must be an object")
    if value.get("quantifier") not in _QUANTIFIERS:
        raise RecordValidationError(f"record {record_id!r}: quantifier_scope.quantifier invalid")


def validate_typed_tuple(record: dict[str, Any]) -> None:
    """Validate the typed-field contract for one canonical record (§6A rules).

    Raises RecordValidationError on any violation (incomplete tuples, invalid
    field types, unsupported structured values, unit-bearing numbers without
    units, unparseable JSON columns).
    """
    record_id = str(record.get("id", "<unknown>"))
    field_name = record.get("field_name")
    field_type = record.get("field_type")
    field_value = record.get("field_value")

    if field_name is None and (field_type is not None or field_value is not None or record.get("field_unit") is not None):
        raise RecordValidationError(f"record {record_id!r}: field_type/value/unit without field_name")

    if field_name is not None:
        if not isinstance(field_name, str) or not field_name:
            raise RecordValidationError(f"record {record_id!r}: field_name must be non-empty string")
        if field_type is None or field_value is None:
            raise RecordValidationError(
                f"record {record_id!r}: field_name present but field_value/field_type missing"
            )
        if field_type not in FIELD_TYPES:
            raise RecordValidationError(f"record {record_id!r}: invalid field_type {field_type!r}")

        if field_type in UNIT_BEARING_TYPES and not record.get("field_unit"):
            raise RecordValidationError(f"record {record_id!r}: unit-bearing field {field_type!r} requires field_unit")

        if field_type == "number" and not isinstance(field_value, (int, float)):
            raise RecordValidationError(f"record {record_id!r}: number field_value must be numeric")
        if field_type == "boolean" and not isinstance(field_value, bool):
            raise RecordValidationError(f"record {record_id!r}: boolean field_value must be true/false")
        if field_type in ("date", "datetime") and not (
            isinstance(field_value, str) and _ISO_DATE_RE.match(field_value)
        ):
            raise RecordValidationError(f"record {record_id!r}: date/datetime field_value must be ISO 8601")
        if field_type == "duration" and not isinstance(field_value, (int, float)):
            raise RecordValidationError(f"record {record_id!r}: duration field_value must be numeric")
        if field_type == "string" and not isinstance(field_value, str):
            raise RecordValidationError(f"record {record_id!r}: string field_value must be a string")
        if field_type == "availability":
            _validate_availability(record.get("availability_schedule"), record_id)
        if field_type == "geography":
            _validate_geo(record.get("geo_scope"), record_id)
        if field_type == "quantified_text":
            _validate_quantifier(record.get("quantifier_scope"), record_id)

    for boundary in ("valid_from", "valid_to", "source_published_at", "source_effective_at"):
        value = record.get(boundary)
        if value is not None and not (isinstance(value, str) and _ISO_DATE_RE.match(value)):
            raise RecordValidationError(f"record {record_id!r}: {boundary} must be ISO 8601 or null")


def row_to_record(row) -> dict[str, Any]:
    """Convert a sqlite Row into a canonical record dict; validate typed tuples."""
    record: dict[str, Any] = {}
    for column in ALL_FIELDS:
        value = row[column] if column in row.keys() else None
        if value is None:
            continue
        record[column] = value

    record_id = str(record.get("id", ""))
    tags = record.get("tags")
    record["tags"] = tags if isinstance(tags, list) else (_parse_json_column(tags, "tags", record_id) or [])

    for column in ("field_value", "geo_scope", "availability_schedule", "quantifier_scope", "exceptions"):
        if column in record:
            record[column] = _parse_json_column(record[column], column, record_id)

    validate_typed_tuple(record)
    return record


def canonical_record(record: dict[str, Any]) -> dict[str, Any]:
    """Allowlisted canonical form (sorted keys handled by canonical JSON)."""
    out = {}
    for column in ALL_FIELDS:
        value = record.get(column)
        if value is None:
            continue
        out[column] = value
    out.setdefault("tags", [])
    return out


def record_digest(record: dict[str, Any]) -> str:
    """Digest of one canonical EvidenceRecord (excludes retrieval score/rank)."""
    return digest(canonical_record(record))
