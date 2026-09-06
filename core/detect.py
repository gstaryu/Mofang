# -*- coding: utf-8 -*-
"""视觉定位：投影剖面法检测稿纸横线与书写区边界。

- 仅用于标注器初次定位（一次性 <0.5s）；渲染管线不依赖本模块。
- 输入：模板图片路径；可选 quad（四角标注四点）限定检测区域。
- 返回 ok / row_lines / x_left / x_right / pitch / rows / message。
- 横线过少返回 ok=False，调用方回退手动四角标注。
"""
from __future__ import annotations

import numpy as np
from PIL import Image


def _cluster(idxs, gap=4):
    idxs = list(idxs)
    if not idxs:
        return []
    groups = [[int(idxs[0])]]
    for v in idxs[1:]:
        if v - groups[-1][-1] <= gap:
            groups[-1].append(int(v))
        else:
            groups.append([int(v)])
    return [sum(g) / len(g) for g in groups]


def _median_gap(lines):
    gaps = [lines[i + 1] - lines[i] for i in range(len(lines) - 1)]
    if not gaps:
        return 0.0
    s = sorted(gaps)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _filter_irregular(lines, rel_tol=0.45):
    """剔除与中位行距差异过大的噪线（表格框线等）。"""
    if len(lines) < 3:
        return lines
    med = _median_gap(lines)
    if med <= 0:
        return lines
    keep = [lines[0]]
    for i in range(1, len(lines)):
        g = lines[i] - lines[i - 1]
        if abs(g - med) <= med * rel_tol:
            keep.append(lines[i])
    return keep


def detect_writing_area(image_path, quad=None, min_lines=4, auto_deskew=True):
    """检测稿纸横线与书写区左右边界（倾斜图自动纠斜后再检测）。

    quad: 可选 [(tl),(tr),(br),(bl)]，检测限定在其外接矩形内。
    返回 dict: ok, row_lines, x_left, x_right, pitch, rows, rotation_deg, image_size, message
    rotation_deg: 纠斜角。>0 表示原图倾斜，渲染时需先摆正、画完再转回。
    """
    work_path = image_path
    rotation_deg = 0.0
    if auto_deskew:
        try:
            rotation_deg = estimate_skew(image_path)
        except Exception:
            rotation_deg = 0.0
        if abs(rotation_deg) >= 0.3:
            work_path = deskewed_image_path(image_path, rotation_deg)
    try:
        im = Image.open(work_path).convert("L")
    except Exception as e:
        return {"ok": False, "message": f"图片无法打开: {e}"}
    a = np.asarray(im, dtype=np.float32)
    H, W = a.shape

    x0 = y0 = 0
    x1, y1 = W, H
    if quad and len(quad) == 4:
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        x0, x1 = max(0, int(min(xs))), min(W, int(max(xs)))
        y0, y1 = max(0, int(min(ys))), min(H, int(max(ys)))
        if x1 - x0 < 50 or y1 - y0 < 50:
            return {"ok": False, "message": "四角区域过小"}

    sub = a[y0:y1, x0:x1]
    bright = float(np.percentile(sub, 90))
    dark = sub < bright * 0.82

    row_frac = dark.mean(axis=1)
    thr = max(0.30, float(row_frac.max()) * 0.5)
    line_ys = _cluster(np.where(row_frac > thr)[0])
    line_ys = [y + y0 for y in line_ys]
    line_ys = _filter_irregular(line_ys)

    if len(line_ys) < min_lines:
        return {
            "ok": False,
            "message": "仅检测到 %d 条横线（不足 %d 条），建议手动四角标注" % (len(line_ys), min_lines),
            "row_lines": [round(v, 1) for v in line_ys],
            "rotation_deg": round(rotation_deg, 2),
        }

    band = dark[np.clip((np.array(line_ys) - y0).astype(int), 0, sub.shape[0] - 1), :]
    col_hit = band.mean(axis=0)
    on = np.where(col_hit > 0.5)[0]
    if len(on) < 50:
        x_left = x0 + W * 0.08
        x_right = x0 + W * 0.92
        bounds_from_lines = False
    else:
        x_left = x0 + float(np.percentile(on, 3))
        x_right = x0 + float(np.percentile(on, 97))
        bounds_from_lines = True

    pitch = _median_gap(line_ys)
    return {
        "ok": True,
        "rotation_deg": round(rotation_deg, 2),
        "row_lines": [round(v, 1) for v in line_ys],
        "x_left": round(float(x_left), 1),
        "x_right": round(float(x_right), 1),
        "pitch": round(pitch, 1),
        "rows": len(line_ys),
        "image_size": [W, H],
        "bounds_from_lines": bounds_from_lines,
        "message": "检测到 %d 条横线，平均行距 %.0fpx" % (len(line_ys), pitch)
                    + ("，已自动纠正 %.1f° 倾斜" % rotation_deg if abs(rotation_deg) >= 0.3 else ""),
    }


def build_template_fields(detect, skip_first_line=True, margin_expand=0.0):
    """把检测结果转成模板 area/row_lines 字段。

    skip_first_line: 跳过第一条检测线（第一行字写在第 1、2 条线之间）。
    margin_expand: 左右边界各向外扩张书写区宽度的比例（0=检测值）。
    """
    if not detect.get("ok"):
        return None
    lines = list(detect["row_lines"])
    if skip_first_line and len(lines) >= 2:
        lines = lines[1:]
    if not lines:
        return None
    width = detect["x_right"] - detect["x_left"]
    x_left = detect["x_left"] - width * margin_expand
    x_right = detect["x_right"] + width * margin_expand
    pitch = detect["pitch"]
    cell_w = pitch * 1.02
    cols = max(1, int((x_right - x_left) / cell_w))
    cell_h = pitch
    return {
        "rotation_deg": detect.get("rotation_deg", 0.0),
        "area": {
            "x": round(x_left, 1),
            "y": round(lines[0] - cell_h + 2, 1),
            "cell_w": round(cell_w, 1),
            "cell_h": round(cell_h, 1),
            "cols": cols,
            "rows": len(lines),
            "col_gap": 0,
            "row_gap": 0,
        },
        "row_lines": [round(v, 1) for v in lines],
        "cols": cols,
        "rows": len(lines),
        "x_left": round(x_left, 1),
        "x_right": round(x_right, 1),
        "pitch": pitch,
    }


def estimate_skew(image_path, max_angle=8.0, step_coarse=1.0, step_fine=0.2):
    """估计图片倾斜角（度）。返回把图转正所需的 PIL rotate 角度。

    原理：横线最“尖”的方向就是水平方向——对每个候选角旋转二值图，
    行投影的平方和越大说明横线越集中、越水平。粗扫 1° 后细化 0.2°。
    """
    im = Image.open(image_path).convert("L")
    im.thumbnail((700, 1000))
    a = np.asarray(im, dtype=np.float32)
    bright = float(np.percentile(a, 90))
    dark = (a < bright * 0.82).astype(np.uint8) * 255
    dark_im = Image.fromarray(dark)

    def score(ang):
        r = dark_im.rotate(ang, resample=Image.BILINEAR, fillcolor=0)
        prof = (np.asarray(r) > 0).sum(axis=1).astype(np.float32)
        return float((prof ** 2).sum())

    coarse = np.arange(-max_angle, max_angle + 1e-9, step_coarse)
    best = float(max(coarse, key=score))
    fine = np.arange(best - step_coarse, best + step_coarse + 1e-9, step_fine)
    best = float(max(fine, key=score))
    return best if abs(best) >= 0.2 else 0.0


def deskewed_image_path(image_path, angle):
    """返回摆正后的图片缓存路径（有缓存直接复用）。"""
    import os
    out = image_path + f".deskew{int(round(angle * 10))}.png"
    if not os.path.isfile(out):
        img = Image.open(image_path).convert("RGB")
        img.rotate(angle, resample=Image.BICUBIC, fillcolor=(255, 255, 255)).save(out)
    return out
