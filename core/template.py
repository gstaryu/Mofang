# -*- coding: utf-8 -*-
"""稿纸模板数据模型。

坐标单位说明：
- 图像内部一律使用“像素”（即模板原图的像素坐标系）；
- 物理尺寸使用毫米（mm），打印对齐依赖 mm 精确映射（见 exporter.py）。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict, field

MM_PER_INCH = 25.4


@dataclass
class WritingArea:
    """书写区域：以第一个格子左上角为原点的等距格网。"""

    x: float            # 第一格左上角像素 x
    y: float            # 第一格左上角像素 y
    cell_w: float       # 格宽（像素）
    cell_h: float       # 格高（像素）
    cols: int           # 每行格数
    rows: int           # 每页行数
    col_gap: float = 0.0   # 相邻格水平额外间距
    row_gap: float = 0.0   # 行距（行与行之间的额外像素距离）

    def cell_origin(self, row: int, col: int) -> tuple[float, float]:
        """返回第 row 行第 col 列格子左上角像素坐标。"""
        return (
            self.x + col * (self.cell_w + self.col_gap),
            self.y + row * (self.cell_h + self.row_gap),
        )

    @property
    def col_pitch(self) -> float:
        return self.cell_w + self.col_gap

    @property
    def row_pitch(self) -> float:
        return self.cell_h + self.row_gap

    @property
    def cells_per_page(self) -> int:
        return self.rows * self.cols


@dataclass
class PageGeometry:
    """物理页面信息，决定打印对齐。"""

    width_mm: float = 210.0
    height_mm: float = 297.0

    def dpi_for(self, image_w_px: int, image_h_px: int) -> tuple[float, float]:
        """由图像像素与物理尺寸推算 DPI。"""
        return (
            image_w_px / (self.width_mm / MM_PER_INCH),
            image_h_px / (self.height_mm / MM_PER_INCH),
        )

    def px_per_mm(self, image_w_px: int) -> float:
        return image_w_px / self.width_mm


@dataclass
class PaperTemplate:
    """一个可复用的稿纸模板 = 背景图 + 书写区域 + 物理尺寸。

    row_lines（可选）：每行“书写基线”（横线 y 像素坐标）的显式列表。
    稿纸横线间距不均匀时（拍照/扫描件常见），提供它可让每行文字精确贴合
    真实横线；为空则用 area 的等距格网。
    """

    id: str
    name: str
    image_path: str                 # 模板背景图绝对/相对路径
    area: WritingArea
    physical: PageGeometry = field(default_factory=PageGeometry)
    note: str = ""
    row_lines: list[float] = field(default_factory=list)
    rotation_deg: float = 0.0   # 自动纠斜角：渲染先摆正、画完转回（0=不倾斜）

    # ---------- 派生信息 ----------
    def image_size(self) -> tuple[int, int]:
        from PIL import Image  # 延迟导入，保持模块轻量
        with Image.open(self.image_path) as im:
            return im.size

    def dpi(self) -> tuple[float, float]:
        w, h = self.image_size()
        return self.physical.dpi_for(w, h)

    def capacity_chars(self) -> int:
        """每页可容纳的整格字符数。"""
        return self.area.cells_per_page

    # ---------- 序列化 ----------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict, base_dir: str = "") -> "PaperTemplate":
        area = WritingArea(**d["area"])
        phys = PageGeometry(**d.get("physical", {}))
        path = d["image_path"]
        if base_dir and not os.path.isabs(path):
            path = os.path.join(base_dir, path)
        return cls(
            id=d["id"], name=d["name"], image_path=path,
            area=area, physical=phys, note=d.get("note", ""),
            row_lines=[float(v) for v in d.get("row_lines", [])],
            rotation_deg=float(d.get("rotation_deg", 0.0)),
        )

    def save(self, json_path: str) -> None:
        os.makedirs(os.path.dirname(json_path) or ".", exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, json_path: str) -> "PaperTemplate":
        with open(json_path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f), base_dir=os.path.dirname(json_path))

    # ---------- 校验 ----------
    def validate(self) -> list[str]:
        """返回错误信息列表；空列表表示模板参数自洽。"""
        errors: list[str] = []
        if not os.path.isfile(self.image_path):
            errors.append(f"模板图片不存在: {self.image_path}")
            return errors
        try:
            iw, ih = self.image_size()
        except Exception as e:  # 图片损坏
            errors.append(f"模板图片无法打开（可能已损坏）: {e}")
            return errors
        a = self.area
        right = a.x + a.cols * a.col_pitch
        bottom = a.y + a.rows * a.row_pitch
        if self.row_lines and len(self.row_lines) < a.rows:
            errors.append(
                f"row_lines 行基线数量（{len(self.row_lines)}）少于行数（{a.rows}）"
            )
        if a.cols < 1 or a.rows < 1:
            errors.append("行列数必须 ≥ 1")
        if a.cell_w <= 0 or a.cell_h <= 0:
            errors.append("格子尺寸必须 > 0")
        if right > iw + 0.5 or bottom > ih + 0.5:
            errors.append(
                f"书写区域超出图片边界（区域右下角 ({right:.0f},{bottom:.0f})，"
                f"图片尺寸 ({iw},{ih})）"
            )
        if self.physical.width_mm <= 0 or self.physical.height_mm <= 0:
            errors.append("物理尺寸必须 > 0")
        dpi_x, dpi_y = self.dpi()
        if not (25 <= dpi_x <= 2400 and 25 <= dpi_y <= 2400):
            errors.append(
                f"由物理尺寸推算的 DPI 异常（{dpi_x:.0f}x{dpi_y:.0f}），"
                "请检查物理尺寸是否与图片实际打印尺寸一致"
            )
        return errors
