# -*- coding: utf-8 -*-
"""Phase 1 冒烟测试：模板 + 字体 + 排版 + 渲染 → PNG。

用法: python tests/test_phase1.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image

from core.template import PaperTemplate, WritingArea, PageGeometry
from core.font_loader import FontLibrary, FontAsset
from core.layout import LayoutEngine
from core.render import HandwritingRenderer, RenderParams
from core.exporter import export_png

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMG = os.path.join(ROOT, "data", "templates", "A4本子.jpg")
FONT = os.path.join(ROOT, "data", "fonts", "青叶手写体.ttf")
OUT = os.path.join(ROOT, "data", "output")

TEXT = """抄写任务测试。中文排版需要处理标点符号的避头尾规则，比如逗号、句号不能出现在行首，引号“开括号”不能挂在行尾。
破折号——占两格，省略号……也占两格。
Third line mixes ASCII like English words and numbers 12345.
生僻字测试：饕餮龘齉（部分字体缺字时应降级到备用字体）。
行首禁则触发测试，这行末尾故意放一个字加标点逼出挤格效果，测试挤格，
"""

img = Image.open(IMG)
W, H = img.size
print(f"模板图片尺寸: {W}x{H}")

# 使用由横线检测生成的预置模板（真实场景由四角标注得到）
TPL_JSON = os.path.join(ROOT, "data", "templates", "a4benzi.json")
tpl = PaperTemplate.load(TPL_JSON)
area = tpl.area
errs = tpl.validate()
assert not errs, f"模板校验失败: {errs}"
print(f"DPI: {tpl.dpi()[0]:.0f}x{tpl.dpi()[1]:.0f}, 每页容量: {tpl.capacity_chars()} 格")

lib = FontLibrary(os.path.join(ROOT, "data", "fonts"))
font = FontAsset(FONT)
print(f"字体: {font.name}, 字形数: {len(font.glyphs)}")
missing_in_font = font.covers(TEXT)
print(f"该字体对测试文本缺失: {missing_in_font or '无'}")

engine = LayoutEngine()
result = engine.layout(
    TEXT, cols=area.cols, rows=area.rows, page_count=2,
    coverage_check=lambda ch: ch in missing_in_font,
)
result.missing.has_fallback_font = lib.fallback is not None
print(f"页数: {len(result.pages)}, 溢出: {result.overflow_chars} 格")
print(f"缺字报告: {result.missing.summary}")

params = RenderParams(seed=7)
renderer = HandwritingRenderer()
pages = renderer.render(tpl, result, font, lib.fallback, params)
paths = export_png(pages, OUT, "phase1")
print(f"导出: {paths}")
print("OK")
