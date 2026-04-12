from memory.services.memory_apply_service import MemoryApplyService


class ProfileMemorySyncService:
    """Backward-compatible wrapper around the unified memory apply engine."""

    def __init__(self) -> None:
        self.memory_apply_service = MemoryApplyService()

    def sync_project(self, project_id: str) -> dict:
        return self.memory_apply_service.sync_project(project_id)

    def sync_uploaded_source(self, source_id: str) -> dict:
        return self.memory_apply_service.sync_uploaded_source(source_id)
