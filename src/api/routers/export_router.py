"""小说导出路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.export_schema import (
    ExportRequest,
    ExportResponse,
    MultiFormatExportRequest,
)
from src.db.session import get_session
from src.services.export_service import ExportService

router = APIRouter()


@router.post("", response_model=ExportResponse)
@router.post("/txt", response_model=ExportResponse)
async def export_txt(req: ExportRequest, session: AsyncSession = Depends(get_session)):
    """导出为 TXT."""
    service = ExportService(session)
    try:
        return await service.export_to_txt(req.project_id, req.target_dir)
    except ValueError as e:
        msg = str(e)
        if "未完成" in msg:
            raise HTTPException(status_code=412, detail=msg)
        if "穿越" in msg or "过深" in msg:
            raise HTTPException(status_code=400, detail=msg)
        raise HTTPException(status_code=404, detail=msg)
    except PermissionError:
        raise HTTPException(status_code=403, detail="目标路径不可写")
    except TimeoutError:
        raise HTTPException(status_code=504, detail="导出超时")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")


@router.post("/docx", response_model=ExportResponse)
async def export_docx(req: MultiFormatExportRequest, session: AsyncSession = Depends(get_session)):
    """导出为 DOCX."""
    return await _do_export("docx", req, session)


@router.post("/epub", response_model=ExportResponse)
async def export_epub(req: MultiFormatExportRequest, session: AsyncSession = Depends(get_session)):
    """导出为 EPUB."""
    return await _do_export("epub", req, session)


@router.post("/markdown", response_model=ExportResponse)
async def export_markdown(req: MultiFormatExportRequest, session: AsyncSession = Depends(get_session)):
    """导出为 Markdown."""
    return await _do_export("markdown", req, session)


@router.post("/pdf", response_model=ExportResponse)
async def export_pdf(req: MultiFormatExportRequest, session: AsyncSession = Depends(get_session)):
    """导出为 PDF."""
    return await _do_export("pdf", req, session)


async def _do_export(fmt: str, req: MultiFormatExportRequest, session: AsyncSession):
    service = ExportService(session)
    method_map = {
        "docx": service.export_to_docx,
        "epub": service.export_to_epub,
        "markdown": service.export_to_markdown,
        "pdf": service.export_to_pdf,
    }
    try:
        return await method_map[fmt](
            req.project_id, req.target_dir, req.template_id, req.options
        )
    except ValueError as e:
        msg = str(e)
        if "未完成" in msg:
            raise HTTPException(status_code=412, detail=msg)
        if "穿越" in msg or "过深" in msg:
            raise HTTPException(status_code=400, detail=msg)
        raise HTTPException(status_code=404, detail=msg)
    except PermissionError:
        raise HTTPException(status_code=403, detail="目标路径不可写")
    except TimeoutError:
        raise HTTPException(status_code=504, detail="导出超时")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导出失败: {e}")
