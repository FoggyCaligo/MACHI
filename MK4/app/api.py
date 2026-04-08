from contextlib import asynccontextmanager
from pathlib import Path
import shutil
import time
import uuid
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.orchestrator import Orchestrator
from config import OLLAMA_DEFAULT_MODEL
from memory.db import initialize_database
from profile_analysis.services.profile_attachment_ingest_service import (
    ProfileAttachmentIngestService,
)
from project_analysis.services.project_ask_service import ProjectAskService
from project_analysis.services.project_ingest_service import ProjectIngestService
from project_analysis.stores.db import init_project_tables
from tools.ollama_client import OllamaClient


UPLOAD_DIR = Path("data/uploads")
EXTRACT_DIR = Path("data/extracted")
STATIC_DIR = Path(__file__).resolve().parent / "static"

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown",
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".yaml", ".yml", ".toml",
    ".ini", ".sql", ".html", ".css",
}

PROFILE_MESSAGE_HINTS = {
    "나에 대해", "나를", "프로필", "성향", "스타일", "선호", "습관",
    "내가 어떤", "어떤 사람", "이해", "파악", "need", "니즈",
    "작동 방식", "블로그", "글 모음", "글들", "회고", "생각",
}
PROFILE_FILE_HINTS = {
    "profile", "blog", "essay", "memo", "notes", "retrospective",
    "회고", "블로그", "프로필", "메모", "생각", "기록",
}
FIRST_PERSON_MARKERS = {
    "나는", "내가", "나의", "저는", "제가", "저의", "i am", "i'm", "my ",
}


def _log(message: str) -> None:
    print(f"[API] {message}", flush=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_database()
    init_project_tables()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    _log("startup complete")
    yield


app = FastAPI(title="MK4 Personalization Agent", lifespan=lifespan)
orchestrator = Orchestrator()

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def root():
    return {"message": "mk4 is running", "ui": "/ui"}


@app.get("/ui")
def ui():
    html_path = STATIC_DIR / "chat.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="UI 파일이 없습니다.")
    return FileResponse(html_path)


@app.get("/models")
def list_models():
    try:
        models = OllamaClient.list_local_models()
        return {
            "default_model": OLLAMA_DEFAULT_MODEL,
            "ollama_available": True,
            "models": models,
            "error": None,
        }
    except Exception as exc:
        _log(f"/models warning | error={exc}")
        return {
            "default_model": OLLAMA_DEFAULT_MODEL,
            "ollama_available": False,
            "models": [],
            "error": str(exc),
        }


def _normalize_optional(value: str | None) -> str | None:
    value = (value or "").strip()
    if value.lower() in {"", "string", "null", "none", "undefined"}:
        return None
    return value


def _resolve_model_name(model: str | None) -> str:
    return (model or OLLAMA_DEFAULT_MODEL).strip()


def _read_text_upload(file: UploadFile) -> str:
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


def _merge_message_with_text(message: str, filename: str, content: str) -> tuple[str, dict]:
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


def _looks_like_profile_request(message: str, filename: str, content: str) -> bool:
    lowered_message = (message or "").lower()
    lowered_filename = (filename or "").lower()
    lowered_content = (content or "")[:4000].lower()

    if any(hint in lowered_message for hint in PROFILE_MESSAGE_HINTS):
        return True

    if any(hint in lowered_filename for hint in PROFILE_FILE_HINTS):
        return True

    first_person_hits = sum(1 for marker in FIRST_PERSON_MARKERS if marker in lowered_content)
    if first_person_hits >= 3:
        return True

    return False


@app.post("/chat")
async def chat(
    message: Annotated[str | None, Form()] = None,
    project_id: Annotated[str | None, Form()] = None,
    model: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
):
    started_at = time.perf_counter()

    message = (message or "").strip()
    project_id = _normalize_optional(project_id)
    model = _normalize_optional(model)
    effective_project_id = project_id
    effective_model = _resolve_model_name(model)

    filename = file.filename if file is not None else ""
    lower_name = filename.lower()
    is_zip_upload = bool(file is not None and lower_name.endswith(".zip"))

    _log(
        f"/chat start | message_len={len(message)} | "
        f"project_id={effective_project_id} | "
        f"model={effective_model} | "
        f"file={filename or '-'} | is_zip={is_zip_upload}"
    )

    if not message and file is None:
        raise HTTPException(status_code=400, detail="message와 file이 모두 비어 있습니다.")

    if not message and file is not None and not is_zip_upload:
        raise HTTPException(
            status_code=400,
            detail="텍스트 파일을 참고 자료로 붙일 때는 함께 보낼 message가 필요합니다.",
        )

    try:
        if file is not None:
            if is_zip_upload:
                _log("zip upload branch entered")

                saved_name = f"{uuid.uuid4()}_{filename}"
                saved_path = UPLOAD_DIR / saved_name

                with saved_path.open("wb") as buffer:
                    shutil.copyfileobj(file.file, buffer)

                _log(f"zip saved | path={saved_path}")

                ingest_service = ProjectIngestService()
                project = ingest_service.ingest(
                    zip_path=saved_path,
                    project_name=filename,
                    extract_root=EXTRACT_DIR,
                    model=model,
                )
                effective_project_id = project["id"]

                elapsed = time.perf_counter() - started_at
                _log(f"zip ingest complete | project_id={effective_project_id} | elapsed={elapsed:.2f}s")

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

            _log("text attachment branch entered")
            text_content = _read_text_upload(file)
            _log(f"text attachment loaded | filename={filename} | chars={len(text_content)}")

            if effective_project_id:
                merged_message, file_meta = _merge_message_with_text(message, filename, text_content)
                _log(
                    f"artifact ask with text attachment | filename={file_meta['filename']} | "
                    f"truncated={file_meta['truncated']} | merged_chars={file_meta['merged_chars']}"
                )

                ask_service = ProjectAskService()
                result = ask_service.ask(
                    project_id=effective_project_id,
                    question=merged_message,
                    model=model,
                )

                elapsed = time.perf_counter() - started_at
                _log(f"artifact ask complete | elapsed={elapsed:.2f}s")

                return {
                    "reply": result["answer"],
                    "mode": "artifact",
                    "project_id": effective_project_id,
                    "used_model": effective_model,
                    "used_chunks": result.get("used_chunks", []),
                    "used_profile_evidence": result.get("used_profile_evidence", []),
                    "profile_evidence_extract": result.get("profile_evidence_extract"),
                    "profile_memory_sync": result.get("profile_memory_sync"),
                    "attached_file": file_meta,
                }

            if _looks_like_profile_request(message=message, filename=filename, content=text_content):
                _log("profile attachment update branch entered")

                profile_ingest_service = ProfileAttachmentIngestService()
                result = profile_ingest_service.ingest_text(
                    filename=filename,
                    content=text_content,
                    user_request=message,
                    model=model,
                )

                elapsed = time.perf_counter() - started_at
                _log(
                    f"profile attachment update complete | elapsed={elapsed:.2f}s | "
                    f"candidate_count={result.get('profile_evidence_extract', {}).get('candidate_count', 0)}"
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

            merged_message, file_meta = _merge_message_with_text(message, filename, text_content)
            _log(
                f"general chat with attached text branch entered | "
                f"filename={file_meta['filename']} | truncated={file_meta['truncated']} | "
                f"merged_chars={file_meta['merged_chars']}"
            )

            result = orchestrator.handle_chat(merged_message, model=model)

            elapsed = time.perf_counter() - started_at
            _log(f"general chat with attached text complete | elapsed={elapsed:.2f}s")

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

        if effective_project_id:
            _log("artifact ask branch entered (no file)")

            ask_service = ProjectAskService()
            result = ask_service.ask(
                project_id=effective_project_id,
                question=message,
                model=model,
            )

            elapsed = time.perf_counter() - started_at
            _log(f"artifact ask complete (no file) | elapsed={elapsed:.2f}s")

            return {
                "reply": result["answer"],
                "mode": "artifact",
                "project_id": effective_project_id,
                "used_model": effective_model,
                "used_chunks": result.get("used_chunks", []),
                "used_profile_evidence": result.get("used_profile_evidence", []),
                "profile_evidence_extract": result.get("profile_evidence_extract"),
                "profile_memory_sync": result.get("profile_memory_sync"),
            }

        _log("general chat branch entered")
        result = orchestrator.handle_chat(message, model=model)

        elapsed = time.perf_counter() - started_at
        _log(f"general chat complete | elapsed={elapsed:.2f}s")

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
        }
    except HTTPException:
        raise
    except Exception as exc:
        elapsed = time.perf_counter() - started_at
        _log(f"/chat error | elapsed={elapsed:.2f}s | error={exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/recall")
def recall(query: str):
    started_at = time.perf_counter()
    try:
        result = orchestrator.handle_recall(query)
        elapsed = time.perf_counter() - started_at
        _log(f"/recall complete | query_len={len(query)} | elapsed={elapsed:.2f}s")
        return result
    except Exception as exc:
        elapsed = time.perf_counter() - started_at
        _log(f"/recall error | elapsed={elapsed:.2f}s | error={exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
