from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.modules.knowledge_bases.domain import (
    GenerationEvent,
    GenerationStatus,
    IndexGeneration,
    ItemEvent,
    ItemStatus,
    derive_allowed_actions,
    derive_display_status,
    transition_generation,
    transition_generation_item,
)
from app.modules.knowledge_bases.errors import InvalidKnowledgeBaseTransitionError


def generation(status: GenerationStatus) -> IndexGeneration:
    return IndexGeneration(
        id=uuid4(),
        knowledge_base_id=uuid4(),
        generation_number=1,
        status=status,
        completeness=None,
        is_frozen=False,
        activated_at=None,
    )


def test_first_partial_build_activates_but_partial_rebuild_is_held() -> None:
    validating = generation(GenerationStatus.VALIDATING)
    activated_at = datetime.now(UTC)

    first = transition_generation(
        validating,
        GenerationEvent.VALIDATION_PARTIAL,
        has_active_generation=False,
        activated_at=activated_at,
    )
    rebuild = transition_generation(
        validating,
        GenerationEvent.VALIDATION_PARTIAL,
        has_active_generation=True,
    )

    assert first.status is GenerationStatus.PARTIAL_READY
    assert first.completeness == "partial"
    assert first.activated_at == activated_at
    assert rebuild.status is GenerationStatus.PARTIAL_FAILED
    assert rebuild.completeness is None


def test_full_success_freezes_generation_only_during_activation() -> None:
    now = datetime.now(UTC)
    succeeded = transition_generation(
        generation(GenerationStatus.VALIDATING),
        GenerationEvent.VALIDATION_FULL_SUCCESS,
        has_active_generation=False,
        activated_at=now,
    )

    assert succeeded.status is GenerationStatus.SUCCEEDED
    assert succeeded.completeness == "full"
    assert succeeded.is_frozen is True
    assert succeeded.activated_at == now


@pytest.mark.parametrize(
    "event",
    [GenerationEvent.VALIDATION_FULL_SUCCESS, GenerationEvent.VALIDATION_PARTIAL],
)
def test_activatable_result_requires_activation_timestamp(event: GenerationEvent) -> None:
    with pytest.raises(InvalidKnowledgeBaseTransitionError):
        transition_generation(
            generation(GenerationStatus.VALIDATING),
            event,
            has_active_generation=False,
        )


def test_partial_failed_can_retry_but_active_partial_cannot_mutate() -> None:
    retried = transition_generation(
        generation(GenerationStatus.PARTIAL_FAILED),
        GenerationEvent.RETRY_FAILED_ITEMS,
        has_active_generation=True,
    )

    assert retried.status is GenerationStatus.BUILDING
    with pytest.raises(InvalidKnowledgeBaseTransitionError):
        transition_generation(
            generation(GenerationStatus.PARTIAL_READY),
            GenerationEvent.RETRY_FAILED_ITEMS,
            has_active_generation=True,
        )


def test_generation_item_pipeline_and_retry_are_strict() -> None:
    status = ItemStatus.QUEUED
    for event, expected in (
        (ItemEvent.START_CHUNKING, ItemStatus.CHUNKING),
        (ItemEvent.START_EMBEDDING, ItemStatus.EMBEDDING),
        (ItemEvent.START_KEYWORD_INDEXING, ItemStatus.KEYWORD_INDEXING),
        (ItemEvent.START_VECTOR_INDEXING, ItemStatus.VECTOR_INDEXING),
        (ItemEvent.START_VALIDATING, ItemStatus.VALIDATING),
        (ItemEvent.SUCCEED, ItemStatus.SUCCEEDED),
    ):
        status = transition_generation_item(status, event, generation_frozen=False)
        assert status is expected

    with pytest.raises(InvalidKnowledgeBaseTransitionError):
        transition_generation_item(ItemStatus.SUCCEEDED, ItemEvent.FAIL, generation_frozen=False)
    with pytest.raises(InvalidKnowledgeBaseTransitionError):
        transition_generation_item(ItemStatus.FAILED, ItemEvent.RETRY, generation_frozen=True)


@pytest.mark.parametrize(
    ("enabled", "active", "latest", "pending", "expected"),
    [
        (False, "full", None, False, "disabled"),
        (True, None, "building", False, "building"),
        (True, None, "failed", False, "unavailable"),
        (True, "full", "building", False, "rebuilding"),
        (True, "partial", None, False, "partial_ready"),
        (True, "full", None, True, "config_changed"),
        (True, "full", None, False, "ready"),
    ],
)
def test_display_status_is_derived_not_stored(
    enabled: bool,
    active: str | None,
    latest: str | None,
    pending: bool,
    expected: str,
) -> None:
    assert derive_display_status(enabled, active, latest, pending) == expected


def test_allowed_actions_are_derived_from_raw_state() -> None:
    assert derive_allowed_actions(
        enabled=True,
        active_completeness="full",
        latest_build_status=None,
        has_pending_build_config=True,
        bot_reference_count=0,
    ) == (
        "edit_metadata",
        "disable",
        "retrieval_test",
        "build",
        "discard_pending_build_config",
        "delete",
    )
    assert "delete" not in derive_allowed_actions(
        enabled=True,
        active_completeness="full",
        latest_build_status="building",
        has_pending_build_config=False,
        bot_reference_count=1,
    )
