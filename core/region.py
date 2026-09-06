# -*- coding: utf-8 -*-
"""书写区域标注：四角点选 → 格网参数换算。

用户在模板图上依次点选书写区域四个角（左上→右上→右下→左下），
由四角几何推算等距格网（行列数由用户输入）。
V1 不做透视矫正，四角换算按边中点平均，可容忍轻微倾斜。
"""
from __future__ import annotations

from .template import WritingArea


def grid_from_corners(
    tl: tuple[float, float],
    tr: tuple[float, float],
    br: tuple[float, float],
    bl: tuple[float, float],
    rows: int,
    cols: int,
) -> WritingArea:
    """由四角 + 行列数推算 WritingArea。

    思路：
    - 起点 = 四角加权中心顶部（更抗单角点偏）；
    - 平均列间距 = 上边宽/cols 与下边宽/cols 取均值；
    - 平均行间距 = 左边高/rows 与右边高/rows 取均值；
    - 整体带一点倾斜时，取上下边中点倾斜量微调起始 x。
    """
    if rows < 1 or cols < 1:
        raise ValueError("行列数必须 ≥ 1")

    top_w = tr[0] - tl[0]
    bot_w = br[0] - bl[0]
    left_h = bl[1] - tl[1]
    right_h = br[1] - tr[1]
    if min(top_w, bot_w, left_h, right_h) <= 0:
        raise ValueError("四角点顺序错误：应为 左上→右上→右下→左下")

    cell_w = (top_w + bot_w) / 2 / cols
    cell_h = (left_h + right_h) / 2 / rows

    # 上下边中点的倾斜量折算到 x 起点
    top_mid_x = (tl[0] + tr[0]) / 2
    bot_mid_x = (bl[0] + br[0]) / 2
    skew = (bot_mid_x - top_mid_x) / 2

    x = tl[0] + top_w / 2 / cols + skew / rows
    y = (tl[1] + tr[1]) / 2 + left_h / 2 / rows

    return WritingArea(x=x, y=y, cell_w=cell_w, cell_h=cell_h,
                       cols=cols, rows=rows, col_gap=0.0, row_gap=0.0)


def corners_to_grid(
    corners: list[tuple[float, float]],
    rows: int,
    cols: int,
) -> list[list[tuple[float, float]]]:
    """返回 rows×cols 每格左上角坐标（双线性插值，供预览/未来非均匀渲染用）。"""
    if len(corners) != 4:
        raise ValueError("需要恰好 4 个角点")
    tl, tr, br, bl = corners
    grid = []
    for r in range(rows):
        row_pts = []
        for c in range(cols):
            v = r / (rows - 1) if rows > 1 else 0.0
            u = c / (cols - 1) if cols > 1 else 0.0
            top = (tl[0] + (tr[0] - tl[0]) * u, tl[1] + (tr[1] - tl[1]) * u)
            bottom = (bl[0] + (br[0] - bl[0]) * u, bl[1] + (br[1] - bl[1]) * u)
            left = (tl[0] + (bl[0] - tl[0]) * v, tl[1] + (bl[1] - tl[1]) * v)
            right = (tr[0] + (br[0] - tr[0]) * v, tr[1] + (br[1] - tr[1]) * v)
            row_pts.append(((top[0] + left[0] + bottom[0] + right[0]) / 4,
                            (top[1] + left[1] + bottom[1] + right[1]) / 4))
        grid.append(row_pts)
    return grid
