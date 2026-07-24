import pytest
from app.modules.parsing.domain import ParseEvent, ParseState, transition_parse_state
from app.modules.parsing.tasks import mineru_poll_delay_seconds


def test_mineru_parse_state_path_is_strict() -> None:
    state = ParseState.QUEUED
    for event, expected in (
        (ParseEvent.SUBMIT, ParseState.SUBMITTING),
        (ParseEvent.UPLOAD, ParseState.UPLOADING),
        (ParseEvent.WAIT_PROVIDER, ParseState.PROVIDER_PENDING),
        (ParseEvent.PROVIDER_RUNNING, ParseState.PARSING),
        (ParseEvent.DOWNLOAD, ParseState.DOWNLOADING),
        (ParseEvent.NORMALIZE, ParseState.NORMALIZING),
        (ParseEvent.SUCCEED, ParseState.SUCCEEDED),
    ):
        state = transition_parse_state(state, event)
        assert state is expected


def test_builtin_can_skip_directly_to_normalizing() -> None:
    assert transition_parse_state(ParseState.QUEUED, ParseEvent.NORMALIZE) is ParseState.NORMALIZING


def test_only_queued_can_cancel_and_terminal_duplicate_is_noop() -> None:
    assert transition_parse_state(ParseState.QUEUED, ParseEvent.CANCEL) is ParseState.CANCELLED
    assert (
        transition_parse_state(ParseState.SUCCEEDED, ParseEvent.DUPLICATE) is ParseState.SUCCEEDED
    )
    with pytest.raises(ValueError, match="invalid parse state transition"):
        transition_parse_state(ParseState.PARSING, ParseEvent.CANCEL)


def test_invalid_stage_skip_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid parse state transition"):
        transition_parse_state(ParseState.QUEUED, ParseEvent.SUCCEED)


def test_provider_converting_maps_to_parsing_without_a_new_domain_state() -> None:
    assert (
        transition_parse_state(ParseState.PROVIDER_PENDING, ParseEvent.PROVIDER_CONVERTING)
        is ParseState.PARSING
    )
    assert (
        transition_parse_state(ParseState.PARSING, ParseEvent.PROVIDER_CONVERTING)
        is ParseState.PARSING
    )


def test_failed_provider_query_can_resume_without_returning_to_submission() -> None:
    assert (
        transition_parse_state(ParseState.FAILED, ParseEvent.RESUME_PROVIDER_QUERY)
        is ParseState.PROVIDER_PENDING
    )


@pytest.mark.parametrize(
    ("elapsed_seconds", "expected_delay"),
    [(0.0, 3), (59.9, 3), (60.0, 10), (599.9, 10), (600.0, 30)],
)
def test_mineru_poll_delay_uses_the_configured_schedule(
    elapsed_seconds: float,
    expected_delay: int,
) -> None:
    assert mineru_poll_delay_seconds(elapsed_seconds) == expected_delay
