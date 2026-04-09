from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.orchestrator import Orchestrator
from app.text_attachment_route_resolver import TextAttachmentRouteResolver
from profile_analysis.services.profile_attachment_ingest_service import (
    ProfileAttachmentIngestService,
)
from project_analysis.services.project_ask_service import ProjectAskService
from project_analysis.services.project_ingest_service import ProjectIngestService


TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown",
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".yaml", ".yml", ".toml",
    ".ini", ".sql", ".html", ".css",
}


class RequestOrchestrator:
    def __init__(
        self,
        *,
        upload_dir: Path,
        extract_dir: Path,
        orchestrator: Orchestrator | None = None,
        text_attachment_route_resolver: TextAttachmentRouteResolver | None = None,
    ) -> None:
        self.upload_dir = upload_dir
        self.extract_dir = extract_dir

        self.orchestrator = orchestrator or Orchestrator()
        self.text_attachment_route_resolver = (
            text_attachment_route_resolver or TextAttachmentRouteResolver()
        )

        self.project_ingest_service = ProjectIngestService()
        self.project_ask_service = ProjectAskService()
        self.profile_attachment_ingest_service = ProfileAttachmentIngestService()

    def _read_text_upload(self, file: UploadFile) -> str:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in TEXT_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail="현재 UI에서는 텍스트 파일만 바로 첨부할 수 있습니다. ZIP은 artifact/project 업로드용으로 사용하세요.",
            )

        raw = file.file.read()
        for encoding in ("utf-8", "utf-8-sig", "cp949"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue

        raise HTTPException(status_code=400, detail="첨부 파일 인코딩을 읽지 못했습니다.")

    def _merge_message_with_text(
        self,
        message: str,
        filename: str,
        content: str,
    ) -> tuple[str, dict]:
        content = (content or "").strip()
        if not content:
            raise HTTPException(status_code=400, detail="첨부 파일 내용이 비어 있습니다.")

        max_chars = 2800
        truncated = False
        if len(content) > max_chars:
            content = content[:max_chars].rstrip() + "\n..."
            truncated = True

        merged = (
            f"{message}\n\n"
            f"[첨부 파일]\n"
            f"파일명: {filename}\n"
            f"아래 내용은 사용자가 첨부한 파일의 발췌 본문이다. 필요한 범위에서만 참고하라.\n\n"
            f"{content}"
        )

        return merged, {
            "filename": filename,
            "truncated": truncated,
            "merged_chars": len(merged),
        }

    def handle_chat_request(
        self,
        *,
        message: str,
        project_id: str | None,
        model: str | None,
        effective_model: str,
        file: UploadFile | None,
    ) -> dict:
        filename = (file.filename or "") if file is not None else ""
        lower_name = filename.lower()
        is_zip_upload = bool(file is not None and lower_name.endswith(".zip"))

        if not message and file is None:
            raise HTTPException(status_code=400, detail="message와 file이 모두 비어 있습니다.")

        if not message and file is not None and not is_zip_upload:
            raise HTTPException(
                status_code=400,
                detail="텍스트 파일을 참고 자료로 붙일 때는 함께 보낼 message가 필요합니다.",
            )

        if file is not None:
            if is_zip_upload:
                saved_name = f"{uuid.uuid4()}_{filename}"
                saved_path = self.upload_dir / saved_name

                with saved_path.open("wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)

                project = self.project_ingest_service.ingest(
                    zip_path=saved_path,
                    project_name=filename,
                    extract_root=self.extract_dir,
                    model=model,
                )

                effective_project_id = project["id"]

                return {
                    "reply": f"artifact 업로드가 완료되었습니다: {filename}",
                    "mode": "artifact",
                    "project_id": effective_project_id,
                    "used_model": effective_model,
                    "used_chunks": [],
                    "used_profile_evidence": [],
                    "stored_file_count": project.get("stored_file_count", 0),
                    "stored_chunk_count": project.get("stored_chunk_count", 0),
                    "skipped_file_count": project.get("skipped_file_count", 0),
                    "profile_evidence_extract": project.get("profile_evidence_extract", {}),
                    "profile_memory_sync": project.get("profile_memory_sync", {}),
                }

            text_content = self._read_text_upload(file)

            if project_id:
                merged_message, file_meta = self._merge_message_with_text(
                    message,
                    filename,
                    text_content,
                )

                result = self.project_ask_service.ask(
                    project_id=project_id,
                    question=merged_message,
                    model=model,
                )

                return {
                    "reply": result["answer"],
                    "mode": "artifact",
                    "project_id": project_id,
                    "used_model": effective_model,
                    "used_chunks": result.get("used_chunks", []),
                    "used_profile_evidence": result.get("used_profile_evidence", []),
                    "profile_evidence_extract": result.get("profile_evidence_extract"),
                    "profile_memory_sync": result.get("profile_memory_sync"),
                    "attached_file": file_meta,
                }

            attachment_route = self.text_attachment_route_resolver.resolve(
                user_request=message,
                filename=filename,
                content=text_content,
                model=model,
            )

            if attachment_route == "profile_update":
                result = self.profile_attachment_ingest_service.ingest_text(
                    filename=filename,
                    content=text_content,
                    user_request=message,
                    model=model,
                )

                return {
                    "reply": result["answer"],
                    "mode": "profile_update",
                    "project_id": None,
                    "used_model": effective_model,
                    "used_chunks": [],
                    "used_profile_evidence": result.get("used_profile_evidence", []),
                    "profile_evidence_extract": result.get("profile_evidence_extract"),
                    "profile_memory_sync": result.get("profile_memory_sync"),
                    "attached_file": {
                        "filename": filename,
                        "truncated": False,
                        "merged_chars": None,
                    },
                }

            merged_message, file_meta = self._merge_message_with_text(
                message,
                filename,
                text_content,
            )
            result = self.orchestrator.handle_chat(merged_message, model=model)

            return {
                "reply": result["reply"],
                "context_used": result.get("context_used", {}),
                "update_plan": result.get("update_plan", {}),
                "mode": "general",
                "project_id": None,
                "used_model": effective_model,
                "used_chunks": [],
                "used_profile_evidence": [],
                "profile_evidence_extract": None,
                "profile_memory_sync": None,
                "attached_file": file_meta,
            }

        if project_id:
            result = self.project_ask_service.ask(
                project_id=project_id,
                question=message,
                model=model,
            )

            return {
                "reply": result["answer"],
                "mode": "artifact",
                "project_id": project_id,
                "used_model": effective_model,
                "used_chunks": result.get("used_chunks", []),
                "used_profile_evidence": result.get("used_profile_evidence", []),
                "profile_evidence_extract": result.get("profile_evidence_extract"),
                "profile_memory_sync": result.get("profile_memory_sync"),
            }

        result = self.orchestrator.handle_chat(message, model=model)

        return {
            "reply": result["reply"],
            "context_used": result.get("context_used", {}),
            "update_plan": result.get("update_plan", {}),
            "mode": "general",
            "project_id": None,
            "used_model": effective_model,
            "used_chunks": [],
            "used_profile_evidence": [],
            "profile_evidence_extract": None,
            "profile_memory_sync": None,
            "attached_file": None,
        }