"""Canonical evidence-record schema tests (criteria #24, #59)."""

from __future__ import annotations

import pytest

from affirmed_mcp.schema import RecordValidationError, canonical_record, record_digest, validate_typed_tuple


def _base(**kw):
    rec = {"id": "r1", "text": "t", "source": "s", "tags": []}
    rec.update(kw)
    return rec


def test_complete_typed_tuple_validates():
    validate_typed_tuple(_base(field_name="price", field_type="number", field_value=75, field_unit="USD"))
    validate_typed_tuple(_base(field_name="towing", field_type="availability",
                               field_value={"always": True}, availability_schedule={"always": True}))
    validate_typed_tuple(_base(field_name="on", field_type="boolean", field_value=True))
    validate_typed_tuple(_base(field_name="since", field_type="date", field_value="2026-01-15"))
    validate_typed_tuple(_base(field_name="hours", field_type="duration", field_value=8, field_unit="hour"))


def test_incomplete_tuple_rejected():
    with pytest.raises(RecordValidationError):
        validate_typed_tuple(_base(field_name="price"))  # type+value missing
    with pytest.raises(RecordValidationError):
        validate_typed_tuple(_base(field_type="number", field_value=75))  # name missing
    with pytest.raises(RecordValidationError):
        validate_typed_tuple(_base(field_name="price", field_type="number", field_value=75))  # unit missing


def test_invalid_field_type_rejected():
    with pytest.raises(RecordValidationError):
        validate_typed_tuple(_base(field_name="x", field_type="truthiness", field_value=1))


def test_wrong_value_shape_rejected():
    with pytest.raises(RecordValidationError):
        validate_typed_tuple(_base(field_name="x", field_type="number", field_value="seventy-five", field_unit="USD"))
    with pytest.raises(RecordValidationError):
        validate_typed_tuple(_base(field_name="x", field_type="boolean", field_value="yes"))
    with pytest.raises(RecordValidationError):
        validate_typed_tuple(_base(field_name="x", field_type="date", field_value="01/15/2026"))
    with pytest.raises(RecordValidationError):
        validate_typed_tuple(_base(field_name="x", field_type="availability", field_value=True))  # needs schedule


def test_iso_boundaries_enforced():
    with pytest.raises(RecordValidationError):
        validate_typed_tuple(_base(valid_from="yesterday"))
    validate_typed_tuple(_base(valid_from="2026-01-15T00:00:00Z"))


def test_canonical_record_round_trip_and_digest():
    rec = _base(field_name="price", field_type="number", field_value=75, field_unit="USD")
    canon = canonical_record(rec)
    assert canon["field_name"] == "price"
    assert record_digest(canon) == record_digest(rec)
    assert record_digest(canon) != record_digest(_base(field_name="price", field_type="number",
                                                       field_value=76, field_unit="USD"))
