# -*- coding: utf-8 -*-
"""字体加载与缺字检测。

- 用户字体：TTF/OTF，由 fontTools 读取 cmap 得到字符覆盖集；
- 缺字降级：缺失字符用备用字体渲染，并记录到缺字报告。
"""
from __future__ import annotations

import hashlib
import os

from fontTools.ttLib import TTFont, TTLibError

FONT_EXTS = {".ttf", ".otf", ".ttc"}


def _file_id(path: str) -> str:
    return hashlib.md5(os.path.abspath(path).encode("utf-8")).hexdigest()[:12]


class FontAsset:
    """单个字体文件。"""

    def __init__(self, path: str, name: str | None = None, is_fallback: bool = False):
        if not os.path.isfile(path):
            raise FileNotFoundError(f"字体文件不存在: {path}")
        ext = os.path.splitext(path)[1].lower()
        if ext not in FONT_EXTS:
            raise ValueError(f"不支持的字体格式 {ext}（支持 .ttf/.otf/.ttc）")
        self.path = path
        self.name = name or os.path.splitext(os.path.basename(path))[0]
        self.id = _file_id(path)
        self.is_fallback = is_fallback
        self._glyphs: set[str] | None = None  # 惰性加载

    @property
    def glyphs(self) -> set[str]:
        """字体 cmap 覆盖的字符集合（首次访问时解析，损坏会抛 ValueError）。"""
        if self._glyphs is None:
            try:
                font = TTFont(self.path, fontNumber=0, lazy=True)
                cmap = font.getBestCmap()
                self._glyphs = {chr(cp) for cp in cmap.keys()}
                font.close()
            except (TTLibError, Exception) as e:
                raise ValueError(f"字体文件损坏或无法解析（{self.name}）: {e}") from e
        return self._glyphs

    def covers(self, text: str) -> set[str]:
        """返回 text 中该字体缺失的字符集合（空白不算缺）。"""
        return {ch for ch in set(text) if ch not in self.glyphs and not ch.isspace()}

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "is_fallback": self.is_fallback,
            "glyph_count": len(self.glyphs),
        }


class FontLibrary:
    """字体库：管理用户字体目录 + 备用字体。"""

    def __init__(self, fonts_dir: str):
        self.fonts_dir = fonts_dir
        os.makedirs(fonts_dir, exist_ok=True)
        self.fallback_path = self._find_system_fallback()
        self._fallback: FontAsset | None = None
        self._broken: list[str] = []

    @staticmethod
    def _find_system_fallback() -> str | None:
        """在常见位置寻找一个可用中文备字体。"""
        candidates = [
            r"C:\Windows\Fonts\msyh.ttc",
            r"C:\Windows\Fonts\msyhl.ttc",
            r"C:\Windows\Fonts\simsun.ttc",
            r"C:\Windows\Fonts\simhei.ttf",
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        return None

    @property
    def fallback(self) -> FontAsset | None:
        if self._fallback is None and self.fallback_path:
            try:
                self._fallback = FontAsset(self.fallback_path, name="系统备用字体", is_fallback=True)
            except (ValueError, FileNotFoundError):
                self._fallback = None
        return self._fallback

    def scan(self) -> list[FontAsset]:
        """扫描字体目录；损坏文件记入 broken_files，不中断。"""
        fonts: list[FontAsset] = []
        broken: list[str] = []
        for fn in sorted(os.listdir(self.fonts_dir)):
            ext = os.path.splitext(fn)[1].lower()
            if ext not in FONT_EXTS:
                continue
            try:
                fonts.append(FontAsset(os.path.join(self.fonts_dir, fn)))
            except (ValueError, FileNotFoundError):
                broken.append(fn)
        self._broken = broken
        return fonts

    @property
    def broken_files(self) -> list[str]:
        return self._broken

    def get(self, font_id_or_name: str) -> FontAsset | None:
        for f in self.scan():
            if f.id == font_id_or_name or f.name == font_id_or_name:
                return f
        return None

    def add(self, src_path: str) -> FontAsset:
        """复制字体文件到字体库目录；解析失败抛 ValueError。"""
        ext = os.path.splitext(src_path)[1].lower()
        if ext not in FONT_EXTS:
            raise ValueError(f"不支持的字体格式 {ext}（支持 .ttf/.otf/.ttc）")
        dst = os.path.join(self.fonts_dir, os.path.basename(src_path))
        if os.path.abspath(src_path) != os.path.abspath(dst):
            with open(src_path, "rb") as fi, open(dst, "wb") as fo:
                fo.write(fi.read())
        return FontAsset(dst)  # 解析失败会在这里抛出
