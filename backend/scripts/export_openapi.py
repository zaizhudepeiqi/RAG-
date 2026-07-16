import json
import sys
from pathlib import Path

from pydantic import SecretStr

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.bootstrap.application import create_app  # noqa: E402
from app.core.config import Settings  # noqa: E402


def main() -> None:
    settings = Settings(
        app_env="test",
        app_version="0.1.0",
        database_url="postgresql+psycopg://openapi:openapi@127.0.0.1:5432/openapi",
        redis_url="redis://127.0.0.1:6379/15",
        storage_root=Path("storage/openapi-export").resolve(),
        jwt_signing_key=SecretStr("openapi-export-only-jwt-key-0001"),
        credential_encryption_key=SecretStr("b3BlbmFwaS1leHBvcnQtY3JlZGVudGlhbC1rZXktMDE="),
        initial_admin_password=SecretStr("OpenAPI-Export-Only-Password-03!"),
    )
    schema = create_app(settings).openapi()
    output = REPOSITORY_ROOT / "docs/api/openapi.json"
    output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
