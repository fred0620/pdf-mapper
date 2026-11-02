"""依範本取值。這一層只忠實取值與標記疑點，不改寫資料內容。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import ocr as ocr_engine
from .align import Transform
from .document import Box, Glyph, Page, group_lines, inside, is_garbled, line_text, normalize_text

OCR_MIN_CONFIDENCE = 0.85
LABEL_MOVED = 0.03
TYPE_PATTERNS = {
    "number": r"^[-+(]?\s*[\d,]*\.?\d+\s*%?\)?$",
    "date": r"^.*\d.*$",
}

# 每種疑點都用白話告訴使用者要看什麼。
REASONS = {
    "ocr_low_confidence": "影像辨識信心偏低",
    "ocr_disagrees": "文字層與影像辨識結果不同",
    "garbled_text_layer": "文字層是亂碼，已改用影像辨識",
    "ocr_unavailable": "文字層沒有內容，且影像辨識無法使用",
    "weak_alignment": "這一頁對位不穩，位置可能有偏差",
    "no_alignment": "這一頁找不到定位點，用範本原始位置取值",
    "label_moved": "欄位標題位置與其他欄位偏移不一致",
    "touches_edge": "內容壓到框線，可能少抓字",
    "crosses_column": "內容跨到隔壁欄，可能分錯欄",
    "format_mismatch": "格式與設定不符",
    "required_missing": "必填欄位沒有抓到值",
    "sum_mismatch": "加總驗證不符",
    "row_spans_pages": "這一列可能跨頁，已合併，請確認",
    "sequence_gap": "項次不連續，可能漏列",
}


@dataclass
class Reading:
    text: str = ""
    lines: list[str] = field(default_factory=list)
    source: str = ""
    confidence: float = 1.0
    reasons: list[str] = field(default_factory=list)


def _confidence(glyphs: list[Glyph]) -> float:
    return round(sum(g.score for g in glyphs) / len(glyphs), 3) if glyphs else 0.0


def _text_lines(glyphs: list[Glyph]) -> list[str]:
    return [line_text(line) for line in group_lines(glyphs)]


def _crosses_edge(page: Page, box: Box, kept: list[Glyph]) -> bool:
    """同一行的字壓在左右框線上，或就緊貼在框外，代表框太小、可能少抓字。"""
    for g in page.glyphs:
        if not box[1] < g.cy < box[3]:
            continue
        if g.x0 < box[0] < g.x1 or g.x0 < box[2] < g.x1:
            return True
        reach = g.width * 1.2
        beside = (box[0] - reach < g.x1 <= box[0]) or (box[2] <= g.x0 < box[2] + reach)
        if beside and any(abs(k.cy - g.cy) < g.height / 2 and abs(k.cx - g.cx) < reach * 2 for k in kept):
            return True
    return False


def read_box(page: Page, box: Box, source: str = "auto", verify: bool = False,
             use_ocr: bool = True) -> Reading:
    """讀一個範圍。auto：文字層優先，沒有或是亂碼才用影像辨識。"""
    reading = Reading()
    text_glyphs = [g for g in page.glyphs if inside(g, box)]
    garbled = any(is_garbled(g.text) for g in text_glyphs)
    if source != "ocr" and text_glyphs and not garbled:
        reading.lines = _text_lines(text_glyphs)
        reading.source, reading.confidence = "text", 1.0
        if _crosses_edge(page, box, text_glyphs):
            reading.reasons.append("touches_edge")
        if verify and use_ocr and ocr_engine.available():
            other = normalize_text("".join(_text_lines(page.ocr_region(box)[0])))
            if normalize_text("".join(reading.lines)) != other:
                reading.reasons.append("ocr_disagrees")
    elif source == "text":
        reading.source = "text"
    elif use_ocr and ocr_engine.available():
        glyphs, clipped = page.ocr_region(box)
        reading.lines = _text_lines(glyphs)
        reading.source, reading.confidence = "ocr", _confidence(glyphs) if glyphs else 1.0
        if clipped:
            reading.reasons.append("touches_edge")
        if garbled:
            reading.reasons.append("garbled_text_layer")
        if glyphs and reading.confidence < OCR_MIN_CONFIDENCE:
            reading.reasons.append("ocr_low_confidence")
    elif use_ocr:
        reading.reasons.append("ocr_unavailable")
    reading.text = " ".join(reading.lines).strip()
    return reading


def shape_value(reading_text: str, lines: list[str], spec: dict) -> tuple[str, list[str]]:
    """依設定選行、擷取並檢查格式。回傳 (值, 疑點)。"""
    reasons: list[str] = []
    value = reading_text
    pick = spec.get("pick_line")
    if pick:
        index = pick - 1 if pick > 0 else pick
        value = lines[index] if -len(lines) <= index < len(lines) else ""
    extract = spec.get("extract")
    if extract and value:
        match = re.search(extract, value)
        if match:
            value = match.group(1) if match.groups() else match.group(0)
        else:
            reasons.append("format_mismatch")
            return value.strip(), reasons
    value = value.strip()
    pattern = spec.get("pattern") or TYPE_PATTERNS.get(spec.get("type", "text"))
    if value and pattern and not re.search(pattern, value):
        reasons.append("format_mismatch")
    return value, reasons


def make_value(spec: dict, value: str, source: str, confidence: float, reasons: list[str],
               page: int | None, box: Box | None, transform: Transform | None) -> dict:
    reasons = list(dict.fromkeys(reasons))
    if transform and transform.quality == "none":
        reasons.append("no_alignment")
    elif transform and transform.quality == "weak":
        reasons.append("weak_alignment")
    if not value and spec.get("required"):
        reasons.append("required_missing")
        status = "missing"
    elif not value:
        reasons = [r for r in reasons if r == "ocr_unavailable"]
        status = "review" if reasons else "ok"
    else:
        status = "review" if reasons else "ok"
    return {
        "value": value,
        "status": status,
        "reasons": reasons,
        "source": source,
        "confidence": confidence,
        "page": None if page is None else page + 1,
        "box": None if box is None else [round(v, 5) for v in box],
    }


def locate_value_box(field_spec: dict, transform: Transform) -> tuple[Box, list[str]]:
    """有標題的欄位優先跟著自己的標題走，否則跟著整頁轉換走。"""
    box = transform.box(tuple(field_spec["value_box"]))
    hit = transform.hits.get(f"label:{field_spec['id']}")
    if field_spec.get("kind") != "key_value" or not hit:
        return box, []
    px, py = transform.point(*hit.ref)
    dx, dy = hit.found[0] - px, hit.found[1] - py
    reasons = ["label_moved"] if max(abs(dx), abs(dy)) > LABEL_MOVED else []
    return (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy), reasons


def extract_field(spec: dict, pages: list[Page], transforms: dict[int, Transform],
                  use_ocr: bool = True) -> dict:
    last = None
    for page in pages:
        transform = transforms[page.index]
        box, reasons = locate_value_box(spec, transform)
        reading = read_box(page, box, spec.get("source", "auto"), bool(spec.get("verify")), use_ocr)
        value, shape_reasons = shape_value(reading.text, reading.lines, spec)
        result = make_value(spec, value, reading.source, reading.confidence,
                            reasons + reading.reasons + shape_reasons, page.index, box, transform)
        if value:
            return result
        last = result
    return last or make_value(spec, "", "", 0.0, [], None, None, None)


def _ocr_bands(page: Page, box: Box, dividers: list[float]) -> list[Glyph]:
    """逐直欄辨識。整張表一起辨識時，同一高度的多欄常被併成一行，位置就不準了。"""
    glyphs: list[Glyph] = []
    for band, (left, right) in enumerate(zip(dividers, dividers[1:])):
        found, clipped = page.ocr_region((left, box[1], right, box[3]), margin=0.012)
        lines: dict[int, list[Glyph]] = {}
        for g in found:
            lines.setdefault(g.line, []).append(g)
        for number, line in lines.items():
            # 壓線的行整行收回本欄，保持字序；各欄的行編號互不相干
            start, end = min(g.x0 for g in line), max(g.x1 for g in line)
            margin = (right - left) * 0.01
            scale = min(1.0, (right - left - 2 * margin) / (end - start))
            target = min(max(start, left + margin), right - margin - (end - start) * scale)
            place = lambda x: target + (x - start) * scale
            glyphs.extend(
                Glyph(g.text, place(g.x0), g.y0, place(g.x1), g.y1, g.score, "ocr",
                      band * 1000 + number, clipped)
                for g in line
            )
    return glyphs


def _table_glyphs(page: Page, box: Box, dividers: list[float], source: str,
                  use_ocr: bool) -> tuple[list[Glyph], str, list[str]]:
    glyphs = [g for g in page.glyphs if inside(g, box)]
    garbled = any(is_garbled(g.text) for g in glyphs)
    if source != "ocr" and glyphs and not garbled:
        return glyphs, "text", []
    if source == "text" or not use_ocr:
        return [], "text", []
    if not ocr_engine.available():
        return [], "", ["ocr_unavailable"]
    return _ocr_bands(page, box, dividers), "ocr", ["garbled_text_layer"] if garbled else []


def _ocr_empty_bands(page: Page, glyphs: list[Glyph], dividers: list[float], box: Box) -> list[Glyph]:
    """文字層只有部分直欄時，其餘直欄的內容可能在影像裡，只補辨識這幾欄。"""
    if not ocr_engine.available():
        return []
    extra: list[Glyph] = []
    for left, right in zip(dividers, dividers[1:]):
        if not any(left <= g.cx < right for g in glyphs):
            extra += _ocr_bands(page, box, [left, right])
    return extra


def _boundaries(key_lines: list[list[Glyph]], glyphs: list[Glyph], top: float, bottom: float,
                key_at_top: bool) -> list[tuple[float, float]]:
    """切出每一列的上下界。項次可能在列的中間，所以用兩個項次之間最大的空白來切。"""
    cuts = [top]
    for upper, lower in zip(key_lines, key_lines[1:]):
        y_upper, y_lower = upper[0].cy, lower[0].cy
        if key_at_top:
            cuts.append(min(g.y0 for g in lower) - 1e-4)
            continue
        spans = sorted((g.y0, g.y1) for g in glyphs if y_upper < g.cy < y_lower)
        reach, best_gap, cut = y_upper, 0.0, (y_upper + y_lower) / 2
        for y0, y1 in spans:
            if y0 - reach > best_gap:
                best_gap, cut = y0 - reach, (y0 + reach) / 2
            reach = max(reach, y1)
        if y_lower - reach > best_gap:
            cut = (y_lower + reach) / 2
        cuts.append(cut)
    cuts.append(bottom)
    return list(zip(cuts, cuts[1:]))


def extract_table(spec: dict, pages: list[Page], transforms: dict[int, Transform], total_pages: int,
                  use_ocr: bool = True) -> dict:
    from .template import rule_matches

    columns = spec["columns"]
    key_id = spec.get("key_column")
    key_index = next((_band(c, i) for i, c in enumerate(columns) if c["id"] == key_id), None)
    key_pattern = spec.get("key_pattern") or r"^\d+$"
    key_at_top = spec.get("key_position", "middle") == "top"
    stop_pattern = spec.get("stop_pattern")
    rows: list[dict] = []
    stopped = False

    for page in pages:
        if stopped:
            break
        region = next((r for r in spec["regions"]
                       if rule_matches(r.get("page_rule", "first"), page.index, total_pages)), None)
        if region is None:
            continue
        transform = transforms[page.index]
        box = transform.box(tuple(region["box"]))
        middle_y = (region["box"][1] + region["box"][3]) / 2
        dividers = [transform.point(x, middle_y)[0] for x in region["dividers"]]
        glyphs, source, page_reasons = _table_glyphs(page, box, dividers, spec.get("source", "auto"), use_ocr)
        if stop_pattern:
            for line in group_lines(glyphs):
                if re.search(stop_pattern, line_text(line).replace(" ", "")):
                    limit = min(g.y0 for g in line)
                    glyphs = [g for g in glyphs if g.cy < limit]
                    stopped = True
                    break
        if not glyphs:
            continue

        if source == "text" and use_ocr and spec.get("source", "auto") == "auto":
            glyphs = glyphs + _ocr_empty_bands(page, glyphs, dividers, box)

        bands = _rows_on_page(glyphs, dividers, key_index, key_pattern, box, key_at_top)
        for band_top, band_bottom, spill in bands:
            band = [g for g in glyphs if band_top <= g.cy < band_bottom]
            if not band:
                continue
            if spill and rows:
                _merge_spill(rows[-1], band, columns, dividers)
                continue
            rows.append(_build_row(band, columns, dividers, source, page, transform,
                                   (box[0], band_top, box[2], band_bottom), page_reasons))

    issues = _check_sequence(rows, key_id)
    return {"id": spec["id"], "name": spec.get("name", spec["id"]),
            "columns": [{"id": c["id"], "name": c.get("name", c["id"])} for c in columns],
            "rows": rows, "issues": issues}


def _rows_on_page(glyphs, dividers, key_index, key_pattern, box, key_at_top):
    if key_index is None:  # 沒有項次欄：每一行文字就是一列
        return [(min(g.y0 for g in line) - 1e-4, max(g.y1 for g in line) + 1e-4, False)
                for line in group_lines(glyphs)]
    left, right = dividers[key_index], dividers[key_index + 1]
    key_glyphs = [g for g in glyphs if left <= g.cx < right]
    keys = [line for line in group_lines(key_glyphs)
            if re.search(key_pattern, line_text(line).strip())]
    if not keys:  # 整頁都是上一列的延續
        return [(box[1], box[3] + 1e-4, True)]
    bands = [(top, bottom, False)
             for top, bottom in _boundaries(keys, glyphs, box[1], box[3] + 1e-4, key_at_top)]
    if key_at_top:
        first_top = min(g.y0 for g in keys[0]) - 1e-4
        bands[0] = (first_top, bands[0][1], False)
        bands.insert(0, (box[1], first_top, True))
    return bands


def _band(column: dict, index: int) -> int:
    """一個直欄可拆成多個輸出欄（例如同格上下兩行），band 指向實際的直欄。"""
    return column.get("band", index)


def _cell(column, glyphs, source, page, transform, box, crossed, extra_reasons):
    lines = _text_lines(glyphs)
    value, reasons = shape_value(" ".join(lines).strip(), lines, column)
    if crossed:
        reasons.append("crosses_column")
    confidence = _confidence(glyphs) if glyphs else 0.0
    if glyphs and confidence < OCR_MIN_CONFIDENCE:
        reasons.append("ocr_low_confidence")
    actual = "ocr" if any(g.source == "ocr" for g in glyphs) else source
    return make_value(column, value, actual, confidence, extra_reasons + reasons, page.index, box, transform)


def _split_bands(band, dividers):
    count = len(dividers) - 1
    cells = [[] for _ in range(count)]
    crossed = [False] * count
    for g in band:
        for i in range(count):
            if dividers[i] <= g.cx < dividers[i + 1]:
                cells[i].append(g)
                crossed[i] = crossed[i] or g.clipped
                if g.x0 < dividers[i] - g.width * 0.15 or g.x1 > dividers[i + 1] + g.width * 0.15:
                    crossed[i] = True
                break
    return cells, crossed


def _build_row(band, columns, dividers, source, page, transform, box, reasons) -> dict:
    cells, crossed = _split_bands(band, dividers)
    row = {"page": page.index + 1, "cells": {}}
    for index, column in enumerate(columns):
        i = _band(column, index)
        cell_box = (dividers[i], box[1], dividers[i + 1], box[3])
        row["cells"][column["id"]] = _cell(column, cells[i], source, page, transform,
                                           cell_box, crossed[i], list(reasons))
    return row


def _merge_spill(row, band, columns, dividers) -> None:
    cells, _ = _split_bands(band, dividers)
    for index, column in enumerate(columns):
        glyphs = cells[_band(column, index)]
        if not glyphs:
            continue
        cell = row["cells"][column["id"]]
        extra = " ".join(_text_lines(glyphs))
        cell["value"] = f"{cell['value']} {extra}".strip()
        cell["reasons"] = list(dict.fromkeys(cell["reasons"] + ["row_spans_pages"]))
        cell["status"] = "review"


def _check_sequence(rows, key_id) -> list[dict]:
    if not key_id:
        return []
    issues, previous = [], None
    for row in rows:
        cell = row["cells"].get(key_id)
        text = (cell or {}).get("value", "")
        if not text.isdigit():
            continue
        number = int(text)
        if previous is not None and number != previous + 1:
            cell["reasons"] = list(dict.fromkeys(cell["reasons"] + ["sequence_gap"]))
            cell["status"] = "review"
            issues.append({"code": "sequence_gap", "page": row["page"],
                           "message": f"項次從 {previous} 跳到 {number}，可能漏列"})
        previous = number
    return issues
