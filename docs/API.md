# 墨仿 Mofang API 文档

Base URL：`http://127.0.0.1:8642`（可在 start.bat 改端口）
交互式文档：`/docs`（FastAPI 自动生成的 OpenAPI/Swagger UI）

## 模板

### `GET /api/templates`
列出所有模板。返回 `PaperTemplate[]`：

```json
{
  "id": "a4benzi",
  "name": "A4横线本（预置）",
  "image_path": "D:\\...\\A4本子.jpg",
  "area": {"x": 400.0, "y": 189.5, "cell_w": 158.0, "cell_h": 151.5,
           "cols": 20, "rows": 32, "col_gap": 0, "row_gap": 0},
  "physical": {"width_mm": 210.0, "height_mm": 297.0},
  "note": "", "image_exists": true, "json_file": "a4benzi.json"
}
```

### `POST /api/templates/upload`
上传模板图片（multipart 字段 `file`，支持 jpg/jpeg/png/webp/bmp）。
返回 `{"image_file": "up_x1.jpg", "url": "/files/templates/up_x1.jpg", "width": 4000, "height": 5657}`。
失败（400）：格式不支持 / 图片损坏。

### `POST /api/templates`
创建模板。Body：

```json
{"name": "我的方格本", "image_file": "up_x1.jpg",
 "area": {"x": 100, "y": 150, "cell_w": 40, "cell_h": 40, "cols": 10, "rows": 20},
 "width_mm": 210, "height_mm": 297,
 "row_lines": [520.0, 670.0], "rotation_deg": 0.0,
 "template_id": ""}
```

`row_lines` 为可选的逐行书写基线；`rotation_deg` 为自动纠斜角；`template_id` 非空 = 原地更新该模板（微调/重命名）。  
返回创建/更新后的模板；400 = 参数越界/区域超出图片/DPI 异常（信息含具体原因）。

### `DELETE /api/templates/{tpl_id}`
删除模板 JSON（不删除图片文件）。404 = 不存在。

### `POST /api/templates/detect`
视觉定位：检测稿纸横线与书写区左右边界（投影剖面法，约 0.3s）。Body：

```json
{"image_file": "up_x1.jpg", "quad": null, "skip_first_line": false, "margin_expand": 0.0}
```

→ `{"detect": {"ok": true, "row_lines": [...], "x_left": 396.4, "x_right": 3854.6,
   "pitch": 150.0, "rows": 33, "rotation_deg": 4.6, "message": "...已自动纠正 4.6° 倾斜"},
   "fields": {...模板 area/row_lines/rotation_deg 字段或 null}}`
倾斜照片自动纠斜：`rotation_deg` > 0 时行基线在摆正坐标系中，渲染需先摆正、画完转回。
`quad` 可选（四角标注 [[x,y]×4]，限定检测区域）。检测失败 `ok=false` + 建议手动标注。

### `POST /api/templates/relocate`
对已保存模板重新视觉定位并保存。Body `{"template_id": "a4benzi", "skip_first_line": true}`。

## 字体

### `GET /api/fonts`
返回 `{"fonts": [{id, name, path, is_fallback, glyph_count}], "broken": ["坏文件名"], "has_fallback": true}`

### `POST /api/fonts/upload`
上传字体（multipart `file`，ttf/otf/ttc）。返回字体对象；400 = 格式不支持/解析失败。

### `POST /api/fonts/check`
Body `{"font_id": "...", "text": "..."}` → `{"missing": ["龘"], "has_fallback": true}`

## 渲染 / 导出

### `POST /api/render/preview`
Body：

```json
{"template_id": "a4benzi", "font_id": "5622c92a5403",
 "text": "要渲染的文字", "page": 0, "scale": 1.0,
 "params": {"font_scale": 0.5, "text_rgb": [30,30,34], "h_jitter": 0.05,
            "v_jitter": 0.05, "rotation": 2.5, "size_jitter": 0.05,
            "ink_jitter": 0.16, "baseline_wave": 0.15, "stroke_bold": 1,
            "extra_col_gap": 0.0, "extra_row_gap": 0.0,
            "baseline_shift": 0.3, "seed": 42}}
```

`scale` < 1 时为低分辨率快速渲染（前端拖动实时预览用；0.22 约 0.1s）。  
返回第 `page`+1 页 PNG（0-based；服务端按输入哈希缓存生成结果，翻页秒切）。响应头 `X-Mofang-Info`（JSON）：

```json
{"page_count": 3, "cells_per_page": 704, "overflow_chars": 0,
 "total_pages": 3, "page": 0,
 "missing": {"missing_chars": ["龘"], "fallback_used": ["龘"],
             "has_fallback_font": true, "summary": "主字体缺 1 个字符：龘；已用系统备用字体顶替"}}
```

`params` 所有键可选（缺省用默认值）；400 = 模板/字体/参数不合法。

### `POST /api/export/pdf`
Body 同上。返回 PDF 文件流（`Content-Disposition: attachment`），页面物理尺寸=模板 mm 尺寸；`X-Mofang-Info` 同上。

### `POST /api/export/png`
Body 同上（scale 强制 1.0；`save_path` 可选直存）。返回**全部页面**的 zip（`mofang_p01.png ... mofang_pNN.png`）。

## 预设

### `GET /api/presets`
→ `[{"name": "作业预设", "created": "2026-09-05T15:00:00", "template_id": "...", "font_id": "..."}]`（按创建时间倒序）

### `POST /api/presets`
Body `{"name": "作业预设", "template_id": "...", "font_id": "...", "params": {...}}` → `{"ok": true}`

### `GET /api/presets/{name}`
→ 完整预设文档。404 = 不存在。

### `DELETE /api/presets/{name}`
→ `{"ok": true}`。404 = 不存在。

## 静态资源

- `/` — 网页版界面
- `/files/templates/{文件名}` — 模板图片
- `/files/fonts/{文件名}` — 字体文件（前端 FontFace 预览用）
- `/docs` — Swagger UI

## 错误格式

所有错误为 `{"detail": "中文错误信息"}` + 对应 4xx 状态码。
