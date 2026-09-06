/* 墨仿 Mofang — 前端逻辑（向导式流程，与后端 REST API 交互） */
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  step: 1,
  templates: [],
  fonts: [],
  tplId: null,
  fontId: null,
  page: 0,              // 当前预览页（0-based）
  totalPages: 1,
  corners: [],          // 兼容保留
  annImage: null,       // 兼容保留
};

/* ---------------- 通用 ---------------- */
function toast(msg, isErr = false, ms = 3200) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("err", isErr);
  t.hidden = false;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => { t.hidden = true; }, ms);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    let msg = `请求失败 (${res.status})`;
    try { msg = (await res.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return res;
}

function fileName(p) { return p.replace(/\\/g, "/").split("/").pop(); }

/* ---------------- 步骤导航 ---------------- */
function gotoStep(n) {
  maybeAutoSaveAnnotator(n);   // 离开第 1 步时自动保存未保存的标注（异步，不阻塞导航）
  state.step = n;
  for (let i = 1; i <= 3; i++) {
    $(`panel-${i}`).hidden = i !== n;
    const btn = document.querySelector(`.step[data-step="${i}"]`);
    btn.classList.toggle("active", i === n);
    btn.classList.toggle("done", i < n);
  }
  document.body.dataset.step = n;
  if (n === 1) loadTemplates();
  if (annOnStepLoad[n]) annOnStepLoad[n]();
  window.scrollTo({ top: 0 });
}

document.querySelectorAll(".step").forEach(b =>
  b.addEventListener("click", () => gotoStep(+b.dataset.step)));
$("btnNext").addEventListener("click", () => gotoStep(Math.min(3, state.step + 1)));
$("btnPrev").addEventListener("click", () => gotoStep(Math.max(1, state.step - 1)));
const annOnStepLoad = { 3: () => { updateCapacity(); refreshPresets(); updateParamAvailability(); } };

/* 离开第 1 步时：标注器里若有未保存的标注，自动保存为模板并选中
   （“模板不一定要保存才能用”——保存按钮保留，但不再是必经步骤） */
async function maybeAutoSaveAnnotator(targetStep) {
  if (state.step === 1 && targetStep !== 1 &&
      !$("annotator").hidden && ann.img && ann.lines.length) {
    const tpl = await saveAnnotatorTemplate(true);
    if (tpl) {
      updateParamAvailability();
      toast(`新模板「${tpl.name}」已自动保存并选中，点「生成预览」即可使用`);
    }
  }
}

/* ---------------- 步骤 1：模板 ---------------- */
async function loadTemplates() {
  try {
    state.templates = await (await api("/api/templates")).json();
    const grid = $("tplGrid");
    grid.innerHTML = "";
    for (const t of state.templates) {
      const card = document.createElement("div");
      card.className = "tpl-card" + (t.id === state.tplId ? " selected" : "");
      card.setAttribute("role", "listitem");
      const imgName = fileName(t.image_path);
      card.innerHTML = `
        <img src="/files/templates/${encodeURIComponent(imgName)}" alt="${t.name} 缩略图" loading="lazy">
        <span class="name">${t.name}</span>
        <button class="tpl-del" title="删除模板" aria-label="删除模板 ${t.name}">✕</button>
        <button class="tpl-adjust" title="微调书写区域" aria-label="微调模板 ${t.name}">调整</button>`;
      card.addEventListener("click", (e) => {
        if (e.target.classList.contains("tpl-del")) return;
        if (e.target.classList.contains("tpl-adjust")) return;
        state.tplId = t.id;
        document.querySelectorAll(".tpl-card").forEach(c => c.classList.remove("selected"));
        card.classList.add("selected");
        localStorage.setItem("mofang.tplId", t.id);
        updateParamAvailability();
      });
      card.querySelector(".tpl-adjust").addEventListener("click", () => openAdjustor(t));
      card.querySelector(".name").addEventListener("dblclick", async (e) => {
        e.stopPropagation();
        const newName = prompt("重命名模板：", t.name);
        if (newName === null || newName.trim() === "" || newName.trim() === t.name) return;
        try {
          await api("/api/templates", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              name: newName.trim(), image_file: fileName(t.image_path),
              area: t.area, width_mm: t.physical.width_mm, height_mm: t.physical.height_mm,
              note: t.note || "", row_lines: t.row_lines || [],
              template_id: t.id,
            }),
          });
          if (state.tplId === t.id) { /* id 不变，引用仍有效 */ }
          loadTemplates();
          toast(`模板已重命名为「${newName.trim()}」`);
        } catch (err) { toast(err.message, true); }
      });
      card.querySelector(".tpl-del").addEventListener("click", async () => {
        if (!confirm(`确定删除模板「${t.name}」？`)) return;
        await api(`/api/templates/${t.id}`, { method: "DELETE" });
        if (state.tplId === t.id) state.tplId = null;
        loadTemplates();
        toast("模板已删除");
      });
      grid.appendChild(card);
    }
    if (!state.templates.length)
      grid.innerHTML = `<p class="hint">还没有模板 — 上传一张稿纸照片开始。</p>`;
  } catch (e) { toast(e.message, true); }
}

$("tplUpload").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const fd = new FormData();
    fd.append("file", file);
    const up = await (await api("/api/templates/upload", { method: "POST", body: fd })).json();
    openAnnotator(up);
  } catch (err) { toast(err.message, true); }
  e.target.value = "";
});

/* ---------- 标注器：自动检测 + 微调 / 手动四角兜底 ---------- */
const ann = {
  img: null, file: null, scale: 1,
  mode: "auto",                    // auto | manual
  detect: null,                    // 原始检测结果
  lines: [],                       // 当前生效的书写基线（可能已跳过首线/截断）
  xL: 0, xR: 0, pitch: 150,
  corners: [],                     // 手动四角
  lineMode: "detected",            // detected=贴合检测线 | uniform=均匀生成
  rotation: 0,                     // 自动纠斜角（度）
  imgW: 0, imgH: 0,
};

function openAnnotator(up) {
  $("annotator").hidden = false;
  ann.file = up.image_file;
  ann.editingId = null;     // 上传 = 新模板；防止残留的“调整”上下文覆盖已有模板
  ann.lines = [];
  ann.corners = [];
  ann.detect = null;
  const img = new Image();
  img.onload = () => {
    ann.img = img; ann.imgW = up.width; ann.imgH = up.height;
    $("annName").value = "";
    autoDetect();
  };
  img.onerror = () => toast("图片加载失败", true);
  img.src = up.url;
  $("annotator").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function autoDetect() {
  ann.mode = "auto";
  $("annDetectMsg").textContent = "视觉定位中…";
  try {
    const res = await (await api("/api/templates/detect", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_file: ann.file, skip_first_line: false }),
    })).json();
    ann.detect = res.detect;
    ann.rotation = res.detect.rotation_deg || 0;
    if (Math.abs(ann.rotation) >= 0.3) {
      // 显示纠斜后的图（行基线在摆正坐标系里）；输出渲染会转回原角度
      const deskewUrl = "/files/templates/" + encodeURIComponent(ann.file) + ".deskew" + Math.round(ann.rotation * 10) + ".png";
      const dimg = new Image();
      dimg.onload = () => { ann.img = dimg; ann.imgW = dimg.naturalWidth; ann.imgH = dimg.naturalHeight; drawAnnotator(); };
      dimg.src = deskewUrl;
      toast(`已自动纠正 ${ann.rotation}° 倾斜（预览显示摆正后的图，导出为原角度）`);
    }
    if (res.detect.ok) {
      ann.lines = [...res.detect.row_lines];
      ann.xL = res.detect.x_left;
      ann.xR = res.detect.x_right;
      ann.pitch = res.detect.pitch;
      rebuildAnn();   // 立即应用“跳过第一条线”等选项，保持行数一致
      $("annDetectMsg").textContent = "✓ " + res.detect.message + "（可微调）";
      $("annModeTip").textContent = "自动检测成功：行基线逐行贴合真实横线";
    } else {
      $("annDetectMsg").textContent = "⚠ " + res.detect.message;
      switchToManual(true);
      return;
    }
  } catch (e) {
    $("annDetectMsg").textContent = "检测失败：" + e.message;
    switchToManual(true);
    return;
  }
  syncAnnInputs();
  drawAnnotator();
}

function switchToManual(silent) {
  ann.mode = "manual";
  ann.lines = [];
  ann.corners = [];
  $("annModeTip").textContent = "手动模式：依次点击 4 个角（左上→右上→右下→左下）";
  if (!silent) toast("已切换到手动四角模式");
  drawAnnotator();
}

/* 依据控件状态重建生效基线与列数 */
function rebuildAnn() {
  const skipFirst = $("annSkipFirst").checked;
  const top = +$("annTop").value || 0;
  const bottom = +$("annBottom").value || 0;
  const rowsN = +$("annRows").value || 0;   // 0 = 自动（按行距铺满上下边界）
  ann.xL = +$("annXl").value || ann.xL;
  ann.xR = +$("annXr").value || ann.xR;
  ann.pitch = +$("annPitch").value || ann.pitch;
  if (ann.lineMode === "uniform") {
    // 均匀生成：上下边界间等距造线（检测不准时的手工对齐模式）
    const y0 = top > 0 ? top : ann.corners[0]?.[1] ?? 400;
    const y1 = bottom > 0 ? bottom : y0 + (rowsN - 1) * ann.pitch;
    const n = rowsN || Math.max(1, Math.round((y1 - y0) / ann.pitch) + 1);
    const lines = [];
    for (let i = 0; i < n; i++) lines.push(Math.round(y0 + (y1 - y0) * (n === 1 ? 0 : i / (n - 1))));
    // 均匀模式：上边界即第一行书写基线，跳过首线不适用（该勾选框自动禁用）
    ann.lines = lines;
    $("annCols") && (ann.cols = Math.max(1, Math.round((ann.xR - ann.xL) / (ann.pitch * 1.02))));
    return;
  }
  if (ann.mode === "auto" && ann.detect && ann.detect.ok) {
    let lines = [...ann.detect.row_lines];
    if (skipFirst && lines.length >= 2) lines = lines.slice(1);
    if (top > 0) {
      lines = lines.filter(l => l >= top - 3);
      if (lines.length && lines[0] < top + 3) lines[0] = top;      // 吸附到上边界
    }
    if (bottom > 0) {
      lines = lines.filter(l => l <= bottom + 3);
      if (lines.length && lines[lines.length - 1] > bottom - 3) lines[lines.length - 1] = bottom;  // 吸附到下边界
    }
    const rowsCap = +$("annRows").value || lines.length;
    ann.lines = lines.slice(0, Math.max(1, rowsCap));
  } else if (ann.mode === "manual" && ann.corners.length === 4) {
    const lines = [];
    const y0 = top > 0 ? top : ann.corners[0][1] + ann.pitch * 0.7;
    const y1 = bottom > 0 ? bottom : ann.corners[3][1] - ann.pitch * 0.3;
    for (let y = y0; y <= y1; y += ann.pitch) lines.push(Math.round(y));
    let ls = lines;
    if (skipFirst && ls.length >= 2) ls = ls.slice(1);
    const rowsCap = +$("annRows").value || ls.length;
    ann.lines = ls.slice(0, Math.max(1, rowsCap));
  }
  const cols = Math.max(1, Math.round((ann.xR - ann.xL) / (ann.pitch * 1.02)));
  ann.cols = cols;            // 仅作为书写区宽度基准存入模板，渲染时每行字数自动流动
}

function syncAnnInputs() {
  $("annXl").value = Math.round(ann.xL);
  $("annXr").value = Math.round(ann.xR);
  $("annPitch").value = Math.round(ann.pitch);
  if (ann.lines.length) {
    $("annTop").value = Math.round(ann.lines[0]);
    $("annBottom").value = Math.round(ann.lines[ann.lines.length - 1]);
  }
  $("annRows").value = ann.lines.length || 20;
}

function drawAnnotator() {
  if (!ann.img) return;
  const canvas = $("annotCanvas");
  const maxW = Math.min(620, window.innerWidth - 400);
  const maxH = window.innerHeight - 210;      // 与左侧参数区同高，一屏放下
  const scale = Math.min(1, maxW / ann.imgW, Math.max(0.1, maxH / ann.imgH));
  ann.scale = scale;
  canvas.width = ann.imgW * scale;
  canvas.height = ann.imgH * scale;
  const ctx = canvas.getContext("2d");
  ctx.drawImage(ann.img, 0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "rgba(176,58,46,.8)"; ctx.lineWidth = 1.2;

  // 手动模式：角点
  ann.corners.forEach((p, i) => {
    ctx.fillStyle = "#b03a2e";
    ctx.beginPath(); ctx.arc(p[0] * scale, p[1] * scale, 6, 0, 7); ctx.fill();
    ctx.fillStyle = "#2f2a26"; ctx.font = "13px sans-serif";
    ctx.fillText(["左上", "右上", "右下", "左下"][i], p[0] * scale + 9, p[1] * scale - 6);
  });

  // 行带 + 左右边界
  rebuildAnn();
  if (ann.lines.length) {
    ann.lines.forEach(y => {
      ctx.strokeRect(ann.xL * scale, (y - ann.pitch) * scale,
                     (ann.xR - ann.xL) * scale, ann.pitch * scale);
    });
    ctx.strokeStyle = "rgba(176,58,46,.45)";
    ctx.beginPath();
    ctx.moveTo(ann.xL * scale, ann.lines[0] * scale - ann.pitch * scale);
    ctx.lineTo(ann.xL * scale, ann.lines[ann.lines.length - 1] * scale);
    ctx.moveTo(ann.xR * scale, ann.lines[0] * scale - ann.pitch * scale);
    ctx.lineTo(ann.xR * scale, ann.lines[ann.lines.length - 1] * scale);
    ctx.stroke();
  }
}

$("annotCanvas").addEventListener("click", (e) => {
  if (ann.mode !== "manual" || ann.corners.length >= 4) return;
  const rect = e.target.getBoundingClientRect();
  const sx = ann.imgW / rect.width;           // 显示宽 → 原图宽（后续绘制/边界都用原图坐标）
  const sy = ann.imgH / rect.height;
  ann.corners.push([(e.clientX - rect.left) * sx,
                    (e.clientY - rect.top) * sy]);
  if (ann.corners.length === 4) {
    const [tl, tr, , bl] = ann.corners;
    ann.xL = tl[0]; ann.xR = tr[0];
    ann.pitch = Math.max(10, Math.round((bl[1] - tl[1]) / 10));
    rebuildAnn();
    syncAnnInputs();
    toast("四角完成，已按行距推算基线，可继续微调");
  }
  drawAnnotator();
});

$("annAuto").addEventListener("click", autoDetect);
$("annManualBtn").addEventListener("click", () => switchToManual(false));
["annSkipFirst", "annTop", "annBottom", "annXl", "annXr", "annPitch"].forEach(id =>
  $(id).addEventListener("input", () => {
    $("annRows").value = 0;                  // 解除行数上限：边界/首线变化后重新取全量
    rebuildAnn(); drawAnnotator();
    $("annRows").value = ann.lines.length;   // 行数默认跟随检测/边界结果
  }));
$("annRows").addEventListener("input", () => { rebuildAnn(); drawAnnotator(); });
document.querySelectorAll('input[name="annLineMode"]').forEach(r =>
  r.addEventListener("change", () => {
    ann.lineMode = r.value;
    $("annSkipFirst").disabled = (r.value === "uniform");
    $("annSkipFirst").closest(".field-check").style.opacity = (r.value === "uniform") ? ".45" : "1";
    if (r.value === "uniform") {
      // 用当前首末行作为初始上下边界，行数保持
      if (ann.lines.length) {
        $("annTop").value = Math.round(ann.lines[0]);
        $("annBottom").value = Math.round(ann.lines[ann.lines.length - 1]);
      }
      toast("均匀生成模式：调整上/下边界与行数即可手工对齐行线");
    }
    rebuildAnn(); drawAnnotator();
  }));

$("annSave").addEventListener("click", () => saveAnnotatorTemplate(false));

async function saveAnnotatorTemplate(isAuto) {
  if (!ann.img) return null;
  rebuildAnn();
  if (!ann.lines.length) {
    if (!isAuto) toast("暂无可用基线：请先自动检测或手动四角", true);
    return null;
  }
  const cols = ann.cols || Math.max(1, Math.round((ann.xR - ann.xL) / (ann.pitch * 1.02)));
  const pitch = ann.pitch;
  const name = $("annName").value.trim() || "未命名模板";
  try {
    const tpl = await (await api("/api/templates", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name, image_file: ann.file,
        area: {
          x: ann.xL, y: ann.lines[0] - pitch,
          cell_w: (ann.xR - ann.xL) / cols, cell_h: pitch,
          cols, rows: ann.lines.length, col_gap: 0, row_gap: 0,
        },
        width_mm: +$("annW").value, height_mm: +$("annH").value,
        row_lines: ann.lines,
        rotation_deg: ann.rotation || 0,
        template_id: ann.editingId || "",
      }),
    })).json();
    state.tplId = tpl.id;
    localStorage.setItem("mofang.tplId", tpl.id);
    state.templates = await (await api("/api/templates")).json();  // 刷新缓存供 currentTemplate() 使用
    if (!isAuto) {
      toast(`模板「${name}」已${ann.editingId ? "更新" : "保存"}（${ann.lines.length} 行 × ${cols} 格，${ann.mode === "auto" ? "逐行贴合" : "等距格网"}）`);
      ann.editingId = null;
      $("annotator").hidden = true;
      loadTemplates();
    }
    return tpl;
  } catch (e) {
    toast(e.message, true);
    return null;
  }
}

/* 微调已有模板：载入其当前参数进入标注器，保存原地更新 */
async function openAdjustor(t) {
  $("annotator").hidden = false;
  ann.editingId = t.id;
  ann.file = fileName(t.image_path);
  ann.corners = [];
  const img = new Image();
  img.onload = async () => {
    ann.img = img; ann.imgW = img.naturalWidth; ann.imgH = img.naturalHeight;
    $("annName").value = t.name;
    // 先重新检测作为基准，再叠加模板已保存的定制值
    try {
      const res = await (await api("/api/templates/detect", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_file: ann.file, skip_first_line: false }),
      })).json();
      ann.detect = res.detect;
      ann.mode = "auto";
      if (res.detect.ok) {
        ann.xL = res.detect.x_left; ann.xR = res.detect.x_right; ann.pitch = res.detect.pitch;
      }
    } catch (_) {}
    // 模板自带 row_lines / 边界时以其为准（用户此前微调过的结果）
    const tl = t.row_lines || [];
    if (tl.length) {
      ann.rotation = t.rotation_deg || 0;
      ann.lines = [...tl];
      ann.detect = ann.detect && ann.detect.ok
        ? { ...ann.detect, row_lines: [...tl, ann.detect.row_lines[ann.detect.row_lines.length - 1]] }
        : { ok: true, row_lines: [...tl] };
      ann.xL = t.area.x; ann.xR = t.area.x + t.area.cols * (t.area.cell_w + t.area.col_gap);
      ann.pitch = t.area.cell_h;
      $("annSkipFirst").checked = false;
      $("annModeTip").textContent = "微调模式：显示的是该模板已保存的行定位";
    }
    if (!ann.lines.length && ann.detect && ann.detect.ok) {
      ann.lines = [...ann.detect.row_lines];
      $("annSkipFirst").checked = true;
    }
    syncAnnInputs();
    drawAnnotator();
  };
  img.onerror = () => toast("模板图片加载失败", true);
  const rot = t.rotation_deg || 0;
  img.src = Math.abs(rot) >= 0.3
    ? "/files/templates/" + encodeURIComponent(ann.file) + ".deskew" + Math.round(rot * 10) + ".png"
    : `/files/templates/${encodeURIComponent(ann.file)}`;
  $("annotator").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/* 参数可用性：全部参数恒可调（贴合横线的模板上调大行距/波浪=故意偏离，见各自提示） */
function updateParamAvailability() { /* 保持空实现以兼容调用点 */ }

/* ---------------- 步骤 2：字体 ---------------- */
async function loadFonts() {
  try {
    const data = await (await api("/api/fonts")).json();
    state.fonts = data.fonts;
    $("fontHint").textContent = data.broken.length
      ? `⚠ 损坏的字体文件：${data.broken.join("、")}` : "";
    const grid = $("fontGrid");
    grid.innerHTML = "";
    for (const f of data.fonts) {
      const card = document.createElement("div");
      card.className = "font-card" + (f.id === state.fontId ? " selected" : "");
      card.setAttribute("role", "listitem");
      card.innerHTML = `<div class="sample" style="font-family:'F-${f.id}'">永字八法</div><span class="name">${f.name}</span>`;
      grid.appendChild(card);
      // 用 FontFace 动态加载字体做预览
      const face = new FontFace(`F-${f.id}`, `url(/files/fonts/${encodeURIComponent(fileName(f.path))})`);
      face.load().then(loaded => {
        document.fonts.add(loaded);
      }).catch(() => { card.querySelector(".sample").textContent = "（预览失败）"; });
      card.addEventListener("click", () => {
        state.fontId = f.id;
        document.querySelectorAll(".font-card").forEach(c => c.classList.remove("selected"));
        card.classList.add("selected");
        localStorage.setItem("mofang.fontId", f.id);
      });
    }
    if (!data.fonts.length)
      grid.innerHTML = `<p class="hint">字体目录为空 — 导入 .ttf/.otf 字体文件开始。</p>`;
  } catch (e) { toast(e.message, true); }
}

$("fontUpload").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  try {
    const fd = new FormData();
    fd.append("file", file);
    const f = await (await api("/api/fonts/upload", { method: "POST", body: fd })).json();
    toast(`字体「${f.name}」已导入（${f.glyph_count} 个字形）`);
    state.fontId = f.id;
    loadFonts();
  } catch (err) { toast(err.message, true); }
  e.target.value = "";
});

/* ---------------- 步骤 3：文字与参数 ---------------- */
const paramIds = ["pSize", "pBold", "pH", "pV", "pRot", "pInk", "pWave", "pColGap", "pRowGap", "pBase"];
const outMap = {
  pSize: ["oSize", v => (+v).toFixed(2)],
  pBold: ["oBold", v => `${Math.round(+v)}`],
  pH: ["oH", v => (+v).toFixed(2)],
  pV: ["oV", v => (+v).toFixed(2)],
  pRot: ["oRot", v => `${(+v).toFixed(1)}°`],
  pInk: ["oInk", v => (+v).toFixed(2)],
  pWave: ["oWave", v => (+v).toFixed(2)],
  pColGap: ["oColGap", v => (+v).toFixed(2)],
  pRowGap: ["oRowGap", v => (+v).toFixed(2)],
  pBase: ["oBase", v => (+v).toFixed(2)],
};
paramIds.forEach(id => {
  $(id).addEventListener("input", () => {
    const [outId, fmt] = outMap[id];
    $(outId).textContent = fmt($(id).value);
    updateCapacity();
    livePreviewSoon();
  });
  $(id).addEventListener("change", fullPreviewSoon);
});
["pR", "pG", "pB"].forEach(id => {
  $(id).addEventListener("input", () => { updateSwatch(); livePreviewSoon(); });
  $(id).addEventListener("change", fullPreviewSoon);
});
function updateSwatch() {
  $("inkSwatch").style.background = `rgb(${$("pR").value},${$("pG").value},${$("pB").value})`;
}
updateSwatch();

function collectParams() {
  return {
    font_scale: +$("pSize").value,
    text_rgb: [+$("pR").value, +$("pG").value, +$("pB").value],
    h_jitter: +$("pH").value,
    v_jitter: +$("pV").value,
    rotation: +$("pRot").value,
    size_jitter: 0.05,
    ink_jitter: +$("pInk").value,
    baseline_wave: +$("pWave").value,
    stroke_bold: +$("pBold").value,
    extra_col_gap: +$("pColGap").value,
    extra_row_gap: +$("pRowGap").value,
    baseline_shift: +$("pBase").value,
    seed: +(state._seed || 42),
  };
}
function applyParams(p) {
  const set = (id, v, fmt) => { $(id).value = v; };
  $("pSize").value = p.font_scale; $("oSize").textContent = (+p.font_scale).toFixed(2);
  $("pBold").value = p.stroke_bold ?? 1; $("oBold").textContent = Math.round(+(p.stroke_bold ?? 1));
  $("pH").value = p.h_jitter; $("oH").textContent = (+p.h_jitter).toFixed(2);
  $("pV").value = p.v_jitter; $("oV").textContent = (+p.v_jitter).toFixed(2);
  $("pRot").value = p.rotation; $("oRot").textContent = (+p.rotation).toFixed(1) + "°";
  $("pInk").value = p.ink_jitter; $("oInk").textContent = (+p.ink_jitter).toFixed(2);
  $("pWave").value = p.baseline_wave; $("oWave").textContent = (+p.baseline_wave).toFixed(2);
  $("pColGap").value = p.extra_col_gap ?? 0; $("oColGap").textContent = (+(p.extra_col_gap ?? 0)).toFixed(2);
  $("pRowGap").value = p.extra_row_gap ?? 0; $("oRowGap").textContent = (+(p.extra_row_gap ?? 0)).toFixed(2);
  $("pBase").value = p.baseline_shift ?? 0; $("oBase").textContent = (+(p.baseline_shift ?? 0)).toFixed(2);
  if (Array.isArray(p.text_rgb)) {
    $("pR").value = p.text_rgb[0]; $("pG").value = p.text_rgb[1]; $("pB").value = p.text_rgb[2];
  }
  updateSwatch();
}

function currentTemplate() { return state.templates.find(t => t.id === state.tplId); }

function updateCapacity() {
  const t = currentTemplate();
  const info = $("capacityInfo");
  if (!t) { info.textContent = "⚠ 尚未选择模板（第 1 步）"; info.className = "capacity over"; return; }
  const cap = t.area.rows * t.area.cols;
  const text = $("textInput").value;
  const approx = [...text].filter(c => !/\s/.test(c)).length;
  const pages = Math.ceil(approx / cap) || 0;
  info.textContent = `每页 ${t.area.cols}×${t.area.rows}=${cap} 格 · 当前约 ${approx} 字 · 约 ${pages} 页`;
  info.className = "capacity" + (approx > cap * 50 ? " over" : "");
}
$("textInput").addEventListener("input", updateCapacity);

/* ---------------- 预设 ---------------- */
async function refreshPresets() {
  try {
    const list = await (await api("/api/presets")).json();
    const sel = $("presetList");
    sel.innerHTML = `<option value="">— 载入预设 —</option>` +
      list.map(p => `<option value="${encodeURIComponent(p.name)}">${p.name}</option>`).join("");
  } catch (_) {}
}
$("presetSave").addEventListener("click", async () => {
  const name = $("presetName").value.trim();
  if (!name) { toast("请输入预设名称", true); return; }
  try {
    await api("/api/presets", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, template_id: state.tplId || "", font_id: state.fontId || "", params: collectParams() }),
    });
    toast(`预设「${name}」已保存`);
    $("presetName").value = "";
    refreshPresets();
  } catch (e) { toast(e.message, true); }
});
$("presetList").addEventListener("change", async (e) => {
  const name = e.target.value;
  if (!name) return;
  try {
    const p = await (await api(`/api/presets/${name}`)).json();
    if (p.template_id) { state.tplId = p.template_id; }
    if (p.font_id) { state.fontId = p.font_id; }
    applyParams(p.params || {});
    toast(`预设已载入（模板/字体选择也已恢复）`);
  } catch (err) { toast(err.message, true); }
});

/* ---------------- 预览（多页翻页 + 拖动实时低清预览） ---------------- */
let _previewSeq = 0;
async function renderPreview(resetPage = false, scale = 1) {
  if (!state.tplId) { toast("请先在第 1 步选择模板", true); gotoStep(1); return; }
  if (!state.fontId) { toast("请先在第 2 步选择字体", true); gotoStep(2); return; }
  const text = $("textInput").value.trim();
  if (!text) { toast("请先在第 3 步输入文字", true); gotoStep(3); return; }
  if (resetPage) state.page = 0;
  const seq = ++_previewSeq;
  const live = scale < 1;                       // 拖动中的快速预览
  if (!live) $("previewSpinner").hidden = false;
  if (!live) $("previewInfo").textContent = "渲染中…";
  try {
    const res = await api("/api/render/preview", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ template_id: state.tplId, font_id: state.fontId, text,
                             params: collectParams(), page: state.page, scale }),
    });
    if (seq !== _previewSeq) return;            // 已有更新请求，丢弃旧响应
    const blob = await res.blob();
    $("previewImg").src = URL.createObjectURL(blob);
    $("previewImg").hidden = false;
    $("previewEmpty").hidden = true;
    const info = JSON.parse(res.headers.get("X-Mofang-Info") || "{}");
    state.totalPages = info.total_pages || 1;
    updatePageNav();
    const t = currentTemplate();
    const bits = [`模板「${t ? t.name : state.tplId}」· 共 ${state.totalPages} 页`];
    if (info.overflow_chars > 0) bits.push(`⚠ 超出容量 ${info.overflow_chars} 格，超出部分未渲染`);
    $("previewInfo").textContent = bits.join(" · ");
    const mr = $("missingReport");
    if (info.missing && info.missing.missing_chars.length) {
      mr.hidden = false;
      mr.textContent = `缺字提示：${info.missing.summary}`;
    } else mr.hidden = true;
  } catch (e) {
    if (seq === _previewSeq) { toast(e.message, true); $("previewInfo").textContent = ""; }
  } finally {
    if (seq === _previewSeq) $("previewSpinner").hidden = true;
  }
}

/* 拖动滑块：防抖 180ms 发低清请求（0.22 倍）；松手（change）自动全分辨率精修 */
let _liveTimer = null;
function livePreviewSoon() {
  if (!state.tplId || !state.fontId || !$("previewImg").hidden === false) {
    // 尚未生成过预览时不自动渲染，避免一进页面就跑
  }
  if ($("previewImg").hidden) return;           // 还没生成过预览
  clearTimeout(_liveTimer);
  _liveTimer = setTimeout(() => renderPreview(false, 0.22), 180);
}
function fullPreviewSoon() {
  if ($("previewImg").hidden) return;
  clearTimeout(_liveTimer);
  _liveTimer = setTimeout(() => renderPreview(false, 1), 120);
}

function updatePageNav() {
  const n = state.totalPages || 1;
  const p = Math.min(state.page, n - 1);
  $("pageLabel").textContent = `第 ${p + 1} / ${n} 页`;
  $("btnPrevPage").disabled = p <= 0;
  $("btnNextPage").disabled = p >= n - 1;
}
$("btnPrevPage").addEventListener("click", () => {
  if (state.page > 0) { state.page--; renderPreview(); }
});
$("btnNextPage").addEventListener("click", () => {
  if (state.page < (state.totalPages || 1) - 1) { state.page++; renderPreview(); }
});
$("btnGenerate").addEventListener("click", () => renderPreview(true));
$("btnReroll").addEventListener("click", () => {
  state._seed = Math.floor(Math.random() * 1e9);
  renderPreview();
});

/* ---------------- 步骤 5：导出 ---------------- */
async function doExport(kind) {
  if (!state.tplId || !state.fontId) { toast("请先完成模板与字体选择", true); return; }
  const btn = kind === "pdf" ? $("btnExportPdf") : $("btnExportPng");
  btn.disabled = true;
  $("exportInfo").textContent = "导出中…";
  try {
    const desktop = window.pywebview && window.pywebview.api;
    let body = { template_id: state.tplId, font_id: state.fontId, text: $("textInput").value,
                 params: collectParams(), page: state.page };
    if (desktop) {
      // 桌面版：弹出“另存为”对话框，服务端直存选定路径
      const name = kind === "pdf" ? "mofang.pdf" : "mofang_png.zip";
      const types = kind === "pdf" ? "PDF 文件 (*.pdf)" : "ZIP 压缩包 (*.zip)";
      const savePath = await desktop.pick_save_path(name, types);
      if (!savePath) { $("exportInfo").textContent = ""; btn.disabled = false; return; }
      body.save_path = savePath;
    }
    const res = await api(`/api/export/${kind}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const infoHeader = res.headers.get("X-Mofang-Info");
    const info = JSON.parse(infoHeader || "{}");
    if (desktop) {
      const saved = (await res.json()).path;
      $("exportInfo").textContent = `已保存到：${saved}`;
      toast("导出完成");
    } else {
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = kind === "pdf" ? "mofang.pdf" : "mofang_png.zip";
      a.click();
      URL.revokeObjectURL(a.href);
      $("exportInfo").textContent = `已导出全部 ${info.page_count ?? 1} 页 PNG（zip）。打印请选择“实际大小/100%”。`
        + (info.overflow_chars > 0 ? `（注意：超出容量 ${info.overflow_chars} 格未渲染）` : "");
      toast("导出完成");
    }
  } catch (e) { toast(e.message, true); $("exportInfo").textContent = ""; }
  finally { btn.disabled = false; }
}
$("btnExportPdf").addEventListener("click", () => doExport("pdf"));
$("btnExportPng").addEventListener("click", () => doExport("png"));

/* ---------------- 初始化 ---------------- */
(async function init() {
  try {
    state.templates = await (await api("/api/templates")).json();
    const fontsData = await (await api("/api/fonts")).json();
    const savedTpl = localStorage.getItem("mofang.tplId");
    const savedFont = localStorage.getItem("mofang.fontId");
    if (savedTpl && state.templates.some(t => t.id === savedTpl)) state.tplId = savedTpl;
    if (savedFont && fontsData.fonts.some(f => f.id === savedFont)) state.fontId = savedFont;
  } catch (_) {}
  refreshPresets();
  gotoStep(1);
})();
