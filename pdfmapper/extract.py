"""依範本取值。這一層只忠實取值與標記疑點，不改寫資料內容。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import ocr as ocr_engine
from .align import Transform, find_marker
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
    "column_collision": "同一行有兩段內容搶同一欄，請確認分欄",
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


def _place_table(spec: dict, region: dict, page: Page, transform: Transform, use_ocr: bool,
                 issues: list[dict]) -> tuple[Box, list[float], bool]:
    """決定這一頁表格的實際範圍。回傳 (範圍, 分隔線, 是否在此結束)。

    有表頭時，上緣和左右都跟著表頭走；下緣維持原位，代表「資料最低到這裡」，
    表格提早結束則交給表尾標記或結束文字判斷。
    """
    box = transform.box(tuple(region["box"]))
    middle_y = (region["box"][1] + region["box"][3]) / 2
    dividers = [transform.point(x, middle_y)[0] for x in region["dividers"]]
    name = spec.get("name", spec["id"])

    header = region.get("header")
    if header:
        left, right = transform.box(tuple(header["box"]))[0], transform.box(tuple(header["box"]))[2]
        hit = find_marker(page, header, (max(0.0, left - 0.1), 0.0, min(1.0, right + 0.1), 1.0), use_ocr)
        if hit:
            expected = transform.point(*hit.ref)
            dx, dy = hit.found[0] - expected[0], hit.found[1] - expected[1]
            box = (box[0] + dx, box[1] + dy, box[2] + dx, max(box[3], box[1] + dy + 0.01))
            dividers = [x + dx for x in dividers]
        else:
            issues.append({"code": "header_not_found", "page": page.index + 1,
                           "message": f"表格「{name}」找不到表頭，改用範本的固定位置"})

    ended = False
    marker = spec.get("end_marker")
    if marker:
        left, right = transform.box(tuple(marker["box"]))[0], transform.box(tuple(marker["box"]))[2]
        hit = find_marker(page, marker, (max(0.0, left - 0.1), box[1], min(1.0, right + 0.1), 1.0), use_ocr)
        if hit:
            half = (marker["box"][3] - marker["box"][1]) / 2
            box = (box[0], box[1], box[2], min(box[3], hit.found[1] - half))
            ended = True
    return box, dividers, ended


def _key_on_first_line(keys: list[list[Glyph]], glyphs: list[Glyph]) -> bool:
    """第一個項次上方沒有任何內容，代表項次就在每一列的第一行。"""
    top = min(g.y0 for g in keys[0])
    height = max(g.height for g in keys[0])
    return not any(g.cy < top - height * 0.3 for g in glyphs)


def extract_table(spec: dict, pages: list[Page], transforms: dict[int, Transform], total_pages: int,
                  use_ocr: bool = True) -> dict:
    from .template import rule_matches

    columns = spec["columns"]
    key_id = spec.get("key_column")
    key_index = next((_band(c, i) for i, c in enumerate(columns) if c["id"] == key_id), None)
    key_pattern = spec.get("key_pattern") or r"^\d+$"
    position = spec.get("key_position", "middle")  # 舊範本沒有這個設定，維持原本的行為
    key_at_top = None if position == "auto" else position == "top"
    stop_pattern = spec.get("stop_pattern")
    rows: list[dict] = []
    issues: list[dict] = []
    stopped = False

    for page in pages:
        if stopped:
            break
        region = next((r for r in spec["regions"]
                       if rule_matches(r.get("page_rule", "first"), page.index, total_pages)), None)
        if region is None:
            continue
        transform = transforms[page.index]
        box, dividers, stopped = _place_table(spec, region, page, transform, use_ocr, issues)
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

        if key_at_top is None and key_index is not None:  # 第一頁判斷一次，續頁沿用
            keys = _key_lines(glyphs, dividers, key_index, key_pattern)
            if keys:
                key_at_top = _key_on_first_line(keys, glyphs)
        layout = _assign_chunks(glyphs, dividers)
        bands = _rows_on_page(glyphs, dividers, key_index, key_pattern, box, bool(key_at_top))
        for band_top, band_bottom, spill in bands:
            band = [g for g in glyphs if band_top <= g.cy < band_bottom]
            if not band:
                continue
            if spill and rows:
                _merge_spill(rows[-1], band, columns, layout)
                continue
            rows.append(_build_row(band, columns, dividers, source, page, transform,
                                   (box[0], band_top, box[2], band_bottom), page_reasons, layout))

    if spec.get("end_marker") and rows and not stopped:
        issues.append({"code": "end_not_found", "page": None,
                       "message": f"表格「{spec.get('name', spec['id'])}」找不到表尾標記，可能抓到多餘內容"})
    issues.extend(_check_sequence(rows, key_id))
    return {"id": spec["id"], "name": spec.get("name", spec["id"]),
            "columns": [{"id": c["id"], "name": c.get("name", c["id"])} for c in columns],
            "rows": rows, "issues": issues}


def _key_lines(glyphs, dividers, key_index, key_pattern):
    left, right = dividers[key_index], dividers[key_index + 1]
    candidates = group_lines([g for g in glyphs if left <= g.cx < right])
    return [line for line in candidates if re.search(key_pattern, line_text(line).strip())]


def _rows_on_page(glyphs, dividers, key_index, key_pattern, box, key_at_top):
    if key_index is None:  # 沒有項次欄：每一行文字就是一列
        return [(min(g.y0 for g in line) - 1e-4, max(g.y1 for g in line) + 1e-4, False)
                for line in group_lines(glyphs)]
    keys = _key_lines(glyphs, dividers, key_index, key_pattern)
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
    joined = ("\n" if column.get("join") == "newline" else " ").join(lines).strip()
    value, reasons = shape_value(joined, lines, column)
    if crossed:
        reasons.append(crossed if isinstance(crossed, str) else "crosses_column")
    confidence = _confidence(glyphs) if glyphs else 0.0
    if glyphs and confidence < OCR_MIN_CONFIDENCE:
        reasons.append("ocr_low_confidence")
    actual = "ocr" if any(g.source == "ocr" for g in glyphs) else source
    return make_value(column, value, actual, confidence, extra_reasons + reasons, page.index, box, transform)


def _split_chunks(line: list[Glyph]) -> list[list[Glyph]]:
    """把一行切成一段段文字。字距小的視為同一段，兩欄之間的空白才算分開。"""
    widths = sorted(g.width for g in line if g.width > 0)
    gap = (widths[len(widths) // 2] if widths else 0.005) * 1.5
    chunks = [[line[0]]]
    for prev, cur in zip(line, line[1:]):
        same_ocr_line = cur.line >= 0 and cur.line == prev.line
        if cur.x0 - prev.x1 > gap and not same_ocr_line:
            chunks.append([])
        chunks[-1].append(cur)
    return chunks


def _band_of(x: float, dividers: list[float]) -> int:
    for i in range(len(dividers) - 1):
        if x < dividers[i + 1]:
            return i
    return len(dividers) - 2


def _detect_alignment(whole: dict[int, list[list[Glyph]]]) -> dict[int, tuple[str, float]]:
    """從完整落在欄內的內容，判斷這一欄靠哪邊：哪一邊比較整齊就靠哪一邊，並記下對齊線位置。"""
    aligned: dict[int, tuple[str, float]] = {}
    for band, chunks in whole.items():
        if len(chunks) < 2:
            continue
        lefts = sorted(c[0].x0 for c in chunks)
        rights = sorted(c[-1].x1 for c in chunks)
        spread_left, spread_right = lefts[-1] - lefts[0], rights[-1] - rights[0]
        if abs(spread_left - spread_right) > 0.002:
            side, edges = ("left", lefts) if spread_left < spread_right else ("right", rights)
            aligned[band] = (side, edges[len(edges) // 2])
    return aligned


def _choose_band(chunk: list[Glyph], first: int, last: int, dividers: list[float],
                 aligned: dict[int, tuple[str, float]]) -> tuple[int, bool]:
    """跨欄的一段文字歸給誰。回傳 (直欄, 是否沒有把握)。

    靠左的欄，內容的左緣會對齊那一欄；靠右的欄則是右緣。貼齊對齊線的一邊就是它的欄。
    """
    left, right = chunk[0].x0, chunk[-1].x1
    tolerance = chunk[0].width * 1.5
    fits_first = first in aligned and aligned[first][0] == "left" and abs(left - aligned[first][1]) <= tolerance
    fits_last = last in aligned and aligned[last][0] == "right" and abs(right - aligned[last][1]) <= tolerance
    if fits_first != fits_last:
        return (first if fits_first else last), False
    overlaps = [min(right, dividers[i + 1]) - max(left, dividers[i]) for i in range(first, last + 1)]
    return first + overlaps.index(max(overlaps)), True


def _assign_chunks(glyphs: list[Glyph], dividers: list[float]) -> dict[int, tuple[int, object]]:
    """以「一段文字」為單位分欄，長內容跨到隔壁欄時才不會被切成兩半。

    回傳 {id(字): (直欄, 標記)}，標記不為空時代表這段需要人確認。
    """
    placed: list[tuple[list[Glyph], int, int, int]] = []  # (文字, 開始欄, 結束欄, 行號)
    whole: dict[int, list[list[Glyph]]] = {}
    for number, line in enumerate(group_lines(glyphs)):
        for chunk in _split_chunks(line):
            first = _band_of(chunk[0].x0 + chunk[0].width * 0.3, dividers)
            last = _band_of(chunk[-1].x1 - chunk[-1].width * 0.3, dividers)
            placed.append((chunk, first, last, number))
            if first == last:
                whole.setdefault(first, []).append(chunk)
    aligned = _detect_alignment(whole)

    decided = []
    for chunk, first, last, number in placed:
        if first == last:
            decided.append((chunk, first, number, None))
            continue
        band, unsure = _choose_band(chunk, first, last, dividers, aligned)
        decided.append((chunk, band, number, "crosses_column" if unsure else None))

    seen: dict[tuple[int, int], int] = {}
    for _chunk, band, number, _flag in decided:
        seen[(number, band)] = seen.get((number, band), 0) + 1
    layout: dict[int, tuple[int, object]] = {}
    for chunk, band, number, flag in decided:
        crossed = any(g.clipped for g in chunk)
        if seen[(number, band)] > 1:
            flag = "column_collision"
        elif crossed and not flag:
            flag = "crosses_column"
        for g in chunk:
            layout[id(g)] = (band, flag)
    return layout


def _split_bands(band_glyphs, layout, count):
    cells = [[] for _ in range(count)]
    flags: list[object] = [None] * count
    for g in band_glyphs:
        band, flag = layout[id(g)]
        cells[band].append(g)
        flags[band] = flags[band] or flag
    return cells, flags


def _build_row(band, columns, dividers, source, page, transform, box, reasons, layout) -> dict:
    cells, flags = _split_bands(band, layout, len(dividers) - 1)
    row = {"page": page.index + 1, "cells": {}}
    for index, column in enumerate(columns):
        i = _band(column, index)
        cell_box = (dividers[i], box[1], dividers[i + 1], box[3])
        row["cells"][column["id"]] = _cell(column, cells[i], source, page, transform,
                                           cell_box, flags[i], list(reasons))
    return row


def _merge_spill(row, band, columns, layout) -> None:
    count = max(_band(c, i) for i, c in enumerate(columns)) + 1
    count = max([count] + [layout[id(g)][0] + 1 for g in band])
    cells, _ = _split_bands(band, layout, count)
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
