""".aibk 归档格式读写 - zip容器+manifest+JSON数据文件."""
from __future__ import annotations

import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.logger import get_logger

ARCHIVE_VERSION = "1.0.0"
APP_VERSION = "0.1.0"


class ArchiveFormat:
    """.aibk 归档读写."""

    def __init__(self) -> None:
        self.logger = get_logger()

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def write_archive(self, target_path: str, data: dict[str, Any], project_id: str, project_name: str = "", options: dict | None = None) -> str:
        """写入 .aibk 归档（原子写入）."""
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target.with_suffix(".aibk.tmp")

        files_info: dict[str, dict] = {}
        item_count = 0

        try:
            with zipfile.ZipFile(str(tmp_path), "w", zipfile.ZIP_DEFLATED) as zf:
                for name, content in data.items():
                    if isinstance(content, (dict, list)):
                        raw = json.dumps(content, ensure_ascii=False, default=str).encode("utf-8")
                    elif isinstance(content, str):
                        raw = content.encode("utf-8")
                    else:
                        raw = str(content).encode("utf-8")
                    zf.writestr(f"{name}.json", raw)
                    files_info[f"{name}.json"] = {
                        "path": f"{name}.json",
                        "size_bytes": len(raw),
                        "sha256": self._sha256(raw),
                    }
                    if isinstance(content, list):
                        item_count += len(content)
                    elif isinstance(content, dict):
                        item_count += 1

                manifest = {
                    "archive_version": ARCHIVE_VERSION,
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "app_version": APP_VERSION,
                    "project_id": project_id,
                    "project_name": project_name,
                    "item_count": item_count,
                    "files": files_info,
                    "options": options or {},
                }
                manifest_raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
                zf.writestr("manifest.json", manifest_raw)

            import os as _os
            _os.replace(str(tmp_path), str(target))
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
            raise
        self.logger.info(f"归档写入完成: {target}, {item_count} 条目")
        return str(target)

    def read_archive(self, source_path: str) -> dict[str, Any]:
        """读取 .aibk 归档，校验 SHA256."""
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"归档文件不存在: {source_path}")

        result: dict[str, Any] = {}
        with zipfile.ZipFile(str(source), "r") as zf:
            manifest_raw = zf.read("manifest.json")
            manifest = json.loads(manifest_raw.decode("utf-8"))

            archive_version = manifest.get("archive_version", "1.0.0")
            if archive_version > ARCHIVE_VERSION:
                raise ValueError(f"归档版本 {archive_version} 高于当前应用支持版本 {ARCHIVE_VERSION}，请升级应用")

            for filename, file_info in manifest.get("files", {}).items():
                raw = zf.read(filename)
                expected_sha = file_info.get("sha256") if isinstance(file_info, dict) else file_info
                actual = self._sha256(raw)
                if actual != expected_sha:
                    raise ValueError(f"归档文件损坏：{filename} 校验失败")
                key = filename.replace(".json", "")
                result[key] = json.loads(raw.decode("utf-8"))

            result["_manifest"] = manifest
        return result

    def get_manifest(self, source_path: str) -> dict[str, Any]:
        """仅读取 manifest."""
        source = Path(source_path)
        with zipfile.ZipFile(str(source), "r") as zf:
            manifest_raw = zf.read("manifest.json")
            return json.loads(manifest_raw.decode("utf-8"))