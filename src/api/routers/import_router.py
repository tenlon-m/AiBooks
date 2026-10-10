"""文件导入路由."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.schemas.import_schema import ImportParseRequest, ImportParseResponse
from src.services.import_service import ImportService

router = APIRouter()


@router.post("/parse", response_model=ImportParseResponse)
async def parse_file(req: ImportParseRequest):
    service = ImportService()
    try:
        return service.parse(req.file_path, req.category)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        msg = str(e)
        if "过大" in msg:
            raise HTTPException(status_code=413, detail=msg)
        if "不支持" in msg:
            raise HTTPException(status_code=415, detail=msg)
        raise HTTPException(status_code=422, detail=msg)