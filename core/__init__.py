# -*- coding: utf-8 -*-
"""Mofang（墨仿）核心渲染引擎 — 仅供学习交流使用，请勿用于提交作业等不诚信场合。"""

from .template import PaperTemplate, WritingArea, PageGeometry
from .font_loader import FontLibrary, FontAsset
from .layout import LayoutEngine, LayoutResult, MissingGlyphReport
from .render import HandwritingRenderer, RenderParams
from .exporter import export_png, export_pdf
from .preset import PresetManager
from .region import corners_to_grid, grid_from_corners
from .pipeline import generate_pages, GenerationResult

__version__ = "0.1.0"
__all__ = [
    "PaperTemplate", "WritingArea", "PageGeometry",
    "FontLibrary", "FontAsset",
    "LayoutEngine", "LayoutResult", "MissingGlyphReport",
    "HandwritingRenderer", "RenderParams",
    "export_png", "export_pdf",
    "PresetManager",
    "corners_to_grid", "grid_from_corners",
]
