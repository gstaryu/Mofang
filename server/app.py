# -*- coding: utf-8 -*-
"""Mofang 网页版服务：FastAPI 薄外壳，把 core 包成 HTTP API。

启动: python -m uvicorn server.app:app --port 8642   (或使用 start.bat)
"""
from __future__ import annotations

import io
import json
import os
import secrets
import shutil
import sys

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.template import PaperTemplate, WritingArea, PageGeometry  # noqa: E402
from core.font_loader import FontLibrary  # noqa: E402
from core.preset import PresetManager  # noqa: E402
from core.render import RenderParams  # noqa: E402
from core.pipeline import generate_pages  # noqa: E402
from core.exporter import export_pdf  # noqa: E402
from core.detect import detect_writing_area  # noqa: E402
from core.paths import ensure_data_dirs  # noqa: E402

DATA = os.environ.get("MOFANG_DATA") or os.path.join(ROOT, "data")
ensure_data_dirs(DATA)
TPL_DIR = os.path.join(DATA, "templates")
OUT_DIR = os.path.join(DATA, "output")
WEB_DIR = os.path.join(ROOT, "server", "web")

app = FastAPI(title="Mofang 墨仿 API", version="0.1.0")
fonts = FontLibrary(os.path.join(DATA, "fonts"))
presets = PresetManager(os.path.join(DATA, "presets"))


# ---------------- 模板注册表 ----------------
def _template_json(id_: str) -> str:
    return os.path.join(TPL_DIR, f"{id_}.json")


def list_templates() -> list[dict]:
    out = []
    for fn in os.listdir(TPL_DIR):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(TPL_DIR, fn), encoding="utf-8") as f:
                d = json.load(f)
            img = d.get("image_path", "")
            d["image_exists"] = os.path.isfile(img)
            d["json_file"] = fn
            out.append(d)
        except (json.JSONDecodeError, OSError):
            continue
    return out


def load_template(id_: str) -> PaperTemplate:
    path = _template_json(id_)
    if not os.path.isfile(path):
        raise HTTPException(404, f"模板不存在: {id_}")
    try:
        return PaperTemplate.load(path)
    except Exception as e:
        raise HTTPException(400, f"模板文件损坏: {e}")


# ---------------- 静态资源 ----------------
app.mount("/web", StaticFiles(directory=WEB_DIR), name="web")
app.mount("/files/templates", StaticFiles(directory=TPL_DIR), name="templates")
app.mount("/files/fonts", StaticFiles(directory=os.path.join(DATA, "fonts")), name="fonts")


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


# ---------------- 模板 API ----------------
class AreaIn(BaseModel):
    x: float
    y: float
    cell_w: float
    cell_h: float
    cols: int = Field(gt=0, le=100)
    rows: int = Field(gt=0, le=200)
    col_gap: float = 0
    row_gap: float = 0


class TemplateIn(BaseModel):
    name: str
    image_file: str           # 已上传的图片文件名
    area: AreaIn
    width_mm: float = 210
    height_mm: float = 297
    note: str = ""
    row_lines: list[float] = Field(default_factory=list)
    rotation_deg: float = 0.0     # 自动纠斜角
    template_id: str = ""     # 非空 = 更新该模板（微调保存），否则新建


@app.get("/api/templates")
def api_list_templates():
    return list_templates()


@app.post("/api/templates/upload")
async def upload_template_image(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
        raise HTTPException(400, f"不支持的图片格式 {ext}（支持 jpg/png/webp/bmp）")
    tid = secrets.token_hex(4)
    fn = f"up_{tid}{ext}"
    path = os.path.join(TPL_DIR, fn)
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    from PIL import Image
    try:
        with Image.open(path) as im:
            w, h = im.size
            im.verify()
    except Exception as e:
        os.remove(path)
        raise HTTPException(400, f"图片无法打开（可能已损坏）: {e}")
    return {"image_file": fn, "url": f"/files/templates/{fn}", "width": w, "height": h}


@app.post("/api/templates")
def create_template(body: TemplateIn):
    img_path = os.path.join(TPL_DIR, os.path.basename(body.image_file))
    if not os.path.isfile(img_path):
        raise HTTPException(404, "图片不存在，请先上传")
    area = WritingArea(**body.area.model_dump())
    tpl_id = body.template_id if body.template_id else secrets.token_hex(4)
    tpl = PaperTemplate(
        id=tpl_id, name=body.name, image_path=img_path,
        area=area, physical=PageGeometry(body.width_mm, body.height_mm),
        note=body.note, row_lines=list(body.row_lines),
        rotation_deg=float(body.rotation_deg),
    )
    errs = tpl.validate()
    if errs:
        raise HTTPException(400, "；".join(errs))
    tpl.save(_template_json(tpl.id))
    return tpl.to_dict()


@app.delete("/api/templates/{tpl_id}")
def delete_template(tpl_id: str):
    path = _template_json(tpl_id)
    if not os.path.isfile(path):
        raise HTTPException(404, "模板不存在")
    os.remove(path)
    return {"ok": True}


class DetectIn(BaseModel):
    image_file: str
    quad: list[list[float]] | None = None   # 可选：四角标注 [[x,y]×4]
    skip_first_line: bool = True
    margin_expand: float = 0.0


@app.post("/api/templates/detect")
def api_detect(body: DetectIn):
    """视觉定位：检测横线与左右边界（一次性 <0.5s）。"""
    from core.detect import build_template_fields
    img_path = os.path.join(TPL_DIR, os.path.basename(body.image_file))
    if not os.path.isfile(img_path):
        raise HTTPException(404, "图片不存在，请先上传")
    quad = [tuple(p) for p in body.quad] if body.quad and len(body.quad) == 4 else None
    det = detect_writing_area(img_path, quad=quad)
    fields = build_template_fields(det, skip_first_line=body.skip_first_line,
                                   margin_expand=body.margin_expand) if det.get("ok") else None
    return {"detect": det, "fields": fields}


class RelocateIn(BaseModel):
    template_id: str
    skip_first_line: bool = True
    margin_expand: float = 0.0


@app.post("/api/templates/relocate")
def api_relocate(body: RelocateIn):
    """对已保存模板重新视觉定位（更新 area/row_lines 并保存）。"""
    from core.detect import build_template_fields
    tpl = load_template(body.template_id)
    det = detect_writing_area(tpl.image_path)
    fields = build_template_fields(det, skip_first_line=body.skip_first_line,
                                   margin_expand=body.margin_expand) if det.get("ok") else None
    if not fields:
        return {"ok": False, "detect": det}
    tpl.area = WritingArea(**fields["area"])
    tpl.row_lines = fields["row_lines"]
    tpl.rotation_deg = float(fields.get("rotation_deg", 0.0))
    tpl.save(_template_json(tpl.id))
    return {"ok": True, "detect": det, "template": tpl.to_dict()}


# ---------------- 字体 API ----------------
@app.get("/api/fonts")
def api_list_fonts():
    return {
        "fonts": [f.to_dict() for f in fonts.scan()],
        "broken": fonts.broken_files,
        "has_fallback": fonts.fallback is not None,
    }


@app.post("/api/fonts/upload")
async def upload_font(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in {".ttf", ".otf", ".ttc"}:
        raise HTTPException(400, f"不支持的字体格式 {ext}（支持 ttf/otf/ttc）")
    tmp = os.path.join(DATA, f"tmp_font{ext}")
    with open(tmp, "wb") as f:
        shutil.copyfileobj(file.file, f)
    try:
        asset = fonts.add(tmp)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        if os.path.isfile(tmp):
            os.remove(tmp)
    return asset.to_dict()


class CheckTextIn(BaseModel):
    font_id: str
    text: str


@app.post("/api/fonts/check")
def api_font_check(body: CheckTextIn):
    font = fonts.get(body.font_id)
    if font is None:
        raise HTTPException(404, "字体不存在")
    missing = font.covers(body.text)
    return {"missing": sorted(missing), "has_fallback": fonts.fallback is not None}


# ---------------- 渲染 / 导出 API ----------------
class RenderIn(BaseModel):
    template_id: str
    font_id: str
    text: str
    params: dict = Field(default_factory=dict)   # RenderParams 字段
    page: int = 0                                 # 预览页码（0-based）
    scale: float = 1.0                            # 预览渲染分辨率比例（<1 快速预览）
    save_path: str = ""                           # 非空 = 桌面版“另存为”直存该路径


# 简单生成缓存：翻页时同一输入直接取缓存页，秒切
_GEN_CACHE: dict[str, object] = {}
_GEN_CACHE_MAX = 4


def _generate_cached(body: RenderIn):
    import hashlib
    tpl = load_template(body.template_id)
    # 缓存键包含模板完整内容：调整/重定位/重命名后自动失效，不再命中旧纸
    key = hashlib.sha1(json.dumps({
        "t": body.template_id, "tpl": tpl.to_dict(), "f": body.font_id,
        "x": body.text, "p": body.params, "s": round(body.scale, 3),
    }, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if key in _GEN_CACHE:
        return _GEN_CACHE[key]
    font = fonts.get(body.font_id)
    if font is None:
        raise HTTPException(404, "字体不存在")
    try:
        params = RenderParams.from_dict(body.params)
    except Exception as e:
        raise HTTPException(400, f"渲染参数不合法: {e}")
    gen = generate_pages(tpl, font, fonts.fallback, body.text, params,
                         render_scale=body.scale)
    if len(_GEN_CACHE) >= _GEN_CACHE_MAX:
        _GEN_CACHE.pop(next(iter(_GEN_CACHE)))
    _GEN_CACHE[key] = gen
    return gen


def _resolve(body: RenderIn):
    tpl = load_template(body.template_id)
    font = fonts.get(body.font_id)
    if font is None:
        raise HTTPException(404, "字体不存在")
    try:
        params = RenderParams.from_dict(body.params)
    except Exception as e:
        raise HTTPException(400, f"渲染参数不合法: {e}")
    return tpl, font, params


@app.post("/api/render/preview")
def api_render_preview(body: RenderIn):
    gen = _generate_cached(body)
    if not gen.pages:
        raise HTTPException(400, "没有可渲染的内容")
    page = max(0, min(body.page, len(gen.pages) - 1))
    buf = io.BytesIO()
    gen.pages[page].save(buf, format="PNG")
    info = gen.layout.to_dict()
    info["total_pages"] = len(gen.pages)
    info["page"] = page
    return Response(buf.getvalue(), media_type="image/png",
                    headers={"X-Mofang-Info": json.dumps(info, ensure_ascii=False)})


@app.post("/api/export/pdf")
def api_export_pdf(body: RenderIn):
    gen = _generate_cached(body)
    tpl = load_template(body.template_id)
    if body.save_path:
        export_pdf(gen.pages, body.save_path, (tpl.physical.width_mm, tpl.physical.height_mm))
        return {"ok": True, "path": body.save_path,
                "info": gen.layout.to_dict()}
    out = os.path.join(OUT_DIR, f"mofang_{secrets.token_hex(3)}.pdf")
    export_pdf(gen.pages, out, (tpl.physical.width_mm, tpl.physical.height_mm))
    info = json.dumps(gen.layout.to_dict(), ensure_ascii=False)
    return FileResponse(out, media_type="application/pdf", filename="mofang.pdf",
                        headers={"X-Mofang-Info": info})


@app.post("/api/export/png")
def api_export_png(body: RenderIn):
    """导出全部页面为 zip（每页一个 PNG：mofang_p01.png ...）。"""
    import zipfile
    gen = _generate_cached(body)
    info = json.dumps(gen.layout.to_dict(), ensure_ascii=False)

    def png_zip() -> io.BytesIO:
        z = io.BytesIO()
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
            for i, pg in enumerate(gen.pages, 1):
                b = io.BytesIO()
                pg.save(b, format="PNG")
                zf.writestr(f"mofang_p{i:02d}.png", b.getvalue())
        z.seek(0)
        return z

    if body.save_path:
        z = png_zip()
        with open(body.save_path, "wb") as f:
            f.write(z.getvalue())
        return {"ok": True, "path": body.save_path, "pages": len(gen.pages),
                "info": gen.layout.to_dict()}
    z = png_zip()
    return Response(z.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": "attachment; filename=mofang_png.zip",
                             "X-Mofang-Info": info})


# ---------------- 预设 API ----------------
class PresetIn(BaseModel):
    name: str
    template_id: str = ""
    font_id: str = ""
    params: dict = Field(default_factory=dict)


@app.get("/api/presets")
def api_presets():
    return presets.list()


@app.post("/api/presets")
def api_save_preset(body: PresetIn):
    presets.save(body.name, {"template_id": body.template_id,
                             "font_id": body.font_id, "params": body.params})
    return {"ok": True}


@app.get("/api/presets/{name}")
def api_load_preset(name: str):
    try:
        return presets.load(name)
    except FileNotFoundError:
        raise HTTPException(404, "预设不存在")


@app.delete("/api/presets/{name}")
def api_delete_preset(name: str):
    if not presets.delete(name):
        raise HTTPException(404, "预设不存在")
    return {"ok": True}
