from uuid import UUID


class CountingTaskHandler:
    def __init__(self) -> None:
        self.side_effect_count = 0

    def run(self, _operation_id: UUID) -> dict[str, object]:
        self.side_effect_count += 1
        return {"sideEffectCount": self.side_effect_count}
