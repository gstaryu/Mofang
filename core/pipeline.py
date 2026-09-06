# -*- coding: utf-8 -*-
"""端到端流水线：模板 + 字体 + 文本 + 参数 → 页面图像与排版报告。

网页版与桌面版共用此入口，保证双端行为一致。
"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import Image

from .template import PaperTemplate, WritingArea, PageGeometry
from .font_loader import FontAsset
from .layout import LayoutEngine, LayoutResult
from .render import HandwritingRenderer, RenderParams


@dataclass
class GenerationResult:
    pages: list[Image.Image]
    layout: LayoutResult
    template_errors: list[str]


# 低分辨率渲染的缩放模板图缓存：{ (image_path, scale): new_path }
_SCALED_IMG_CACHE: dict[tuple[str, float], str] = {}


def _scaled_template(template: PaperTemplate, s: float) -> PaperTemplate:
    """生成按 s 缩放的模板（图片重采样 + 几何等比缩放），用于快速预览。"""
    key = (template.image_path, round(s, 3))
    path = _SCALED_IMG_CACHE.get(key)
    if not path or not __import__("os").path.isfile(path):
        img = Image.open(template.image_path).convert("RGB")
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))),
                         Image.BILINEAR)
        path = key[0] + f".scaled{int(s * 100)}.png"
        img.save(path)
        _SCALED_IMG_CACHE[key] = path
    a = template.area
    area = WritingArea(
        x=a.x * s, y=a.y * s, cell_w=a.cell_w * s, cell_h=a.cell_h * s,
        cols=a.cols, rows=a.rows, col_gap=a.col_gap * s, row_gap=a.row_gap * s,
    )
    return PaperTemplate(
        id=template.id, name=template.name, image_path=path, area=area,
        physical=template.physical, note=template.note,
        row_lines=[v * s for v in template.row_lines],
    )


def generate_pages(
    template: PaperTemplate,
    font: FontAsset,
    fallback: FontAsset | None,
    text: str,
    params: RenderParams,
    render_scale: float = 1.0,
) -> GenerationResult:
    """校验 → 排版 → 渲染。模板/参数校验失败抛 ValueError。

    render_scale < 1 时按比例缩放模板与几何做低分辨率快速渲染
    （预览拖动用；导出恒为 1.0，不受影响）。
    """
    if render_scale < 1.0:
        template = _scaled_template(template, max(0.1, min(1.0, render_scale)))
    errs = template.validate()
    if errs:
        raise ValueError("模板配置有误：" + "；".join(errs))
    perrs = params.validate()
    if perrs:
        raise ValueError("渲染参数有误：" + "；".join(perrs))

    missing = font.covers(text)
    # 流式排版：每行字数由“字号（随行高自适应）× 字水平间距”自动决定，
    # 行与行可不同。模板 cols 仅作为书写区宽度基准（avail）。
    area = template.area
    eff_tpl = PaperTemplate(id=template.id, name=template.name,
                            image_path=template.image_path, area=area,
                            physical=template.physical, note=template.note,
                            row_lines=template.row_lines)
    avail = area.cols * (area.cell_w + area.col_gap)   # 书写区可用宽度
    if template.row_lines:
        lines = template.row_lines
        row_caps = []
        row_char_ws = []
        for r in range(len(lines)):
            gap = (lines[r] - lines[r - 1]) if r > 0 else area.cell_h
            char_w = max(6.0, gap * params.font_scale)
            row_char_ws.append(char_w)
            adv = max(char_w * 0.2,
                      char_w / 2 * (1 + params.extra_col_gap))   # 半格步进（负间距防重叠过度）
            row_caps.append(max(2, int(avail / adv)))
    else:
        char_w = area.cell_h * params.font_scale
        adv = max(char_w * 0.2, char_w / 2 * (1 + params.extra_col_gap))
        one = max(2, int(avail / adv))
        row_caps = [one] * area.rows
        row_char_ws = [char_w] * area.rows
    # 英文/数字按字体实测宽度分配占格（参考字号 100 下的像素宽）
    try:
        from PIL import ImageFont
        ref_font = ImageFont.truetype(font.path, 100)
        ascii_measure = lambda s: sum(ref_font.getlength(c) for c in s)
    except (OSError, Exception):
        ascii_measure = None
    engine = LayoutEngine()
    layout = engine.layout(
        text, cols=area.cols, rows=area.rows, page_count=1024,
        coverage_check=lambda ch: ch in missing,
        row_caps=row_caps, row_char_ws=row_char_ws,
        extra_col_gap=params.extra_col_gap,
        ascii_measure=ascii_measure,
    )
    layout.missing.has_fallback_font = fallback is not None

    renderer = HandwritingRenderer()
    pages = renderer.render(eff_tpl, layout, font, fallback, params)
    return GenerationResult(pages=pages, layout=layout, template_errors=errs)
