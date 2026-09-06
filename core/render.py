# -*- coding: utf-8 -*-
"""手写感渲染器。

自然度手段（幅度全部可调，seed 固定即可复现，“换一版”即换 seed）：
- 逐字水平/竖直位移抖动（模拟笔画落点不准）
- 逐字旋转抖动（模拟运笔歪斜）
- 逐字大小浮动
- 墨色浓淡抖动（alpha + 明度微变）
- 行基线低频波浪（整行微微起伏，避免直线感）
- 笔画加粗（模拟用力按压/钢笔出墨，缓解细字体的“打印感”）
- 英文/数字整词渲染（自然字距），仅在放不下时等比缩小
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, asdict

from PIL import Image, ImageDraw, ImageFont

from .template import PaperTemplate
from .layout import LayoutResult, PlacedToken
from .font_loader import FontAsset


@dataclass
class RenderParams:
    """渲染参数（预设持久化的最小单位，网页/桌面两端通用）。"""

    font_scale: float = 0.5       # 字号 = 行高 × font_scale
    text_rgb: tuple[int, int, int] = (30, 30, 34)   # 墨水颜色
    h_jitter: float = 0.05        # 水平笔画位移幅度（字宽的比例）
    v_jitter: float = 0.05        # 竖直笔画位移幅度（行高的比例）
    rotation: float = 2.5         # 笔画旋转幅度（度）
    size_jitter: float = 0.05     # 字号浮动比例
    ink_jitter: float = 0.16      # 墨色浓淡幅度（0=均匀）
    baseline_wave: float = 0.15   # 行基线波浪幅度（0~1，低频）
    stroke_bold: float = 1.0      # 笔画加粗（0~3，模拟按压/出墨）
    extra_col_gap: float = 0.0    # 字水平间距（字宽的比例，可为负=更紧凑）
    extra_row_gap: float = 0.0    # 字竖直间距（行距的比例，叠加在模板行距上）
    baseline_shift: float = 0.3   # 字底贴近横线（行高的比例，整体下移，可压线）
    seed: int = 42                # 随机种子

    def to_dict(self) -> dict:
        d = asdict(self)
        d["text_rgb"] = list(self.text_rgb)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RenderParams":
        known = set(cls.__dataclass_fields__)
        kw = {k: v for k, v in d.items() if k in known}
        if "text_rgb" in kw and isinstance(kw["text_rgb"], list):
            kw["text_rgb"] = tuple(kw["text_rgb"])
        return cls(**kw)

    def validate(self) -> list[str]:
        errs = []
        if not (0.3 <= self.font_scale <= 1.3):
            errs.append("字号比例应在 0.3 ~ 1.3 之间")
        if not all(0 <= c <= 255 for c in self.text_rgb):
            errs.append("文字 RGB 取值须在 0~255")
        for name in ("h_jitter", "v_jitter", "size_jitter", "ink_jitter"):
            v = getattr(self, name)
            if not (0 <= v <= 0.6):
                errs.append(f"{name} 应在 0 ~ 0.6 之间")
        for name in ("extra_col_gap", "extra_row_gap"):
            v = getattr(self, name)
            if not (-0.4 <= v <= 0.5):
                errs.append(f"{name} 应在 -0.4 ~ 0.5 之间")
        if not (0 <= self.baseline_shift <= 0.6):
            errs.append("字底贴近横线应在 0 ~ 0.6 之间")
        if not (0 <= self.rotation <= 25):
            errs.append("笔画旋转应在 0 ~ 25 度")
        if not (0 <= self.baseline_wave <= 1):
            errs.append("基线波浪应在 0 ~ 1 之间")
        if not (0 <= self.stroke_bold <= 3):
            errs.append("笔画加粗应在 0 ~ 3 之间")
        return errs


class _FontCache:
    """按 (路径, 像素大小) 缓存 ImageFont。"""

    def __init__(self):
        self._cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}

    def get(self, path: str, size: int) -> ImageFont.FreeTypeFont:
        key = (path, size)
        if key not in self._cache:
            self._cache[key] = ImageFont.truetype(path, size)
        return self._cache[key]


class HandwritingRenderer:
    """渲染器：模板 + 排版结果 + 字体 + 参数 → 每页 PIL Image。"""

    def __init__(self, font_cache: _FontCache | None = None):
        self.cache = font_cache or _FontCache()

    # ---------- 主入口 ----------
    def render(
        self,
        template: PaperTemplate,
        layout: LayoutResult,
        font: FontAsset,
        fallback_font: FontAsset | None,
        params: RenderParams,
    ) -> list[Image.Image]:
        errs = params.validate()
        if errs:
            raise ValueError("渲染参数不合法: " + "；".join(errs))

        pages: list[Image.Image] = []
        rot = float(getattr(template, "rotation_deg", 0.0) or 0.0)
        for page_idx, placed in enumerate(layout.pages):
            base = Image.open(template.image_path).convert("RGBA")
            if abs(rot) >= 0.05:
                # 倾斜模板：先摆正（文字沿横线书写），渲染完再转回原角度
                base = base.rotate(rot, resample=Image.BICUBIC,
                                   fillcolor=(255, 255, 255, 255))
            rng = random.Random(f"{params.seed}:{page_idx}")
            wave_phase = rng.uniform(0, math.tau)
            for tok in placed:
                self._draw_token(base, template, tok, font, fallback_font,
                                 params, rng, wave_phase)
            page = base.convert("RGB")
            if abs(rot) >= 0.05:
                page = page.rotate(-rot, resample=Image.BICUBIC,
                                   fillcolor=(255, 255, 255))
            pages.append(page)
        return pages

    # ---------- 单 token 绘制 ----------
    def _draw_token(
        self,
        canvas: Image.Image,
        template: PaperTemplate,
        tok: PlacedToken,
        font: FontAsset,
        fallback: FontAsset | None,
        params: RenderParams,
        rng: random.Random,
        wave_phase: float,
    ) -> None:
        area = template.area
        # 流式定位：x = 书写区左界 + 半格步进 × 列号。
        # 步进 = 字宽/2 × (1 + 字水平间距)；字宽 = 行高 × 字号比例（方块字宽=高），
        # 行距小的行字符更窄 → 自动容纳更多字，行与行字数可不同。
        row_lines = getattr(template, "row_lines", None)
        on_line = bool(row_lines and tok.row < len(row_lines))
        if on_line:
            lines = row_lines
            gap = (lines[tok.row] - lines[tok.row - 1]) if 0 < tok.row < len(lines) \
                else area.cell_h
            cell_h = max(8.0, gap)                       # 本行实际行高
            cy = lines[tok.row] - cell_h \
                + params.extra_row_gap * cell_h * tok.row   # 竖直间距：逐行累计下移
        else:
            cell_h = area.cell_h
            cy = area.y + tok.row * (cell_h + area.row_gap) \
                + params.extra_row_gap * cell_h * tok.row
        char_w = cell_h * params.font_scale                 # 方块字：宽=高
        half_adv = char_w / 2 * (1 + params.extra_col_gap)  # 半格步进
        cx = area.x + tok.col * half_adv
        token_w = tok.cells * half_adv

        # 基线保护：竖直抖动幅度不超过本行剩余空隙（贴合模式）
        v_jitter_eff = min(params.v_jitter,
                           max(0.0, (1.0 - params.font_scale) * 0.32)) if on_line \
            else params.v_jitter
        jy_raw = rng.uniform(-1, 1) * v_jitter_eff * cell_h
        # 行基线波浪：低频正弦，整行整体微微起伏（非 0 时会偏离真实横线）
        wave = math.sin(wave_phase + tok.col * 0.18) * cell_h * params.baseline_wave * 0.15

        # 逐字随机量（jy 已含基线保护、波浪与字底下沉）
        jx = rng.uniform(-1, 1) * params.h_jitter * char_w
        jy = jy_raw + wave + params.baseline_shift * cell_h
        rot = rng.uniform(-1, 1) * params.rotation
        scale = 1.0 + rng.uniform(-1, 1) * params.size_jitter
        ink = 1.0 - rng.uniform(0, params.ink_jitter)

        r, g, b = params.text_rgb
        alpha = int(255 * ink)
        drift = int((1 - ink) * 30)
        color = (min(255, r + drift), min(255, g + drift), min(255, b + drift), alpha)
        sw = int(round(params.stroke_bold))   # stroke_width

        use_fb = tok.use_fallback and fallback is not None
        path = fallback.path if use_fb else font.path

        if tok.squeezed:
            # 禁则挤入：缩到 55% 画在格子右下角
            base_size = max(6, int(char_w * scale * 0.55))
            jx += char_w * 0.28
            jy += cell_h * 0.30
            self._draw_one(canvas, path, tok.text, base_size, color, sw, rot, cx, cy,
                           char_w, cell_h, jx, jy, center=True)
            return

        if len(tok.text) > 1 and ord(tok.text[0]) < 256:
            # 半角串（英文/数字/URL）：整词渲染。
            # 词宽不足分配空间时拉大字距撑满（避免富余堆在词尾、词距显得过大）。
            fs = max(8, int(cell_h * 0.72 * params.font_scale / 0.88 * scale))
            try:
                probe = self.cache.get(path, fs)
                natural = sum(probe.getlength(ch) for ch in tok.text)
            except (OSError, Exception):
                natural = 0
            alloc = token_w * 0.94
            if natural > alloc > 0:
                fs = max(6, int(fs * alloc / natural))   # 放不下才等比缩小
            self._draw_one(canvas, path, tok.text, fs, color, sw, rot, cx, cy,
                           char_w, cell_h, jx, jy,
                           center=False, left_edge=cx + jx * 0.4,
                           justify_to=alloc)
            return

        base_size = max(8, int(char_w * scale))
        self._draw_one(canvas, path, tok.text, base_size, color, sw, rot, cx, cy,
                       char_w, cell_h, jx, jy,
                       center=False, token_w=token_w)

    def _draw_one(self, canvas, path, text, size, color, sw, rot,
                  cx, cy, cell_w, cell_h, jx, jy, center=False, left_edge=None,
                  token_w=None, justify_to=None):
        """画一个 token：独立瓦片（按文字实测宽度）+ 旋转 + 贴回。

        justify_to：目标宽度。给定时逐字符绘制并拉大字距，把词撑满目标宽
        （用于英文单词填满其分配空间，消除词尾富余造成的视觉大间距）。
        """
        try:
            fnt = self.cache.get(path, size)
        except OSError:
            return
        try:
            text_w = fnt.getlength(text)
        except Exception:
            text_w = size * max(1, len(text))
        pad = int(size * 0.5) + sw * 2
        tw = int(text_w) + pad * 2
        th = int(size * 1.6) + pad * 2
        tile = Image.new("RGBA", (max(4, tw), max(4, th)), (0, 0, 0, 0))
        d = ImageDraw.Draw(tile)
        try:
            tracking = 0.0
            if justify_to and len(text) > 1 and text_w < justify_to:
                tracking = min((justify_to - text_w) / (len(text) - 1),
                               0.30 * size)   # 字距上限：富余过大（如 URL）不硬撑
                if tracking * (len(text) - 1) < 4:
                    tracking = 0.0
            if tracking > 0:
                tw = int(text_w + tracking * (len(text) - 1)) + pad * 2   # 瓦片含拉伸后宽度
                th = int(size * 1.6) + pad * 2
                tile = Image.new("RGBA", (max(4, tw), max(4, th)), (0, 0, 0, 0))
                d = ImageDraw.Draw(tile)
                x = float(pad)
                for ch in text:
                    d.text((x, pad), ch, font=fnt, fill=color,
                           stroke_width=sw or 0, stroke_fill=color)
                    x += fnt.getlength(ch) + tracking
            else:
                d.text((pad, pad), text, font=fnt, fill=color,
                       stroke_width=sw or 0, stroke_fill=color)
        except UnicodeEncodeError:
            return
        if abs(rot) > 0.05:
            tile = tile.rotate(rot, resample=Image.BICUBIC, expand=False)
        tw, th = tile.size
        if center:
            center_x = cx + cell_w / 2 + jx
        elif left_edge is not None:
            center_x = left_edge + (tw - 2 * pad) / 2
        else:
            center_x = cx + (token_w or cell_w) / 2 + jx
        center_y = cy + cell_h / 2 + jy
        px, py = int(center_x - tw / 2), int(center_y - th / 2)
        canvas.alpha_composite(tile, (px, py))
