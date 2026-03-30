"""Manual data import API routes."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from src.db import postgres as pg
from src.services.manual_import import ManualImportService

from .errors import AppError
from .schemas import APIResponse

router = APIRouter(prefix="/api/manual-import", tags=["manual_import"])

ImportType = Literal["products", "orders", "inventory"]


class ManualImportPreviewResponse(BaseModel):
    import_type: str
    filename: str
    detected_sheets: list[str]
    total_rows: int
    normalized_preview: dict
    quality_report: dict


class ManualImportResultResponse(ManualImportPreviewResponse):
    run_id: str
    imported_rows: int
    skipped_rows: int
    import_summary: dict


async def _get_service() -> ManualImportService:
    pool = pg.get_pool()
    if pool is None:
        raise AppError("数据库未初始化，无法导入数据", status_code=503)
    return ManualImportService(pool)


@router.post("/preview", response_model=APIResponse[ManualImportPreviewResponse])
async def preview_manual_import(
    file: UploadFile = File(...),
    import_type: ImportType | None = Form(default=None),
) -> APIResponse[ManualImportPreviewResponse]:
    service = await _get_service()
    content = await file.read()
    if not content:
        raise AppError("上传文件为空", status_code=400)
    try:
        preview = service.preview(file.filename or "upload.xlsx", content, import_type)
    except ValueError as exc:
        raise AppError(str(exc), status_code=400) from exc
    return APIResponse(data=ManualImportPreviewResponse(**preview.__dict__))


@router.post("/commit", response_model=APIResponse[ManualImportResultResponse])
async def commit_manual_import(
    file: UploadFile = File(...),
    import_type: ImportType | None = Form(default=None),
) -> APIResponse[ManualImportResultResponse]:
    service = await _get_service()
    content = await file.read()
    if not content:
        raise AppError("上传文件为空", status_code=400)
    try:
        result = await service.import_file(file.filename or "upload.xlsx", content, import_type)
    except ValueError as exc:
        raise AppError(str(exc), status_code=400) from exc
    return APIResponse(data=ManualImportResultResponse(**result.__dict__))


@router.get("/runs", response_model=APIResponse[list[dict]])
async def list_manual_import_runs(limit: int = 20) -> APIResponse[list[dict]]:
    service = await _get_service()
    return APIResponse(data=await service.list_runs(limit=limit))


@router.get("/overview", response_model=APIResponse[dict])
async def manual_import_overview() -> APIResponse[dict]:
    service = await _get_service()
    return APIResponse(data=await service.get_overview())


@router.get("/review", response_model=APIResponse[dict])
async def manual_import_review(limit: int = 20) -> APIResponse[dict]:
    service = await _get_service()
    return APIResponse(data=await service.get_review(limit=limit))


@router.get("/comparison", response_model=APIResponse[dict])
async def manual_import_comparison(import_type: ImportType | None = None) -> APIResponse[dict]:
    service = await _get_service()
    return APIResponse(data=await service.get_run_comparison(import_type=import_type))
