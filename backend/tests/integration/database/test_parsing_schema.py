import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

FEATURE_FLAGS = {
    "hasText": False,
    "hasPages": False,
    "hasHeadings": False,
    "hasBoundingBoxes": False,
    "hasAssets": False,
    "hasTables": False,
    "hasFormulas": False,
}


def insert_blob(
    connection: Connection,
    *,
    blob_id: UUID | None = None,
    sha256: str | None = None,
    size_bytes: int = 10,
    reference_count: int = 1,
) -> UUID:
    blob_id = blob_id or uuid4()
    sha256 = sha256 or uuid4().hex * 2
    connection.execute(
        text(
            """
            INSERT INTO source_blobs (
                id, sha256, size_bytes, storage_key, mime_type, reference_count
            ) VALUES (
                :id, :sha256, :size_bytes, :storage_key, 'text/plain', :reference_count
            )
            """
        ),
        {
            "id": blob_id,
            "sha256": sha256,
            "size_bytes": size_bytes,
            "storage_key": f"blobs/{blob_id}",
            "reference_count": reference_count,
        },
    )
    return blob_id


def insert_source(
    connection: Connection,
    *,
    blob_id: UUID,
    source_id: UUID | None = None,
    origin_type: str = "admin_upload",
    revision: int = 1,
) -> UUID:
    source_id = source_id or uuid4()
    connection.execute(
        text(
            """
            INSERT INTO data_sources (
                id, source_blob_id, display_name, source_path, original_file_name,
                extension, mime_type, size_bytes, sha256, origin_type, revision
            ) VALUES (
                :id, :blob_id, 'example.txt', 'example.txt', 'example.txt',
                'txt', 'text/plain', 10, :sha256, :origin_type, :revision
            )
            """
        ),
        {
            "id": source_id,
            "blob_id": blob_id,
            "sha256": "a" * 64,
            "origin_type": origin_type,
            "revision": revision,
        },
    )
    return source_id


def insert_version(
    connection: Connection,
    *,
    source_id: UUID,
    version_id: UUID | None = None,
    version_number: int = 1,
    status: str = "queued",
    quality_level: str | None = None,
    feature_flags: dict[str, object] | None = None,
    block_count: int = 0,
) -> UUID:
    version_id = version_id or uuid4()
    connection.execute(
        text(
            """
            INSERT INTO parsed_source_versions (
                id, data_source_id, version_number, parser_code, parser_version,
                normalizer_version, config_snapshot, config_hash, source_sha256,
                status, quality_level, feature_flags, block_count
            ) VALUES (
                :id, :source_id, :version_number, 'builtin_text', '1', '1',
                '{}'::jsonb, :config_hash, :source_sha256, :status, :quality_level,
                CAST(:feature_flags AS jsonb), :block_count
            )
            """
        ),
        {
            "id": version_id,
            "source_id": source_id,
            "version_number": version_number,
            "config_hash": "b" * 64,
            "source_sha256": "a" * 64,
            "status": status,
            "quality_level": quality_level,
            "feature_flags": json.dumps(feature_flags or FEATURE_FLAGS),
            "block_count": block_count,
        },
    )
    return version_id


def test_source_and_parsing_graph_accepts_valid_rows(database_engine: Engine) -> None:
    with database_engine.begin() as connection:
        blob_id = insert_blob(connection)
        source_id = insert_source(connection, blob_id=blob_id)
        version_id = insert_version(connection, source_id=source_id)
        connection.execute(
            text(
                """
                INSERT INTO parsed_blocks (
                    id, parsed_source_version_id, block_type, order_index,
                    text_content, content_hash
                ) VALUES (:id, :version_id, 'paragraph', 0, 'hello', :content_hash)
                """
            ),
            {"id": uuid4(), "version_id": version_id, "content_hash": "c" * 64},
        )


@pytest.mark.parametrize(
    ("sha256", "size_bytes", "reference_count"),
    [("not-a-hash", 10, 1), ("a" * 64, -1, 1), ("a" * 64, 10, -1)],
)
def test_source_blob_rejects_invalid_hash_or_negative_counts(
    database_engine: Engine,
    sha256: str,
    size_bytes: int,
    reference_count: int,
) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            insert_blob(
                connection,
                sha256=sha256,
                size_bytes=size_bytes,
                reference_count=reference_count,
            )


@pytest.mark.parametrize(
    ("origin_type", "revision"),
    [("unknown", 1), ("admin_upload", 0)],
)
def test_data_source_rejects_unknown_origin_or_nonpositive_revision(
    database_engine: Engine,
    origin_type: str,
    revision: int,
) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            blob_id = insert_blob(connection)
            insert_source(
                connection,
                blob_id=blob_id,
                origin_type=origin_type,
                revision=revision,
            )


@pytest.mark.parametrize(
    ("status", "quality_level", "version_number", "block_count"),
    [
        ("unknown", None, 1, 0),
        ("queued", "partial", 1, 0),
        ("queued", None, 0, 0),
        ("queued", None, 1, -1),
    ],
)
def test_parse_version_rejects_invalid_state_or_counts(
    database_engine: Engine,
    status: str,
    quality_level: str | None,
    version_number: int,
    block_count: int,
) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            source_id = insert_source(connection, blob_id=insert_blob(connection))
            insert_version(
                connection,
                source_id=source_id,
                status=status,
                quality_level=quality_level,
                version_number=version_number,
                block_count=block_count,
            )


@pytest.mark.parametrize(
    "feature_flags",
    [
        {**FEATURE_FLAGS, "futureFlag": False},
        {**FEATURE_FLAGS, "hasText": "yes"},
        {key: value for key, value in FEATURE_FLAGS.items() if key != "hasPages"},
    ],
)
def test_parse_version_requires_exact_boolean_feature_flags(
    database_engine: Engine,
    feature_flags: dict[str, object],
) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            source_id = insert_source(connection, blob_id=insert_blob(connection))
            insert_version(connection, source_id=source_id, feature_flags=feature_flags)


def test_parse_version_number_is_unique_per_source(database_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            source_id = insert_source(connection, blob_id=insert_blob(connection))
            insert_version(connection, source_id=source_id, version_number=1)
            insert_version(connection, source_id=source_id, version_number=1)


def test_parse_progress_rejects_incomplete_or_out_of_range_values(
    database_engine: Engine,
) -> None:
    for current, total in ((1, None), (None, 1), (-1, 1), (2, 1)):
        with pytest.raises(IntegrityError):
            with database_engine.begin() as connection:
                source_id = insert_source(connection, blob_id=insert_blob(connection))
                version_id = insert_version(connection, source_id=source_id)
                connection.execute(
                    text(
                        """
                        UPDATE parsed_source_versions
                        SET progress_current = :current, progress_total = :total
                        WHERE id = :version_id
                        """
                    ),
                    {"current": current, "total": total, "version_id": version_id},
                )


def test_parsed_children_reject_negative_order_and_size(database_engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            source_id = insert_source(connection, blob_id=insert_blob(connection))
            version_id = insert_version(connection, source_id=source_id)
            connection.execute(
                text(
                    """
                    INSERT INTO parsed_blocks (
                        id, parsed_source_version_id, block_type, order_index, content_hash
                    ) VALUES (:id, :version_id, 'paragraph', -1, :content_hash)
                    """
                ),
                {"id": uuid4(), "version_id": version_id, "content_hash": "c" * 64},
            )

    with pytest.raises(IntegrityError):
        with database_engine.begin() as connection:
            source_id = insert_source(connection, blob_id=insert_blob(connection))
            version_id = insert_version(connection, source_id=source_id)
            connection.execute(
                text(
                    """
                    INSERT INTO parsed_assets (
                        id, parsed_source_version_id, asset_type, mime_type,
                        storage_key, sha256, size_bytes, order_index
                    ) VALUES (
                        :id, :version_id, 'image', 'image/png', 'assets/example',
                        :sha256, -1, 0
                    )
                    """
                ),
                {"id": uuid4(), "version_id": version_id, "sha256": "d" * 64},
            )
