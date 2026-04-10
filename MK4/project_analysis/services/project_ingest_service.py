from pathlib import Path

from memory.services.memory_ingress_service import MemoryIngressService
from project_analysis.injest.chunker import chunk_text_by_lines
from project_analysis.injest.file_filter import is_allowed_file
from project_analysis.injest.zip_loader import extract_zip
from project_analysis.services.project_profile_evidence_service import ProjectProfileEvidenceService
from project_analysis.stores.project_chunk_store import ProjectChunkStore
from project_analysis.stores.project_file_store import ProjectFileStore
from project_analysis.stores.project_store import ProjectStore


class ProjectIngestService:
    def __init__(self) -> None:
        self.project_store = ProjectStore()
        self.project_file_store = ProjectFileStore()
        self.project_chunk_store = ProjectChunkStore()
        self.profile_evidence_service = ProjectProfileEvidenceService()
        self.memory_ingress_service = MemoryIngressService()
    def ingest(
        self,
        zip_path: Path,
        project_name: str,
        extract_root: Path,
        model: str | None = None,
    ) -> dict:
        project = self.project_store.create(
            name=project_name,
            zip_path=str(zip_path),
            status="uploaded",
        )

        project_id = project["id"]
        target_dir = extract_root / project_id
        stored_file_count = 0
        stored_chunk_count = 0
        skipped_file_count = 0

        self.project_store.update_status(project_id, "extracting")
        extract_zip(zip_path, target_dir)

        self.project_store.update_status(project_id, "indexing")

        for file_path in target_dir.rglob("*"):
            if not file_path.is_file():
                continue

            rel_path = file_path.relative_to(target_dir)

            if not is_allowed_file(rel_path):
                skipped_file_count += 1
                continue

            content = None
            for encoding in ("utf-8", "utf-8-sig", "cp949"):
                try:
                    content = file_path.read_text(encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue

            if content is None:
                skipped_file_count += 1
                continue

            stored_file = self.project_file_store.add(
                project_id=project_id,
                path=str(rel_path).replace("\\", "/"),
                ext=file_path.suffix.lower(),
                size_bytes=file_path.stat().st_size,
                content=content,
            )
            stored_file_count += 1

            chunks = chunk_text_by_lines(content)
            stored_chunk_count += len(chunks)

            for chunk in chunks:
                self.project_chunk_store.add(
                    project_id=project_id,
                    file_id=stored_file["id"],
                    chunk_index=chunk["chunk_index"],
                    start_line=chunk["start_line"],
                    end_line=chunk["end_line"],
                    content=chunk["content"],
                    summary=None,
                )

        self.project_store.update_status(project_id, "extracting_profile_evidence")

        try:
            extract_result = self.profile_evidence_service.extract_and_store(project_id, model=model)
            sync_result = self.memory_ingress_service.sync_project(project_id)
        finally:
            self.project_store.update_status(project_id, "indexed")

        project = self.project_store.get(project_id)
        return {
            **project,
            "stored_file_count": stored_file_count,
            "stored_chunk_count": stored_chunk_count,
            "skipped_file_count": skipped_file_count,
            "profile_evidence_extract": extract_result,
            "profile_memory_sync": sync_result,
        }