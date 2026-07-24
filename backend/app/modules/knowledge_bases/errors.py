from collections.abc import Mapping, Sequence


class KnowledgeBaseError(Exception):
    code: str

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class KnowledgeBaseConfigError(KnowledgeBaseError):
    field_errors: dict[str, list[str]]

    def __init__(
        self,
        code: str,
        field_errors: Mapping[str, Sequence[str]],
    ) -> None:
        super().__init__(code)
        self.field_errors = {key: list(messages) for key, messages in field_errors.items()}


class InvalidKnowledgeBaseTransitionError(KnowledgeBaseError):
    def __init__(self) -> None:
        super().__init__("INVALID_STATE_TRANSITION")
