from memory.services.memory_apply_service import MemoryApplyService


class ConflictPolicy:
    """Backward-compatible wrapper around the unified memory apply engine."""

    def __init__(self) -> None:
        self.memory_apply_service = MemoryApplyService()

    def apply(self, extracted: dict) -> dict:
        return self.memory_apply_service.apply_extracted(extracted)
