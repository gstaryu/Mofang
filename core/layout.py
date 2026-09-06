# -*- coding: utf-8 -*-
"""中文排版引擎：分词、避头尾、断行、分页。

粒度：内部以“半格”为最小单位（1 格 = 2 半格）。
- 全角字符占 2（1 格）；半角字母/数字占 1（0.5 格）；空格占 1（0.5 格）；
- 破折号“——”占 4（2 格）、省略号“……”占 4（不拆开）；
- 行首禁则：句末标点（，。！？等）不出现在行首 —— 挤入上一行末格；
- 行尾禁则：句首标点（“（【等）不出现在行尾 —— 移到下一行；
- 超长 ASCII 串（URL 等）按整行宽硬切。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 行首禁则（这些字符不能出现在一行/一页的开头）
LINE_START_FORBIDDEN = set(
    "，。、；：？！—…””』」）〉》】〕〗〙〛,.;:!?)]}%·ˇ´‘’"
    "″〃々﹔﹕﹖﹗．：；？！－–"
)
# 行尾禁则（这些字符不能出现在一行/一页的末尾）
LINE_END_FORBIDDEN = set("“‘『「（《〈【〔〖〘〚([{＄￥")


@dataclass
class Token:
    """一个排版单元。cells 单位 = 半格。"""

    text: str
    cells: int                # 占多少半格
    is_space: bool = False
    start_forbidden: bool = False
    end_forbidden: bool = False


@dataclass
class PlacedToken:
    """排版结果：一个已定位的字符。col 单位 = 半格。"""

    text: str
    row: int
    col: int                  # 半格列号（0,1,2,...；偶数为整格起点）
    cells: int
    squeezed: bool = False    # 是否挤入上一行末格（禁则处理）
    use_fallback: bool = False


@dataclass
class MissingGlyphReport:
    """缺字报告。"""

    missing_chars: list[str] = field(default_factory=list)
    fallback_used: list[str] = field(default_factory=list)
    has_fallback_font: bool = False

    @property
    def summary(self) -> str:
        if not self.missing_chars:
            return ""
        chars = " ".join(sorted(set(self.missing_chars)))
        tip = "已用系统备用字体顶替" if (self.fallback_used and self.has_fallback_font) \
            else "⚠ 未找到备用字体，将以空白占位"
        return f"主字体缺 {len(set(self.missing_chars))} 个字符：{chars}；{tip}"

    def to_dict(self) -> dict:
        return {
            "missing_chars": sorted(set(self.missing_chars)),
            "fallback_used": sorted(set(self.fallback_used)),
            "has_fallback_font": self.has_fallback_font,
            "summary": self.summary,
        }


@dataclass
class LayoutResult:
    pages: list[list[PlacedToken]]
    missing: MissingGlyphReport
    cells_per_page: int                  # 全格数（rows*cols）
    overflow_chars: int = 0              # 超出容量（全格数）

    def to_dict(self) -> dict:
        return {
            "page_count": len(self.pages),
            "cells_per_page": self.cells_per_page,
            "overflow_chars": self.overflow_chars,
            "missing": self.missing.to_dict(),
        }


class _Overflow(Exception):
    """内部信号：已到最后一页。"""


class LayoutEngine:
    """文本 → 逐页逐格的字符位置（半格粒度）。"""

    def tokenize(self, text: str) -> list[Token]:
        tokens: list[Token] = []
        i, n = 0, len(text)
        while i < n:
            ch = text[i]
            if ch == "\n":
                tokens.append(Token("\n", 0, is_space=True))
                i += 1
                continue
            if ch.isspace():
                tokens.append(Token(" ", 1, is_space=True))   # 空格 = 0.5 格
                i += 1
                continue
            if ch == "—" and i + 1 < n and text[i + 1] == "—":
                tokens.append(Token("——", 4, start_forbidden=True))
                i += 2
                continue
            if ch == "…" and i + 1 < n and text[i + 1] == "…":
                tokens.append(Token("……", 4, start_forbidden=True))
                i += 2
                continue
            if ord(ch) < 128:
                # 半角连续串（含标点），每个字符占 1 半格
                j = i
                while j < n and ord(text[j]) < 128 and not text[j].isspace() and text[j] != "\n":
                    j += 1
                run = text[i:j]
                start_forb = run[0] in LINE_START_FORBIDDEN
                tokens.append(Token(run, len(run), start_forbidden=start_forb))
                i = j
                continue
            tokens.append(Token(ch, 2,
                                start_forbidden=ch in LINE_START_FORBIDDEN,
                                end_forbidden=ch in LINE_END_FORBIDDEN))
            i += 1
        return tokens

    def layout(
        self,
        text: str,
        cols: int,
        rows: int,
        page_count: int,
        coverage_check=None,
        row_caps: list[int] | None = None,
        row_char_ws: list[float] | None = None,
        extra_col_gap: float = 0.0,
        ascii_measure=None,
    ) -> LayoutResult:
        """coverage_check: callable(char) -> True 表示主字体缺该字。

        row_caps（可选）：每行半格容量列表（流式排版）。
        ascii_measure + row_char_ws：英文/数字按字体实测宽度分配占格数
        （ascii_measure(s) 返回参考字号 100 下的像素宽度），词紧贴分配空间。
        """
        if page_count < 1:
            raise ValueError("页数必须 ≥ 1")
        if row_caps:
            rows = len(row_caps)
        if cols < 1 or rows < 1:
            raise ValueError("行列数必须 ≥ 1")
        cols_half = cols * 2
        capacity_half = sum(row_caps) if row_caps else cols_half * rows
        tokens = self.tokenize(text)
        report = MissingGlyphReport()

        pages: list[list[PlacedToken]] = [[]]
        page = pages[0]
        row, col = 0, 0   # col 为半格

        def new_line():
            nonlocal page, row, col
            row += 1
            col = 0
            if row_caps is not None:
                if row >= len(row_caps):
                    if len(pages) >= page_count:
                        raise _Overflow()
                    page = []
                    pages.append(page)
                    row = 0
            elif row >= rows:
                if len(pages) >= page_count:
                    raise _Overflow()
                page = []
                pages.append(page)
                row = 0

        def row_cap() -> int:
            """当前行半格容量（流式：随行变；等距：恒定）。"""
            if row_caps is not None:
                return row_caps[min(row, len(row_caps) - 1)]
            return cols_half

        placed_half = 0
        total_half = 0
        try:
            for tok in tokens:
                if tok.is_space and tok.text == "\n":
                    new_line()
                    continue
                total_half += tok.cells
                if total_half > page_count * capacity_half:
                    continue
                # 英文/数字串：按字体实测宽度分配占格数（词紧贴分配空间）
                if ascii_measure and tok.text and ord(tok.text[0]) < 256 and not tok.is_space:
                    r = min(row, (len(row_char_ws) - 1) if row_char_ws else 0)
                    cw = (row_char_ws[r] if row_char_ws else 20.0)
                    half_adv = max(1.0, cw / 2 * (1 + extra_col_gap))
                    px = ascii_measure(tok.text) * cw / 100.0
                    tok.cells = max(1, min(row_cap(), round(px / half_adv)))
                # 超长 token（URL 等）按整行硬切
                chunks: list[Token] = []
                if tok.cells > row_cap():
                    s = tok.text
                    step = row_cap()
                    for k in range(0, len(s), step):
                        part = s[k:k + step]
                        chunks.append(Token(part, len(part),
                                            start_forbidden=(tok.start_forbidden and k == 0)))
                else:
                    chunks = [tok]
                for ci, tk in enumerate(chunks):
                    # 行尾禁则：起始标点放不进本行 → 整体移到下一行
                    if tk.end_forbidden and col + tk.cells > row_cap():
                        new_line()
                    # 先换行再判禁则（顺序不能反）
                    if col + tk.cells > row_cap():
                        new_line()
                    # 行首禁则：标点落在行首 → 挤到上一行末格
                    if tk.start_forbidden and col == 0 and page:
                        last = page[-1]
                        if not last.squeezed:
                            page.append(PlacedToken(tk.text, last.row, last.col,
                                                    tk.cells, squeezed=True))
                            placed_half += tk.cells
                            continue
                    use_fb = bool(coverage_check and any(
                        coverage_check(c) for c in tk.text if not c.isspace()
                    ))
                    if use_fb:
                        report.missing_chars.extend(list(tk.text.strip()))
                        report.fallback_used.extend(list(tk.text.strip()))
                    page.append(PlacedToken(tk.text, row, col, tk.cells, use_fallback=use_fb))
                    placed_half += tk.cells
                    col += tk.cells
        except _Overflow:
            pass

        overflow = max(0, (total_half - placed_half + 1) // 2)
        cells_per_page = sum(row_caps) if row_caps else rows * cols
        return LayoutResult(pages=pages, missing=report,
                            cells_per_page=cells_per_page, overflow_chars=overflow)
