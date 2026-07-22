from importlib import import_module
from importlib.util import find_spec
from types import ModuleType
from uuid import uuid4

import pytest
from app.core.security import (
    CredentialDecryptionError,
    decrypt_secret,
    encrypt_secret,
)


def load_model_domain() -> ModuleType:
    try:
        spec = find_spec("app.modules.models.domain")
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, "app.modules.models.domain must define provider credential helpers"
    return import_module("app.modules.models.domain")


def test_provider_credential_aad_binds_ciphertext_to_provider() -> None:
    module = load_model_domain()
    first_provider_id = uuid4()
    second_provider_id = uuid4()
    key = b"k" * 32
    plaintext = b"provider-credential-value"

    encrypted = encrypt_secret(
        plaintext,
        key,
        associated_data=module.provider_credential_aad(first_provider_id),
        key_version="v1",
    )

    assert plaintext not in encrypted.ciphertext
    assert (
        decrypt_secret(
            encrypted,
            key,
            associated_data=module.provider_credential_aad(first_provider_id),
        )
        == plaintext
    )
    with pytest.raises(CredentialDecryptionError, match="credential decryption failed"):
        decrypt_secret(
            encrypted,
            key,
            associated_data=module.provider_credential_aad(second_provider_id),
        )


def test_provider_credential_mask_only_exposes_prefix_and_last_four() -> None:
    module = load_model_domain()

    masked = module.mask_credential("credential-value-1234")

    assert masked == "cred...1234"
    assert "value" not in masked
