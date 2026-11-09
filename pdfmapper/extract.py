"""依範本取值。這一層只忠實取值與標記疑點，不改寫資料內容。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from statistics import median

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
    "possible_row_split": "這頁開頭的內容可能屬於上一列，請確認",
    "row_incomplete": "這一列缺必要欄位，可能跨頁或切錯列",
    "value_spans_pages": "內容接到下一頁，已合併，請確認",
    "split_count_mismatch": "段數和設定不符，已留空，請看原始內容",
    "extract_no_match": "擷取規則比對不到，已留空，請看原始內容",
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
            value = (match.group(1) if match.groups() else match.group(0)) or ""
        else:  # 擷取失敗就留空，不把整段內容塞進欄位
            reasons.append("extract_no_match")
            return "", reasons
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
        reasons = [r for r in reasons if r in ("ocr_unavailable", "split_count_mismatch", "extract_no_match")]
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


def _read_continuation(spec: dict, page_after: Page | None, transform: Transform | None,
                       use_ocr: bool) -> tuple[Reading | None, Box | None]:
    """讀欄位在下一頁的接續範圍。"""
    if page_after is None or not spec.get("continuation"):
        return None, None
    box = transform.box(tuple(spec["continuation"]["box"]))
    reading = read_box(page_after, box, spec.get("source", "auto"), False, use_ocr)
    return (reading, box) if reading.text else (None, None)


def extract_field(spec: dict, pages: list[Page], transforms: dict[int, Transform],
                  use_ocr: bool = True, all_pages: list[Page] | None = None) -> dict:
    last = None
    all_pages = all_pages or pages
    for page in pages:
        transform = transforms[page.index]
        box, reasons = locate_value_box(spec, transform)
        reading = read_box(page, box, spec.get("source", "auto"), bool(spec.get("verify")), use_ocr)
        following = all_pages[page.index + 1] if page.index + 1 < len(all_pages) else None
        extra, extra_box = (None, None)
        if reading.text and following is not None:
            extra, extra_box = _read_continuation(spec, following, transforms[following.index], use_ocr)
        lines = reading.lines + (extra.lines if extra else [])
        joiner = "\n" if spec.get("join") == "newline" else " "
        value, shape_reasons = shape_value(joiner.join(lines).strip(), lines, spec)
        if extra:
            reasons = reasons + extra.reasons + ["value_spans_pages"]
        result = make_value(spec, value, reading.source, reading.confidence,
                            reasons + reading.reasons + shape_reasons, page.index, box, transform)
        if extra:
            result["extra_boxes"] = [{"page": following.index + 1, "box": [round(v, 5) for v in extra_box]}]
        if spec.get("extract") and reading.text:
            result["raw"] = joiner.join(lines).strip()
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


@dataclass
class _Piece:
    """一列在某一頁上的內容。全部收集完才組成儲存格，跨頁合併時才能照欄位設定處理。"""
    glyphs: list
    layout: dict
    dividers: list
    source: str
    page: Page
    transform: Transform
    box: Box
    reasons: list
    lead_limit: float | None = None  # 這頁開頭有歸屬疑慮時，這條線以上的內容要確認
    judged: bool = False  # 併到上一列是推測的（整頁沒有項次、或依必填欄位切開），不是版面確定的


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
    # 用字距分段的直欄，一行本來就會有好幾段，不檢查搶欄
    gap_bands = {_band(c, i) for i, c in enumerate(columns) if c.get("part_by") == "gap"}
    rows: list[list[_Piece]] = []  # 每一列由一到多個片段組成，跨頁時片段來自不同頁
    above_key: list[float] = []    # 各列在項次上方有多高，用來判斷下一頁開頭是否異常
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
        layout = _assign_chunks(glyphs, dividers, gap_bands)
        piece = lambda top, bottom, group: _Piece(group, layout, dividers, source, page, transform,
                                                  (box[0], top, box[2], bottom), page_reasons)
        bands = _rows_on_page(glyphs, dividers, key_index, key_pattern, box, bool(key_at_top))

        lead_limit = None
        if rows and not key_at_top and key_index is not None:
            bands, lead_limit = _resolve_lead(rows, columns, glyphs, dividers, key_index, key_pattern,
                                                  bands, above_key)
        for number, (band_top, band_bottom, spill) in enumerate(bands):
            group = [g for g in glyphs if band_top <= g.cy < band_bottom]
            if not group:
                continue
            if spill and rows:
                added = piece(band_top, band_bottom, group)
                added.judged = spill != "top"  # 項次在第一行時，第一個項次上方必定屬於上一列
                rows[-1].append(added)
                continue
            built = piece(band_top, band_bottom, group)
            if number == 0:
                built.lead_limit = lead_limit
            rows.append([built])
            if not key_at_top and key_index is not None:
                keys = _key_lines(group, dividers, key_index, key_pattern)
                if keys:
                    above_key.append(min(g.y0 for g in keys[0]) - min(g.y0 for g in group))

    finished = [_finish_row(pieces, columns) for pieces in rows]
    for column in columns:  # 有內容但整份都沒抽到，多半是規則不對，要提醒
        if not (column.get("start") or column.get("extract") or column.get("part_by")):
            continue
        cells = [row["cells"][column["id"]] for row in finished]
        if any(cell.get("raw") for cell in cells) and not any(cell["value"] for cell in cells):
            issues.append({"code": "column_all_blank", "page": None,
                           "message": f"「{column.get('name', column['id'])}」整份都沒有抓到值，請確認取值規則"})
    if spec.get("end_marker") and finished and not stopped:
        issues.append({"code": "end_not_found", "page": None,
                       "message": f"表格「{spec.get('name', spec['id'])}」找不到表尾標記，可能抓到多餘內容"})
    issues.extend(_check_sequence(finished, key_id))
    return {"id": spec["id"], "name": spec.get("name", spec["id"]),
            "columns": [{"id": c["id"], "name": c.get("name", c["id"])} for c in columns],
            "rows": finished, "issues": issues}


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
        return [(box[1], box[3] + 1e-4, "page")]
    bands = [(top, bottom, False)
             for top, bottom in _boundaries(keys, glyphs, box[1], box[3] + 1e-4, key_at_top)]
    if key_at_top:
        first_top = min(g.y0 for g in keys[0]) - 1e-4
        bands[0] = (first_top, bands[0][1], False)
        bands.insert(0, (box[1], first_top, "top"))
    return bands


def _band(column: dict, index: int) -> int:
    """一個直欄可拆成多個輸出欄（例如同格上下兩行），band 指向實際的直欄。"""
    return column.get("band", index)


KEY_SEPARATORS = ":：.．=＝"  # 開頭和值之間常見的分隔符號，有沒有、全形半形都可以


def _char_class(char: str) -> str:
    """一個字和它的全形（或半形）寫法。"""
    variants = {char}
    if "!" <= char <= "~":
        variants.add(chr(ord(char) + 0xFEE0))
    elif "！" <= char <= "～":
        variants.add(chr(ord(char) - 0xFEE0))
    return "[" + "".join(re.escape(v) for v in sorted(variants)) + "]"


def _start_regex(start: str, strict: bool = False) -> str:
    """開頭文字的比對規則。實務上 PDF 的空白、標點和全形半形常跟設定的不一樣，所以：

    空白多寡不拘；開頭文字裡的標點可有可無；全形半形視為相同；
    開頭後面接的冒號、句點、等號會一起略過，不會帶進值裡。
    英數開頭時，前面不能緊接英數。strict 時後面也不能緊接英文字母，避免 No 比對到 Note；
    找不到才放寬，讓 ECCN5A992 這種沒有分隔的寫法也抓得到。
    """
    core = start.strip().rstrip(KEY_SEPARATORS + " \t")
    parts = []
    for char in core:
        if char.isspace():
            continue
        piece = _char_class(char)
        parts.append(piece if char.isalnum() else piece + "?")
    if not parts:
        return ""
    lead = core.lstrip()[0]
    guard = r"(?<![A-Za-z0-9Ａ-Ｚａ-ｚ０-９])" if lead.isascii() and lead.isalnum() else ""
    separators = "".join(_char_class(c)[1:-1] for c in KEY_SEPARATORS)
    tail = r"(?![A-Za-zＡ-Ｚａ-ｚ])" if strict and core[-1].isascii() and core[-1].isalpha() else ""
    return guard + r"\s*".join(parts) + tail + rf"(?:\s*[{separators}])*"


def _find_start(start: str, text: str, taken: list[tuple[int, int]]):
    """找開頭文字第一次出現、且不在其他（較長）開頭裡面的位置。"""
    for strict in (True, False):
        pattern = _start_regex(start, strict)
        for match in re.finditer(pattern, text, re.IGNORECASE) if pattern else []:
            if not any(lo <= match.start() and match.end() <= hi for lo, hi in taken):
                return match
    return None


def split_sections(text: str, starts: list[str]) -> dict[str, str]:
    """依開頭文字把一格切成多段，每段到下一個已設定的開頭為止。比對不分大小寫。

    長的開頭先找，短的開頭落在長的裡面（Weight 在 Net Weight 裡）時改找下一個位置。
    """
    found, taken = [], []
    for start in sorted(starts, key=lambda item: -len("".join(item.split()))):
        match = _find_start(start, text, taken)
        if match:
            found.append((match.start(), match.end(), start))
            taken.append((match.start(), match.end()))
    found.sort()
    sections = {}
    for (_, end, start), following in zip(found, found[1:] + [(len(text), 0, "")]):
        sections[start] = text[end:following[0]]
    return sections


def read_after_start(lines: list[str], column: dict, starts: list[str]) -> str:
    """取出開頭文字後面的值，開頭文字本身和這格的其他內容都不會帶進來。

    end 決定值到哪裡結束：line 到這一行結束；word 到第一個空白；
    next 到下一個已設定的開頭為止，中間的折行會接回來。
    """
    text = "\n".join(" ".join(line.split()) for line in lines)
    section = split_sections(text, starts).get(column["start"], "").strip()
    end = column.get("end", "next")
    if end == "line":
        return section.split("\n", 1)[0].strip()
    if end == "word":
        return section.split()[0] if section else ""
    return " ".join(section.split())


def _plain_spec(column: dict) -> dict:
    """已經切好內容後，只留下類型和格式檢查。"""
    return {key: value for key, value in column.items() if key in ("type", "pattern")}


def _cell_value(column, joined, lines, starts, parts) -> tuple[str, list[str]]:
    """依欄位的取值方式取出內容。沒有設定時整格保留，這也是最安全的預設。"""
    if column.get("start"):
        value = read_after_start(lines, column, list(starts))
        return shape_value(value, [value], _plain_spec(column))
    if column.get("extract") and not column.get("pick_line"):
        match = re.search(column["extract"], joined)
        if not match:  # 這格沒有這筆資料。必有的欄位請勾「每一列都一定有這欄」
            return "", []
        value = ((match.group(1) if match.groups() else match.group(0)) or "").strip()
        return shape_value(value, [value], _plain_spec(column))
    if column.get("part_by"):
        tokens, peers = parts[column["part_by"]]
        if not joined:
            return "", []
        numbers = sorted(c.get("part", 1) for c in peers)
        if len(tokens) == len(peers) and numbers == list(range(1, len(peers) + 1)):
            token = tokens[column.get("part", 1) - 1]
            return shape_value(token, [token], _plain_spec(column))
        # 段數不對就不猜：留空並標記，原始內容保留在 raw
        return "", ["split_count_mismatch"]
    return shape_value(joined, lines, column)


def _compact(text: str) -> str:
    return "".join(text.split())


def _overlaps(value: str, chunk: str, least: int = 4) -> bool:
    """值裡有沒有用到這段文字：互相包含，或有一段夠長的共同內容（值只取到這段的一部分）。"""
    v, c = _compact(value), _compact(chunk)
    if not v or not c:
        return False
    if c in v or v in c:
        return True
    match = SequenceMatcher(None, v, c, autojunk=False).find_longest_match(0, len(v), 0, len(c))
    return match.size >= least


def _relevant_flag(column: dict, value: str, line_count: int, spans: list) -> str | None:
    """這格的分欄疑點，只在疑點那段文字真的進到這個欄位的值時才算數。

    同一格可能拆成好幾個輸出欄（第幾行、開頭文字、正規表達式），
    某一行跨欄不代表其他行取出的值有問題。
    """
    if not value:
        return None
    picked = None
    pick = column.get("pick_line")
    if pick and not column.get("start") and not column.get("part_by"):
        picked = pick - 1 if pick > 0 else line_count + pick
    for line_index, flag, text in spans:
        if picked is not None and line_index != picked:
            continue
        if _overlaps(value, text):
            return flag
    return None


def _cell(column, lines, glyphs, source, page, transform, box, spans, extra_reasons, starts=(), parts=None):
    joined = ("\n" if column.get("join") == "newline" else " ").join(lines).strip()
    value, reasons = _cell_value(column, joined, lines, starts, parts or {})
    crossed = _relevant_flag(column, value, len(lines), spans or [])
    if crossed:
        reasons.append(crossed)
    confidence = _confidence(glyphs) if glyphs else 0.0
    if glyphs and confidence < OCR_MIN_CONFIDENCE:
        reasons.append("ocr_low_confidence")
    spec = column
    if column.get("row_required"):
        spec = column | {"required": True}
        if not value:
            reasons.append("row_incomplete")
    actual = "ocr" if any(g.source == "ocr" for g in glyphs) else source
    cell = make_value(spec, value, actual, confidence, extra_reasons + reasons, page.index, box, transform)
    if column.get("start") or column.get("extract") or column.get("part_by"):
        cell["raw"] = joined  # 試抓時顯示原始內容，方便調整規則
    return cell


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


COLLISION_USUAL_SHARE = 0.2  # 一欄裡有這個比例以上的行都有多段，就當作這欄本來的格式


def _assign_chunks(glyphs: list[Glyph], dividers: list[float],
                   gap_bands: set[int] = frozenset()) -> dict[int, tuple[int, object]]:
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

    flags = _collisions(decided, dividers, aligned, gap_bands)
    layout: dict[int, tuple[int, object]] = {}
    for index, (chunk, band, _number, flag) in enumerate(decided):
        crossed = any(g.clipped for g in chunk)
        flag = flags.get(index) or flag or ("crosses_column" if crossed else None)
        for g in chunk:
            layout[id(g)] = (band, flag)
    return layout


def _collisions(decided, dividers, aligned, gap_bands) -> dict[int, str]:
    """同一行同一欄有兩段文字時，判斷是不是吃到隔壁欄的內容。回傳 {第幾段: 標記}。

    格子裡本來就常有大空白（單位和數字、撐開的字距），所以只在三個條件都成立時標記：
    這欄不是用字距分段；這欄平常一行只有一段；多出來的那段貼著分隔線，
    而且不是貼著這欄自己的對齊線。
    """
    groups: dict[tuple[int, int], list[int]] = {}
    for index, (_chunk, band, number, _flag) in enumerate(decided):
        groups.setdefault((number, band), []).append(index)
    lines: dict[int, int] = {}
    multi: dict[int, int] = {}
    for (_number, band), members in groups.items():
        lines[band] = lines.get(band, 0) + 1
        multi[band] = multi.get(band, 0) + (len(members) > 1)

    flags: dict[int, str] = {}
    last_band = len(dividers) - 2
    for (_number, band), members in groups.items():
        if len(members) < 2 or band in gap_bands:
            continue
        if multi[band] / lines[band] >= COLLISION_USUAL_SHARE:
            continue
        ordered = sorted(members, key=lambda i: decided[i][0][0].x0)
        own = aligned.get(band)
        left, right = decided[ordered[0]][0], decided[ordered[-1]][0]
        if band > 0 and _sticks_out(left[0].x0, dividers[band], left[0].width, own, "left"):
            flags[ordered[0]] = "column_collision"
        if band < last_band and _sticks_out(right[-1].x1, dividers[band + 1], right[-1].width, own, "right"):
            flags[ordered[-1]] = "column_collision"
    return flags


def _sticks_out(edge: float, divider: float, width: float, own, side: str) -> bool:
    """這段的外緣貼著分隔線，又不是貼著這欄自己的對齊線，就可能是隔壁欄的內容。"""
    if abs(edge - divider) > width * 2:
        return False
    return not (own and own[0] == side and abs(edge - own[1]) <= width * 1.5)


def _split_bands(band_glyphs, layout, count):
    cells = [[] for _ in range(count)]
    for g in band_glyphs:
        cells[layout[id(g)][0]].append(g)
    return cells


def _flag_spans(cell_glyphs, layout, first_line: int) -> list[tuple[int, str, str]]:
    """這格每一行裡有疑點的文字：(第幾行, 疑點, 那段文字)。行號和 _text_lines 的順序一致。"""
    spans = []
    for number, line in enumerate(group_lines(cell_glyphs)):
        flagged: dict[str, list[Glyph]] = {}
        for g in line:
            flag = layout[id(g)][1]
            if flag:
                flagged.setdefault(flag, []).append(g)
        spans += [(first_line + number, flag, line_text(part)) for flag, part in flagged.items()]
    return spans


def _finish_row(pieces: list[_Piece], columns: list[dict]) -> dict:
    """把一列的所有片段組成儲存格。多行、第幾行和格式檢查都在這裡才套用。"""
    first = pieces[0]
    split = [_split_bands(p.glyphs, p.layout, len(p.dividers) - 1) for p in pieces]
    row = {"page": first.page.index + 1, "cells": {}}
    for index, column in enumerate(columns):
        i = _band(column, index)
        lines: list[str] = []
        glyphs: list[Glyph] = []
        gaps: list[str] = []
        spans: list[tuple[int, str, str]] = []
        extra_boxes = []
        used = 0       # 這格的內容來自幾頁
        lead = False   # 這格有內容落在這頁開頭有疑慮的範圍
        judged = False  # 這格有內容是推測併進來的
        for number, (piece, cells) in enumerate(zip(pieces, split)):
            if not cells[i]:
                continue
            used += 1
            judged = judged or piece.judged
            if piece.lead_limit is not None and any(g.cy < piece.lead_limit for g in cells[i]):
                lead = True
            spans += _flag_spans(cells[i], piece.layout, len(lines))
            lines += _text_lines(cells[i])  # 不同頁的座標不能放在一起分行
            glyphs += cells[i]
            gaps += [line_text(chunk) for line in group_lines(cells[i]) for chunk in _split_chunks(line)]
            if number:
                extra_boxes.append({"page": piece.page.index + 1, "box": [
                    round(v, 5) for v in (piece.dividers[i], piece.box[1], piece.dividers[i + 1], piece.box[3])]})
        # 只標實際受影響的格子：內容真的由兩頁合併、是推測併進來的，或落在開頭有疑慮的範圍
        reasons = (list(first.reasons) + (["row_spans_pages"] if used > 1 or judged else [])
                   + (["possible_row_split"] if lead else []))
        box = (first.dividers[i], first.box[1], first.dividers[i + 1], first.box[3])
        starts = [c["start"] for n, c in enumerate(columns) if _band(c, n) == i and c.get("start")]
        peers = [c for n, c in enumerate(columns) if _band(c, n) == i]
        parts = {
            "space": (" ".join(lines).split(), [c for c in peers if c.get("part_by") == "space"]),
            "gap": (gaps, [c for c in peers if c.get("part_by") == "gap"]),
        }
        cell = _cell(column, lines, glyphs, first.source, first.page, first.transform, box, spans, reasons,
                     starts, parts)
        if extra_boxes:
            cell["extra_boxes"] = extra_boxes
        row["cells"][column["id"]] = cell
    return row


def _resolve_lead(rows, columns, glyphs, dividers, key_index, key_pattern, bands, above_key):
    """項次在列中間時，判斷新一頁開頭、第一個項次上方的內容屬於誰。

    這段可能是這一頁第一列的上半部，也可能是上一頁最後一列的下半部。
    有設定「每列必有」時，看上一列完不完整；沒有就不猜，標記給人確認。
    回傳 (調整後的列範圍, 疑慮範圍的下緣)。下緣以上的內容要確認，沒有疑慮時為 None。
    """
    keys = _key_lines(glyphs, dividers, key_index, key_pattern)
    if not keys or not bands or bands[0][2]:
        return bands, None
    key_top = min(g.y0 for g in keys[0])
    height = max(g.height for g in keys[0])
    above = sorted((g for g in glyphs if g.cy < key_top - height * 0.3), key=lambda g: g.y0)
    if not above:
        return bands, None
    lead_height = key_top - above[0].y0
    if above_key and lead_height <= median(above_key) + height * 1.5:
        return bands, None  # 高度和平常一樣，就是這一列自己的上半部

    required = [c for c in columns if c.get("row_required")]
    if not required:
        return bands, key_top - height * 0.3
    previous = _finish_row(rows[-1], columns)
    if all(previous["cells"][c["id"]]["value"] for c in required):
        return bands, None

    # 上一列不完整：在項次上方最大的空白處切開，上半段併回上一列
    cut, reach, best = (above[-1].y1 + key_top) / 2, above[0].y1, 0.0
    for g in above[1:] + [_Top(key_top)]:
        if g.y0 - reach > best:
            best, cut = g.y0 - reach, (g.y0 + reach) / 2
        reach = max(reach, getattr(g, "y1", reach))
    top, bottom, _spill = bands[0]
    return [(top, cut, "lead"), (cut, bottom, False)] + bands[1:], None


@dataclass
class _Top:
    y0: float


SEQUENTIAL_SHARE = 0.6  # 至少這個比例的相鄰項次是 +1，才當作連號來檢查


def _check_sequence(rows, key_id) -> list[dict]:
    """項次跳號只當提示，不把儲存格標成需檢查。

    很多文件的項次本來就是 ID，不會照 1、2、3 排。大多數相鄰項次都是 +1 時，
    才把少數跳號當作可能漏列提醒；否則視為不是連號，不提示。
    """
    if not key_id:
        return []
    numbered = [(row, int(text)) for row in rows
                for text in [(row["cells"].get(key_id) or {}).get("value", "")] if text.isdigit()]
    steps = list(zip(numbered, numbered[1:]))
    if len(steps) < 2:
        return []
    consecutive = sum(after - before == 1 for (_, before), (_, after) in steps)
    if consecutive / len(steps) < SEQUENTIAL_SHARE:
        return []
    return [{"code": "sequence_gap", "level": "notice", "page": row["page"],
             "message": f"項次從 {before} 跳到 {after}，如果項次本來就不連號可忽略"}
            for (_, before), (row, after) in steps if after != before + 1]
