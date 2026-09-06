<div align="center">

# 墨仿 Mofang · 手写模拟打印工具

把打印体变成自然手写的本地工具。

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.1x-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Platform](https://img.shields.io/badge/Platform-Windows-blue)]()
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

![效果总览](docs/img/效果图.png)

![预览工作区](docs/img/预览.png)

</div>

---

## ✨ 核心特性

- **视觉自动定位**：上传稿纸照片，投影剖面法自动检测横线与书写区边界（~0.3s）；**倾斜照片自动纠斜**——文字沿倾斜横线书写，导出仍为原角度。
- **行线来源可切换**：贴合检测线（逐行贴合真实横线，拍照件行距不均也能精确对齐）/ 均匀生成（上下边界 + 行数等距造线，检测不准时手工对齐）。
- **流式中文排版**：避头尾（行首标点挤入上一行末格）、破折号/省略号占两格、自动分页；每行字数由字号 × 字水平间距自动决定，行与行可以不同；英文/URL 按字体实测宽度整词排版。
- **手写感模拟**：水平/竖直笔画位移、笔画旋转、字号浮动、墨色浓淡、行基线起伏、笔画加粗、字底贴近横线——全部可调、固定种子可复现，"换一版"一键重随机。
- **实时预览**：拖动参数即时刷新低清预览（~0.1s），松手自动全分辨率精修；多页 ◀▶ 翻页。
- **打印对齐**：导出 PDF 页面物理尺寸=模板尺寸，打印选"实际大小/100%"即可与实体稿纸对齐；PNG 亦可。
- **双端一致**：网页版（浏览器）与桌面版（pywebview 原生窗口）内嵌同一前端，功能 100% 一致；模板/字体/预设互通。
- **预设系统**：参数 + 模板 + 字体组合一键保存/载入，双端通用。

## 🧱 技术栈

| 层 | 技术 |
|---|---|
| 核心引擎 | Python 3.11 · Pillow（逐字瓦片旋转合成）· fontTools（缺字检测）· NumPy（视觉定位） |
| 排版 | 自研半格粒度排版引擎（避头尾禁则 / 流式字数 / 实测宽度分配） |
| 网页版 | FastAPI + Uvicorn + 原生 HTML/CSS/JS（零构建，Canvas 标注器） |
| 桌面版 | pywebview（WebView2）原生窗口内嵌网页版前端 |
| 导出 | img2pdf（无损嵌入，物理尺寸精确） |
| 打包 | PyInstaller + GitHub Actions（tag 自动构建发布） |

---

## 📁 项目结构

```
Mofang/
├── core/                  # 共享核心引擎（无 UI 依赖）
│   ├── template.py        #   模板模型（row_lines 行基线 / rotation_deg 纠斜角）
│   ├── detect.py          #   视觉定位：投影剖面检测横线/边界 + 自动纠斜
│   ├── layout.py          #   半格粒度排版（避头尾、流式字数、实测宽度分配）
│   ├── render.py          #   手写感渲染（逐行自适应字号、基线保护抖动）
│   ├── exporter.py        #   PNG / 打印对齐 PDF
│   ├── preset.py          #   预设（双端通用）
│   ├── region.py          #   四角点选 → 格网换算（手动兜底）
│   ├── paths.py           #   数据目录解析（源码/打包统一）
│   └── pipeline.py        #   端到端流水线
├── server/                # 网页版
│   ├── app.py             #   FastAPI：REST API + 静态资源
│   └── web/               #   前端（原生 HTML/CSS/JS，三步向导）
├── desktop/               # 桌面版（pywebview 薄壳：进程内 uvicorn + 原生窗口 + 应用图标）
├── data/                  # 运行时数据（模板/字体/预设/输出）
├── docs/                  # 用户文档 / 开发文档 / API 文档
└── tests/                 # 冒烟测试
```

详细设计见 [docs/开发文档.md](docs/开发文档.md)。

---

## 🚀 快速开始

### 环境要求

| 使用方式 | 需要 Python？ |
|---|---|
| 下载 [Releases](https://github.com/gstaryu/Mofang/releases) 中的桌面版 exe | ❌ 不需要，解压即用 |
| 网页版 / 桌面版 bat / 源码运行 | ✅ 需要（Windows 10/11 + [Miniconda](https://docs.conda.io/en/latest/miniconda.html) 或 Python 3.10+） |

另外需要手写字体文件（.ttf/.otf/.ttc，用任意字体制作工具生成）。

### 方式一：网页版（推荐）

双击 `start.bat`——自动创建 conda 环境 `mofang` 并安装依赖，完成后浏览器自动打开 `http://127.0.0.1:8642/`。

### 方式二：桌面版（免 Python）

直接下载 [Releases](https://github.com/gstaryu/Mofang/releases) 中的免安装 zip，解压运行 `Mofang.exe`——无需安装 Python/conda。

### 方式三：桌面版（脚本运行，需 Python）

先运行一次 `start.bat` 完成初始化，之后双击 `桌面版.bat`。

### 方式四：命令行

```bash
conda create -n mofang python=3.11 -y
conda activate mofang
pip install -r requirements.txt

python -m uvicorn server.app:app --port 8642   # 网页版
python desktop/main.py                         # 桌面版（pywebview 窗口）
```

---

## 🖨 使用流程

**三步向导**：模板 → 字体 → 编辑 · 预览 · 导出（后两步同一工作页）

| 步骤 | 说明 |
|---|---|
| 1️⃣ 模板 | 上传稿纸照片 → 自动视觉定位 + 纠斜 → 微调（行线来源/四边界/行数/跳过首线）→ 下一步自动保存 |
| 2️⃣ 字体 | 导入手写字体（缺字自动用系统字体顶替并提示清单） |
| 3️⃣ 编辑 · 预览 · 导出 | 输入文字、拖动参数实时预览、多页翻页、导出 PDF/PNG |

> 🖨 **打印对齐**：导出 PDF 后打印时选择 **"实际大小 / 100%"**，即可与实体稿纸对齐。

完整参数说明与截图见 [docs/用户文档.md](docs/用户文档.md)。

---

## 🏷 版本发布

推送 tag 自动构建 Windows 免安装包并发布到 Release：

```bash
git tag v0.1.0
git push origin v0.1.0
```

---

## 📚 文档索引

| 文档 | 内容 |
|---|---|
| [用户文档](docs/用户文档.md) | 安装、功能图文、参数说明、FAQ |
| [开发文档](docs/开发文档.md) | 项目结构、技术栈、核心设计、打包发布 |
| [API 文档](docs/API.md) | REST 接口说明 |

---

## ⚠️ 免责声明

本项目仅供学习交流。请勿用于提交作业、实验报告等需要真实手写的场合，使用本项目产生的一切后果由使用者自行承担。
