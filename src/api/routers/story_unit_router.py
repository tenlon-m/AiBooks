"""故事单元路由 - 雪花式5级分层大纲."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas.story_unit_schema import (
    GenerateLayerRequest,
    StoryUnitDto,
    StoryUnitTreeDto,
    StoryUnitUpdateRequest,
)
from src.db.session import get_session
from src.services.story_unit_service import StoryUnitService

router = APIRouter()


@router.post("/generate-volume-layer", response_model=list[StoryUnitDto])
async def generate_volume_layer(
    req: GenerateLayerRequest,
    session: AsyncSession = Depends(get_session),
):
    """生成分卷层（最高层）."""
    service = StoryUnitService(session)
    try:
        return await service.generate_volume_layer(req.project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/generate-layer", response_model=list[StoryUnitDto])
async def generate_layer(
    req: GenerateLayerRequest,
    session: AsyncSession = Depends(get_session),
):
    """逐层细化生成."""
    service = StoryUnitService(session)
    try:
        return await service.generate_layer(
            req.project_id, req.parent_unit_id, req.level_type
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/tree/{project_id}", response_model=StoryUnitTreeDto)
async def get_tree(
    project_id: str,
    session: AsyncSession = Depends(get_session),
):
    """获取完整树."""
    service = StoryUnitService(session)
    return await service.list_tree(project_id)


@router.put("/{unit_id}", response_model=StoryUnitDto)
async def update_unit(
    unit_id: str,
    req: StoryUnitUpdateRequest,
    session: AsyncSession = Depends(get_session),
):
    """更新单元（触发级联标记）."""
    service = StoryUnitService(session)
    try:
        return await service.update_unit(unit_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{unit_id}/cascade-mark")
async def cascade_mark(
    unit_id: str,
    session: AsyncSession = Depends(get_session),
):
    """手动级联标记."""
    service = StoryUnitService(session)
    try:
        count = await service.cascade_mark(unit_id)
        return {"marked_count": count}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))