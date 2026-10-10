"""敏感词 / 章节锁定 UI 兼容端点契约测试.

背景：前端 sensitive_word_page 自「打开项目」起调用 /api/sensitive/words
系列端点，但服务端从未实现这些路径——GET/POST/PUT/DELETE /words 撞上
/{word_id} 的 PUT/DELETE 路由返回 405，导致打开项目即弹出
「API 405: Method Not Allowed」。chapter_edit_page 选中章节时调用
GET /api/chapters/{id}/lock 也因只有 PATCH 而 405（锁定状态永远显示
未锁定）。本文件按前端的实际请求/响应形状锁定这组端点契约。
"""
from __future__ import annotations

import asyncio
from typing import Any, Coroutine

import httpx
import pytest

from src.api.server import create_app
from src.config.app_config import AppConfig
from src.db import session as db_session
from src.db.migrations.init_schema import init_schema
from src.db.models import Chapter, Project, SensitiveWord

PID = "p-ui-contract"
CID = "c-ui-contract"


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


@pytest.fixture()
def client(tmp_path: Any) -> Any:
    """每个测试独立临时库 + ASGI 直连的 httpx 客户端."""

    async def _setup() -> httpx.AsyncClient:
        await db_session.close_engine()
        db_session.init_engine(
            AppConfig(
                data_dir=tmp_path,
                log_dir=tmp_path / "logs",
                db_url=f"sqlite+aiosqlite:///{tmp_path / 'ui_contract.db'}",
            )
        )
        await init_schema()
        # 造一个带两章正文的项目
        from src.db.session import get_session_factory

        async with get_session_factory()() as s:
            s.add(Project(
                project_id=PID,
                book_title="契约测试书",
                volume_count=1,
                chapters_per_volume=2,
                words_per_chapter=100,
            ))
            s.add(Chapter(
                chapter_id=CID,
                project_id=PID,
                volume_no=1,
                chapter_no=1,
                title="第一章",
                content="他握紧了手中的炸弹。",
                word_count=10,
            ))
            s.add(Chapter(
                chapter_id="c-2",
                project_id=PID,
                volume_no=1,
                chapter_no=2,
                title="第二章",
                content="平静的日常。",
                word_count=8,
            ))
            await s.commit()

        app = create_app()
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )

    client = _run(_setup())
    yield client
    _run(client.aclose())
    _run(db_session.close_engine())


# --------------------------------------------------------------------------- #
# 敏感词 UI 端点
# --------------------------------------------------------------------------- #


def test_list_words_returns_bare_array_with_ui_fields(client: httpx.AsyncClient) -> None:
    """GET /api/sensitive/words 必须返回裸数组且字段名为 replace_suggestion.

    前端直接 ``for w in words`` 迭代响应体，返回 {"words": [...]} 会迭代出
    字符串 key 直接崩；字段用 suggestion 前端则永远读到空替换建议。
    """

    async def _case() -> None:
        resp = await client.get("/api/sensitive/words")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert isinstance(data, list), "前端期望裸数组"

    _run(_case())


def test_add_then_list_roundtrip(client: httpx.AsyncClient) -> None:
    """POST /words（replace_suggestion 字段）→ GET /words 能看到新词."""

    async def _case() -> None:
        resp = await client.post(
            "/api/sensitive/words",
            json={"word": "炸弹", "category": "暴力", "replace_suggestion": "装置"},
        )
        assert resp.status_code == 200, resp.text

        resp = await client.get("/api/sensitive/words")
        words = {w["word"]: w for w in resp.json()}
        assert "炸弹" in words
        entry = words["炸弹"]
        assert entry["category"] == "暴力"
        assert entry["replace_suggestion"] == "装置", "UI 字段名必须映射 suggestion"
        assert entry["word_id"], "新增词条必须带回 word_id 供删除/更新"

    _run(_case())


def test_bulk_save_upserts_words(client: httpx.AsyncClient) -> None:
    """PUT /words：无 word_id 新增、有 word_id 更新（前端「保存」按钮）."""

    async def _case() -> None:
        # 先经 POST 建一个词拿到 word_id
        await client.post(
            "/api/sensitive/words", json={"word": "旧词", "category": "涉政"}
        )
        listed = (await client.get("/api/sensitive/words")).json()
        old = next(w for w in listed if w["word"] == "旧词")

        resp = await client.put("/api/sensitive/words", json={"words": [
            {"word_id": old["word_id"], "word": "新词", "category": "暴力",
             "replace_suggestion": "替换"},
            {"word": "全新词条", "category": "涉黄"},
        ]})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["updated"] == 1 and body["created"] == 1

        listed = (await client.get("/api/sensitive/words")).json()
        words = {w["word"] for w in listed}
        assert "新词" in words and "全新词条" in words and "旧词" not in words

    _run(_case())


def test_bulk_delete_words(client: httpx.AsyncClient) -> None:
    """DELETE /words（body 传 word_ids）批量删除（前端「删除选中」按钮）."""

    async def _case() -> None:
        ids = []
        for w in ("词甲", "词乙"):
            r = await client.post(
                "/api/sensitive/words", json={"word": w, "category": "暴力"}
            )
            ids.append(r.json()["word_id"])

        resp = await client.request(
            "DELETE", "/api/sensitive/words", json={"word_ids": ids}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted_count"] == 2

        listed = (await client.get("/api/sensitive/words")).json()
        assert not any(w["word"] in ("词甲", "词乙") for w in listed)

    _run(_case())


def test_scan_by_path_returns_ui_hit_shape(client: httpx.AsyncClient) -> None:
    """POST /scan/{project_id}：命中项字段按前端表格契约返回."""

    async def _case() -> None:
        await client.post(
            "/api/sensitive/words",
            json={"word": "炸弹", "category": "暴力", "replace_suggestion": "装置"},
        )
        resp = await client.post(
            f"/api/sensitive/scan/{PID}", json={"user_ideas": ""}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total_hits"] == 1
        hit = body["hits"][0]
        # 前端表格读取的字段
        assert hit["word"] == "炸弹"
        assert hit["chapter_id"] == CID, "双击跳转章节依赖 chapter_id"
        assert hit["chapter_ref"], "表格「章节」列显示 chapter_ref"
        assert "paragraph_pos" in hit
        assert hit["replace_suggestion"] == "装置"

    _run(_case())


def test_builtin_words_cannot_be_modified_by_bulk_save(client: httpx.AsyncClient) -> None:
    """批量保存跳过内置词条，而不是报错（UI 表格会同时包含内置词行）."""

    async def _case() -> None:
        resp = await client.put("/api/sensitive/words", json={"words": [
            {"word_id": "builtin-fake-id", "word": "篡改", "category": "x"},
            {"word": "正常新增", "category": "y"},
        ]})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"created": 1, "updated": 0}

    _run(_case())


# --------------------------------------------------------------------------- #
# 章节锁定状态查询
# --------------------------------------------------------------------------- #


def test_chapter_lock_get_and_patch_roundtrip(client: httpx.AsyncClient) -> None:
    """GET /api/chapters/{id}/lock 查询 + PATCH 翻转 + 再查询."""

    async def _case() -> None:
        # 初始未锁定
        resp = await client.get(f"/api/chapters/{CID}/lock")
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"chapter_id": CID, "is_locked": False}

        # 锁定
        resp = await client.patch(
            f"/api/chapters/{CID}/lock", json={"is_locked": True}
        )
        assert resp.status_code == 200
        assert resp.json()["is_locked"] is True

        # 再查询必须能看到锁定（修复前 GET 是 405）
        resp = await client.get(f"/api/chapters/{CID}/lock")
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_locked"] is True

        # 不存在的章节 → 404
        resp = await client.get("/api/chapters/no-such/lock")
        assert resp.status_code == 404

    _run(_case())


def test_apiclient_has_patch_method() -> None:
    """ApiClient 必须提供 patch（前端锁定按钮使用，缺失会直接 AttributeError）."""
    from src.ui.api_client import ApiClient

    assert hasattr(ApiClient, "patch")
