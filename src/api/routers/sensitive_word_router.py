"""敏感词检测路由."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.sensitive_word_schema import (
    SensitiveScanResult,
    SensitiveScanUiRequest,
    SensitiveWordAddRequest,
    SensitiveWordDto,
    SensitiveWordListResponse,
    SensitiveWordScanRequest,
    SensitiveWordUiAddRequest,
    SensitiveWordUiDeleteRequest,
    SensitiveWordUiSaveRequest,
    SensitiveWordUpdateRequest,
)
from src.db.session import get_session
from src.services.sensitive_word_service import SensitiveWordService

router = APIRouter()


@router.get("", response_model=SensitiveWordListResponse)
@router.get("/", response_model=SensitiveWordListResponse)
async def list_sensitive_words(
    project_id: str | None = None, session: AsyncSession = Depends(get_session)
):
    service = SensitiveWordService(session)
    return await service.list_words(project_id)


@router.post("", response_model=SensitiveWordDto)
@router.post("/", response_model=SensitiveWordDto)
async def add_sensitive_word(
    req: SensitiveWordAddRequest, session: AsyncSession = Depends(get_session)
):
    service = SensitiveWordService(session)
    try:
        return await service.add_word(req)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加敏感词失败: {e}")


# --------------------------------------------------------------------------- #
# UI 兼容端点（/api/sensitive/words 系列 + /scan/{project_id}）
#
# 前端 sensitive_word_page 自「打开项目」起就会调用这些路径，且响应字段名
# （replace_suggestion / hit_id / chapter_ref）与内部 DTO（suggestion /
# chapter_no）不同。历史上服务端从未实现这些路径：
#   - GET/POST/PUT/DELETE /api/sensitive/words 会撞上 /{word_id} 的
#     PUT/DELETE 路由 → 405（打开项目即弹「API 405: Method Not Allowed」）
#   - POST /api/sensitive/scan/{pid} 路径不存在 → 404
# 本组端点按前端调用契约补齐。注意：必须注册在 /{word_id} 路由之前，
# 否则 "words" 会被当作 word_id 吞掉。
# --------------------------------------------------------------------------- #


@router.get("/words")
async def list_sensitive_words_ui(
    project_id: str | None = None, session: AsyncSession = Depends(get_session)
):
    """词库列表（前端期望裸数组，字段名 replace_suggestion）."""
    service = SensitiveWordService(session)
    resp = await service.list_words(project_id)
    return [
        {
            "word_id": w.word_id,
            "word": w.word,
            "category": w.category,
            "replace_suggestion": w.suggestion,
            "is_builtin": w.is_builtin,
        }
        for w in resp.words
    ]


@router.post("/words", response_model=SensitiveWordDto)
async def add_sensitive_word_ui(
    req: SensitiveWordUiAddRequest, session: AsyncSession = Depends(get_session)
):
    """添加单个敏感词（前端按钮触发的即时新增）."""
    service = SensitiveWordService(session)
    try:
        return await service.add_word(
            SensitiveWordAddRequest(
                project_id=req.project_id,
                word=req.word,
                category=req.category,
                suggestion=req.replace_suggestion,
            )
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"添加敏感词失败: {e}")


@router.put("/words")
async def save_sensitive_words_ui(
    req: SensitiveWordUiSaveRequest, session: AsyncSession = Depends(get_session)
):
    """批量保存词库（前端「保存」按钮）：无 word_id 新增、有则更新."""
    service = SensitiveWordService(session)
    try:
        created, updated = await service.save_words(
            [w.model_dump() for w in req.words]
        )
        return {"created": created, "updated": updated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存敏感词库失败: {e}")


@router.delete("/words")
async def delete_sensitive_words_ui(
    req: SensitiveWordUiDeleteRequest, session: AsyncSession = Depends(get_session)
):
    """批量删除词条（前端「删除选中」按钮）."""
    service = SensitiveWordService(session)
    try:
        deleted = await service.delete_words(req.word_ids)
        return {"deleted_count": deleted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除敏感词失败: {e}")


@router.post("/scan/{project_id}")
async def scan_sensitive_words_ui(
    project_id: str,
    req: SensitiveScanUiRequest,
    session: AsyncSession = Depends(get_session),
):
    """全书敏感词扫描（前端「全书扫描」按钮，路径携带 project_id）.

    命中结果按前端 sensitive_word_page 的字段契约返回：
    hit_id / chapter_ref / paragraph_pos / word / category / replace_suggestion /
    chapter_id（双击跳转章节用）。当前扫描为整章计数，无段落级定位，
    paragraph_pos 固定为 0。
    """
    service = SensitiveWordService(session)
    try:
        result = await service.scan(project_id)
        hits = [
            {
                "hit_id": f"{h.chapter_id}:{h.word}",
                "word": h.word,
                "category": h.category,
                "replace_suggestion": h.suggestion,
                "chapter_id": h.chapter_id,
                "chapter_ref": f"第{h.chapter_no}章",
                "paragraph_pos": 0,
                "count": h.count,
            }
            for h in result.hits
        ]
        return {
            "project_id": project_id,
            "total_hits": result.total_hits,
            "hits": hits,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"敏感词扫描失败: {e}")


@router.put("/{word_id}", response_model=SensitiveWordDto)
async def update_sensitive_word(
    word_id: str,
    req: SensitiveWordUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    service = SensitiveWordService(session)
    try:
        return await service.update_word(word_id, req)
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新敏感词失败: {e}")


@router.delete("/{word_id}")
async def delete_sensitive_word(
    word_id: str, session: AsyncSession = Depends(get_session)
):
    service = SensitiveWordService(session)
    try:
        deleted = await service.delete_word(word_id)
        return {"deleted_count": deleted}
    except ValueError as e:
        msg = str(e)
        if "不存在" in msg:
            raise HTTPException(status_code=404, detail=msg)
        raise HTTPException(status_code=400, detail=msg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除敏感词失败: {e}")


@router.post("/scan", response_model=SensitiveScanResult)
async def scan_sensitive_words(
    req: SensitiveWordScanRequest, session: AsyncSession = Depends(get_session)
):
    service = SensitiveWordService(session)
    try:
        return await service.scan(req.project_id, req.chapter_ids)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"敏感词扫描失败: {e}")