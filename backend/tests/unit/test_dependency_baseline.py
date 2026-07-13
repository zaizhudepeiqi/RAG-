from importlib.metadata import version


def test_direct_runtime_dependencies_are_locked() -> None:
    expected = {
        "fastapi": "0.139.0",
        "sqlalchemy": "2.0.51",
        "alembic": "1.18.5",
        "celery": "5.6.3",
        "redis": "6.4.0",
        "chromadb": "1.5.9",
        "pydantic": "2.13.4",
    }

    assert {name: version(name) for name in expected} == expected
