from pathlib import Path
import shutil
import uuid

from fastapi import APIRouter, UploadFile, File, HTTPException

from project_analysis.api.schemas import ReviewFileRequest, AskProjectRequest
from project_analysis.services.project_ingest_service import ProjectIngestService
from project_analysis.services.project_review_service import ProjectReviewService
from project_analysis.stores.project_file_store import ProjectFileStore
from project_analysis.services.project_ask_service import ProjectAskService

router = APIRouter(prefix="/projects", tags=["projects"])

UPLOAD_DIR = Path("data/uploads")
EXTRACT_DIR = Path("data/extracted")

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
EXTRACT_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/upload")
async def upload_project_zip(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="ZIP 파일만 업로드 가능합니다.")

    saved_name = f"{uuid.uuid4()}_{file.filename}"
    saved_path = UPLOAD_DIR / saved_name

    with saved_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    service = ProjectIngestService()
    project = service.ingest(
        zip_path=saved_path,
        project_name=file.filename,
        extract_root=EXTRACT_DIR,
    )

    return {
        "project_id": project["id"],
        "name": project["name"],
        "status": project["status"],
    }


@router.get("/{project_id}/files")
def list_project_files(project_id: str):
    store = ProjectFileStore()
    files = store.list_by_project(project_id)
    return {"project_id": project_id, "files": files}


@router.post("/{project_id}/review-file")
def review_project_file(project_id: str, body: ReviewFileRequest):
    service = ProjectReviewService()

    try:
        result = service.review_file(
            project_id=project_id,
            path=body.path,
            question=body.question,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return result

@router.post("/{project_id}/ask")
def ask_project(project_id: str, body: AskProjectRequest):
    service = ProjectAskService()
    result = service.ask(
        project_id=project_id,
        question=body.question,
    )
    return result