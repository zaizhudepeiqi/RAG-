from uuid import UUID

import pytest
from app.core.ids import parse_or_create_trace_id
from app.core.schemas import ApiModel
from pydantic import ValidationError


class ExampleModel(ApiModel):
    trace_id: str


def test_api_model_serializes_camel_case() -> None:
    assert ExampleModel(trace_id="abc").model_dump() == {"traceId": "abc"}


def test_api_model_accepts_alias_and_rejects_extra_fields() -> None:
    assert ExampleModel(traceId="abc").trace_id == "abc"

    with pytest.raises(ValidationError):
        ExampleModel.model_validate({"traceId": "abc", "unexpected": True})


def test_trace_id_reuses_only_valid_uuid_values() -> None:
    supplied = UUID("2777136d-608c-4c26-8b7a-bc6e15cd9158")

    assert parse_or_create_trace_id(str(supplied)) == supplied
    assert parse_or_create_trace_id("not-a-uuid") != supplied
    assert isinstance(parse_or_create_trace_id(None), UUID)
