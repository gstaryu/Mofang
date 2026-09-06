# -*- coding: utf-8 -*-
"""导出：PNG 序列 / 可直接打印的 PDF。

打印对齐关键：PDF 页面物理尺寸强制等于模板物理尺寸（mm），
用户打印时选择“实际大小/100%”即可与实体稿纸对齐。
"""
from __future__ import annotations

import io
import os

import img2pdf
from PIL import Image

MM_PER_INCH = 25.4


def export_png(pages: list[Image.Image], out_dir: str, prefix: str = "mofang") -> list[str]:
    """逐页导出 PNG，返回文件路径列表。"""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for i, im in enumerate(pages, 1):
        p = os.path.join(out_dir, f"{prefix}_p{i:02d}.png")
        im.save(p, dpi=im.info.get("dpi", (300, 300)))
        paths.append(p)
    return paths


def export_pdf(
    pages: list[Image.Image],
    out_path: str,
    page_size_mm: tuple[float, float],
) -> str:
    """合成 PDF，页面物理尺寸 = page_size_mm（宽, 高）。

    使用 img2pdf 无损嵌入（PNG 像素不重压缩），保证打印像素-物理尺寸一致。
    """
    if not pages:
        raise ValueError("没有可导出的页面")
    w_pt = page_size_mm[0] / MM_PER_INCH * 72.0
    h_pt = page_size_mm[1] / MM_PER_INCH * 72.0
    layout_fun = img2pdf.get_layout_fun(pagesize=(w_pt, h_pt))

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    # img2pdf 接受已编码图像字节；用 PNG 内存流避免 JPEG 二压
    blobs = []
    for im in pages:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        blobs.append(buf.getvalue())

    with open(out_path, "wb") as f:
        f.write(img2pdf.convert(blobs, layout_fun=layout_fun))
    return out_path
