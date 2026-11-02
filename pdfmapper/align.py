"""對位：找到定位點，算出「範本座標」到「這一頁座標」的轉換。

定位點的尋找順序：影像比對（快、不需文字）→ 文字層 → OCR。
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import cv2
import numpy as np

from . import ocr as ocr_engine
from .document import Box, Page, expand, group_lines, normalize_text

PATCH_DPI = 150
SEARCH_MARGIN = 0.06
PATCH_MIN_SCORE = 0.78
GOOD_RESIDUAL = 0.005


@dataclass
class Hit:
    anchor_id: str
    ref: tuple[float, float]
    found: tuple[float, float]
    method: str
    score: float


@dataclass
class Transform:
    a: float = 1.0
    b: float = 0.0
    tx: float = 0.0
    c: float = 0.0
    d: float = 1.0
    ty: float = 0.0
    quality: str = "fixed"  # good / weak / none / fixed（範本沒有定位點）
    found: int = 0
    total: int = 0
    residual: float = 0.0
    hits: dict[str, Hit] = field(default_factory=dict)

    def point(self, x: float, y: float) -> tuple[float, float]:
        return self.a * x + self.b * y + self.tx, self.c * x + self.d * y + self.ty

    def box(self, box: Box) -> Box:
        corners = [self.point(x, y) for x in (box[0], box[2]) for y in (box[1], box[3])]
        xs, ys = zip(*corners)
        return min(xs), min(ys), max(xs), max(ys)

    def summary(self) -> dict:
        return {
            "quality": self.quality,
            "found": self.found,
            "total": self.total,
            "residual": round(self.residual, 5),
            "methods": sorted({hit.method for hit in self.hits.values()}),
        }


def make_patch(page: Page, box: Box) -> str:
    gray = cv2.cvtColor(page.crop(box, PATCH_DPI), cv2.COLOR_RGB2GRAY)
    ok, encoded = cv2.imencode(".png", gray)
    return base64.b64encode(encoded.tobytes()).decode() if ok else ""


def _decode_patch(data: str) -> np.ndarray | None:
    if not data:
        return None
    return cv2.imdecode(np.frombuffer(base64.b64decode(data), np.uint8), cv2.IMREAD_GRAYSCALE)


def _find_by_patch(page: Page, anchor: dict, box: Box) -> tuple[float, float, float] | None:
    patch = _decode_patch(anchor.get("patch", ""))
    if patch is None or patch.std() < 6:  # 幾乎全白的圖塊比不出東西
        return None
    roi_box = expand(box, SEARCH_MARGIN)
    roi = cv2.cvtColor(page.crop(roi_box, PATCH_DPI), cv2.COLOR_RGB2GRAY)
    best = (0.0, None)
    for scale in (1.0, 0.98, 1.02, 0.96, 1.04, 0.93, 1.07):
        scaled = patch if scale == 1.0 else cv2.resize(patch, None, fx=scale, fy=scale)
        if scaled.shape[0] >= roi.shape[0] or scaled.shape[1] >= roi.shape[1]:
            continue
        result = cv2.matchTemplate(roi, scaled, cv2.TM_CCOEFF_NORMED)
        _, score, _, location = cv2.minMaxLoc(result)
        if score > best[0]:
            best = (score, (location[0] + scaled.shape[1] / 2, location[1] + scaled.shape[0] / 2))
        if score > 0.95:
            break
    if best[1] is None or best[0] < PATCH_MIN_SCORE:
        return None
    h, w = roi.shape
    return (
        roi_box[0] + best[1][0] / w * (roi_box[2] - roi_box[0]),
        roi_box[1] + best[1][1] / h * (roi_box[3] - roi_box[1]),
        float(best[0]),
    )


def find_text(glyphs: list, text: str, near: tuple[float, float] | None = None,
              fuzzy: bool = False) -> tuple[float, float, float] | None:
    """在字群中找一段文字，回傳 (中心 x, 中心 y, 分數)。"""
    target = normalize_text(text)
    if not target:
        return None
    candidates = []
    for line in group_lines(glyphs):
        chars = [normalize_text(g.text) or " " for g in line]
        joined = "".join(chars)
        if len(chars) != len(joined):  # 含連字等多碼字元時不做逐字對應
            continue
        for start in range(0, max(1, len(joined) - len(target) + 1)):
            window = joined[start:start + len(target)]
            if window == target:
                score = 1.0
            elif fuzzy and len(window) == len(target):
                score = SequenceMatcher(None, window, target).ratio()
            else:
                continue
            if score < 0.72:
                continue
            matched = line[start:start + len(target)]
            x = (matched[0].x0 + matched[-1].x1) / 2
            y = sum(g.cy for g in matched) / len(matched)
            candidates.append((x, y, score))
    if not candidates:
        return None
    if near:
        return min(candidates, key=lambda c: (c[0] - near[0]) ** 2 + (c[1] - near[1]) ** 2 - c[2] * 1e-3)
    return max(candidates, key=lambda c: c[2])


def box_center(box: Box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def locate(page: Page, anchor: dict, allow_ocr: bool) -> Hit | None:
    box = tuple(anchor["box"])
    expected = box_center(box)
    found = _find_by_patch(page, anchor, box)
    if found:
        return Hit(anchor["id"], expected, found[:2], "image", found[2])
    text = anchor.get("text", "")
    ref = tuple(anchor.get("text_center") or expected)
    if text:
        found = find_text(page.glyphs, text, near=expected)
        if found and _plausible(found, expected):
            return Hit(anchor["id"], ref, found[:2], "text", found[2])
        if allow_ocr and ocr_engine.available():
            found = find_text(page.ocr(), text, near=expected, fuzzy=True)
            if found and _plausible(found, expected):
                return Hit(anchor["id"], ref, found[:2], "ocr", found[2])
    return None


def _plausible(found, expected, limit: float = 0.18) -> bool:
    return abs(found[0] - expected[0]) <= limit and abs(found[1] - expected[1]) <= limit


def estimate(hits: list[Hit], total: int) -> Transform:
    if total == 0:
        return Transform(quality="fixed")
    if not hits:
        return Transform(quality="none", total=total)
    src = np.array([h.ref for h in hits], dtype=np.float32)
    dst = np.array([h.found for h in hits], dtype=np.float32)
    transform = Transform(total=total, found=len(hits), hits={h.anchor_id: h for h in hits})
    if len(hits) >= 3:
        matrix, inliers = cv2.estimateAffinePartial2D(
            src, dst, method=cv2.RANSAC, ransacReprojThreshold=0.006, maxIters=2000
        )
        if matrix is not None and _sane(matrix):
            transform.a, transform.b, transform.tx = map(float, matrix[0])
            transform.c, transform.d, transform.ty = map(float, matrix[1])
            mask = inliers.ravel().astype(bool)
            transform.residual = _residual(transform, src[mask], dst[mask])
            enough = mask.sum() >= 3 and transform.residual <= GOOD_RESIDUAL
            transform.quality = "good" if enough else "weak"
            return transform
    # 點太少或轉換不合理時，只做平移
    shift = np.median(dst - src, axis=0)
    transform.tx, transform.ty = float(shift[0]), float(shift[1])
    transform.residual = _residual(transform, src, dst)
    transform.quality = "weak"
    return transform


def _sane(matrix: np.ndarray) -> bool:
    scale = float(np.hypot(matrix[0, 0], matrix[1, 0]))
    angle = abs(float(np.degrees(np.arctan2(matrix[1, 0], matrix[0, 0]))))
    return 0.85 <= scale <= 1.15 and angle <= 4


def _residual(transform: Transform, src: np.ndarray, dst: np.ndarray) -> float:
    predicted = np.array([transform.point(float(x), float(y)) for x, y in src])
    return float(np.median(np.hypot(*(predicted - dst).T)))


def align_page(page: Page, anchors: list[dict], allow_ocr: bool = True) -> Transform:
    hits = [hit for hit in (locate(page, a, allow_ocr=False) for a in anchors) if hit]
    if allow_ocr and anchors and len(hits) < min(3, len(anchors)) and ocr_engine.available():
        known = {hit.anchor_id for hit in hits}
        hits += [hit for a in anchors if a["id"] not in known
                 for hit in [locate(page, a, allow_ocr=True)] if hit]
    return estimate(hits, len(anchors))
