# -*- coding: utf-8 -*-
"""预设管理：渲染参数 + 模板/字体选择的 JSON 持久化。

预设文件网页版与桌面版通用（同一 data/presets 目录）。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

SAFE_NAME = re.compile(r'[\\/:*?"<>|]')


def _safe(name: str) -> str:
    return SAFE_NAME.sub("_", name).strip() or "unnamed"


class PresetManager:
    def __init__(self, presets_dir: str):
        self.dir = presets_dir
        os.makedirs(presets_dir, exist_ok=True)

    def _path(self, name: str) -> str:
        return os.path.join(self.dir, _safe(name) + ".json")

    def save(self, name: str, data: dict) -> str:
        """data 结构（由调用方组装）：template_id/font_id/render_params/..."""
        doc = dict(data)
        doc["name"] = name
        doc["created"] = datetime.now().isoformat(timespec="seconds")
        path = self._path(name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        return path

    def load(self, name: str) -> dict:
        path = self._path(name)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"预设不存在: {name}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def list(self) -> list[dict]:
        """返回 [{name, created, template_id, font_id}]，按创建时间倒序。"""
        items = []
        for fn in os.listdir(self.dir):
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.dir, fn), encoding="utf-8") as f:
                    d = json.load(f)
                items.append({
                    "name": d.get("name", fn[:-5]),
                    "created": d.get("created", ""),
                    "template_id": d.get("template_id", ""),
                    "font_id": d.get("font_id", ""),
                })
            except (json.JSONDecodeError, OSError):
                continue  # 损坏的预设跳过
        items.sort(key=lambda x: x["created"], reverse=True)
        return items

    def delete(self, name: str) -> bool:
        path = self._path(name)
        if os.path.isfile(path):
            os.remove(path)
            return True
        return False
