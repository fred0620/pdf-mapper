"""把 PDF 頁面整理成統一的資料：不論來自文字層或 OCR，都是一顆顆帶座標的字（Glyph）。

所有座標都是「佔頁面比例」(0 到 1)，左上為原點。
"""
from __future__ import annotations

import math
import threading
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from statistics import median

import numpy as np
import pdfplumber
import pypdfium2 as pdfium

from . import ocr as ocr_engine
from .limits import MAX_CACHED_RENDERS, MAX_RENDER_PIXELS, check_pages

Box = tuple[float, float, float, float]

# pdfium 不是 thread-safe，所有渲染都要排隊。
_PDFIUM_LOCK = threading.RLock()
DEFAULT_OCR_DPI = 300
OCR_MARGIN = 0.02
EDGE_EPS = 0.002


@dataclass(slots=True)
class Glyph:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    score: float = 1.0
    source: str = "text"
    line: int = -1  # OCR 的同一行共用編號，文字層為 -1
    clipped: bool = False  # 這一行超出辨識範圍，可能少字

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def width(self) -> float:
        return self.x1 - self.x0


def normalize_text(text: str) -> str:
    """比對用：全形轉半形、去空白、轉小寫。"""
    return "".join(unicodedata.normalize("NFKC", text).split()).lower()


def is_garbled(text: str) -> bool:
    """字型缺對照表時，文字層會吐出 (cid:123)、私有區字元或替代字元。"""
    if "(cid:" in text or "�" in text:
        return True
    return any(0xE000 <= ord(c) <= 0xF8FF for c in text)


def group_lines(glyphs: list[Glyph]) -> list[list[Glyph]]:
    """依垂直位置把字分行，每行由左到右。"""
    if not glyphs:
        return []
    typical = median(g.height for g in glyphs) or 0.005
    lines: list[list[Glyph]] = []
    centers: list[float] = []
    for g in sorted(glyphs, key=lambda item: item.cy):
        if lines and abs(g.cy - centers[-1]) <= typical * 0.6:
            lines[-1].append(g)
            centers[-1] = sum(item.cy for item in lines[-1]) / len(lines[-1])
        else:
            lines.append([g])
            centers.append(g.cy)
    return [sorted(line, key=lambda item: item.x0) for line in lines]


def line_text(line: list[Glyph]) -> str:
    if not line:
        return ""
    widths = [g.width for g in line if g.width > 0]
    gap = (median(widths) if widths else 0.005) * 0.6
    parts = [line[0].text]
    for prev, cur in zip(line, line[1:]):
        if cur.x0 - prev.x1 > gap:
            parts.append(" ")
        parts.append(cur.text)
    return "".join(parts)


def inside(g: Glyph, box: Box) -> bool:
    return box[0] <= g.cx <= box[2] and box[1] <= g.cy <= box[3]


def expand(box: Box, margin: float) -> Box:
    return (
        max(0.0, box[0] - margin),
        max(0.0, box[1] - margin),
        min(1.0, box[2] + margin),
        min(1.0, box[3] + margin),
    )


class Page:
    def __init__(self, document: "Document", index: int):
        self.document = document
        self.index = index
        plumber_page = document._plumber.pages[index]
        self.width = float(plumber_page.width)
        self.height = float(plumber_page.height)
        self._glyphs: list[Glyph] | None = None
        self._ocr: dict[tuple, list[Glyph]] = {}

    @property
    def glyphs(self) -> list[Glyph]:
        """文字層的字。圖片裡的字不在這裡。"""
        if self._glyphs is None:
            with self.document._lock:
                raw = self.document._plumber.pages[self.index]
                x_origin, y_origin = raw.bbox[0], raw.bbox[1]
                chars = raw.dedupe_chars().chars
            result = []
            for c in chars:
                text = c.get("text", "")
                if not text or not text.strip():
                    continue
                result.append(
                    Glyph(
                        text,
                        (c["x0"] - x_origin) / self.width,
                        (c["top"] - y_origin) / self.height,
                        (c["x1"] - x_origin) / self.width,
                        (c["bottom"] - y_origin) / self.height,
                    )
                )
            self._glyphs = result
        return self._glyphs

    def render(self, dpi: int = 150) -> np.ndarray:
        """回傳 RGB 陣列。"""
        cache, key = self.document._renders, (self.index, dpi)
        with self.document._cache_lock:
            cached = cache.get(key)
            if cached is not None:
                cache.move_to_end(key)
                return cached
        # 頁面尺寸異常大時降低解析度，座標都是比例，不影響對位與取值
        scale = dpi / 72
        pixels = self.width * self.height * scale * scale
        if pixels > MAX_RENDER_PIXELS:
            scale *= math.sqrt(MAX_RENDER_PIXELS / pixels)
        # 頁面與點陣圖都要在鎖內明確關閉：交給垃圾回收的話，釋放動作可能在
        # 別的執行緒渲染途中發生，造成畫面損毀，OCR 就會讀出錯字。
        with _PDFIUM_LOCK:
            page = self.document._pdfium[self.index]
            bitmap = page.render(scale=scale)
            array = np.array(bitmap.to_pil().convert("RGB"))
            bitmap.close()
            page.close()
        # 整份文件共用一個上限：長的掃描檔逐頁 OCR 時，舊頁面的圖會被釋放
        with self.document._cache_lock:
            cache[key] = array
            while len(cache) > MAX_CACHED_RENDERS:
                cache.popitem(last=False)
        return array

    def crop(self, box: Box, dpi: int = 150) -> np.ndarray:
        image = self.render(dpi)
        h, w = image.shape[:2]
        x0, x1 = int(box[0] * w), max(int(box[0] * w) + 1, int(box[2] * w))
        y0, y1 = int(box[1] * h), max(int(box[1] * h) + 1, int(box[3] * h))
        return image[max(y0, 0):min(y1, h), max(x0, 0):min(x1, w)]

    def ocr_region(self, box: Box, margin: float = OCR_MARGIN) -> tuple[list[Glyph], bool]:
        """辨識一個範圍，回傳 (字, 是否被裁切)。

        先照框辨識。若文字貼到框邊，代表可能被切到（靠框線的數字很常見），
        才左右多裁一點重讀，並以「整行的中心」判斷歸屬。
        仍然超出的話，表示框真的太小，要提醒使用者。
        """
        exact = self.ocr(box)
        if not exact:
            return [], False
        if (min(g.x0 for g in exact) > box[0] + EDGE_EPS * 2
                and max(g.x1 for g in exact) < box[2] - EDGE_EPS * 2):
            return exact, False
        wide = (max(0.0, box[0] - margin), box[1], min(1.0, box[2] + margin), box[3])
        groups: dict[int, list[Glyph]] = {}
        for g in self.ocr(wide):
            groups.setdefault(g.line, []).append(g)
        kept: list[Glyph] = []
        clipped = False
        for line in groups.values():
            left, right = min(g.x0 for g in line), max(g.x1 for g in line)
            if not box[0] <= (left + right) / 2 <= box[2]:
                continue
            kept.extend(line)
            clipped = clipped or (left <= wide[0] + EDGE_EPS and wide[0] > 0)
            clipped = clipped or (right >= wide[2] - EDGE_EPS and wide[2] < 1)
        return kept, clipped

    def ocr(self, box: Box = (0.0, 0.0, 1.0, 1.0), dpi: int = DEFAULT_OCR_DPI) -> list[Glyph]:
        """對指定範圍做 OCR，並把結果換回頁面座標。"""
        key = tuple(round(v, 4) for v in box) + (dpi,)
        if key in self._ocr:
            return self._ocr[key]
        crop = self.crop(box, dpi)
        glyphs: list[Glyph] = []
        if crop.size and (crop < 128).any():  # 空白區域不必辨識
            h, w = crop.shape[:2]
            to_x = lambda v: box[0] + v / w * (box[2] - box[0])
            to_y = lambda v: box[1] + v / h * (box[3] - box[1])
            for number, (text, (x0, y0, x1, y1), score) in enumerate(ocr_engine.read(crop)):
                glyphs.extend(_split_line(text, to_x(x0), to_y(y0), to_x(x1), to_y(y1), score, number))
        self._ocr[key] = glyphs
        return glyphs


def _split_line(text: str, x0: float, y0: float, x1: float, y1: float, score: float,
                number: int) -> list[Glyph]:
    """OCR 只給整行的框，依字元寬度估算每個字的位置，後續流程就能共用。"""
    weights = [1.0 if unicodedata.east_asian_width(c) in "WF" else 0.55 for c in text]
    total = sum(weights) or 1.0
    glyphs, cursor = [], x0
    for char, weight in zip(text, weights):
        step = (x1 - x0) * weight / total
        if char.strip():
            glyphs.append(Glyph(char, cursor, y0, cursor + step, y1, score, "ocr", number))
        cursor += step
    return glyphs


class Document:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._cache_lock = threading.Lock()
        self._renders: OrderedDict[tuple[int, int], np.ndarray] = OrderedDict()
        with _PDFIUM_LOCK:
            self._pdfium = pdfium.PdfDocument(str(self.path))
            count = len(self._pdfium)
        try:
            check_pages(count)  # 先檢查頁數，超過上限就不建立頁面資料
            self._plumber = pdfplumber.open(str(self.path))
        except Exception:
            with _PDFIUM_LOCK:
                self._pdfium.close()
            raise
        self.pages = [Page(self, i) for i in range(len(self._plumber.pages))]

    def __len__(self) -> int:
        return len(self.pages)

    def close(self) -> None:
        self._renders.clear()
        self._plumber.close()
        with _PDFIUM_LOCK:
            self._pdfium.close()

    def __enter__(self) -> "Document":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
