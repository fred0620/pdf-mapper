"""解析範本（JSON）的讀寫、檢查與完成處理。格式說明見 docs/template-format.md。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import ocr as ocr_engine
from .align import Transform, align_page, box_center, find_text, make_patch
from .document import Document, Page, expand, group_lines, is_garbled, line_text

try:  # Python 3.11 起移到 re 底下
    from re import _constants as _sre
    from re import _parser as _sre_parse
except ImportError:  # pragma: no cover
    import sre_constants as _sre
    import sre_parse as _sre_parse

SCHEMA_VERSION = 1
MAX_PATTERN_LENGTH = 500
_REPEATS = {_sre.MAX_REPEAT, _sre.MIN_REPEAT}
FIELD_KINDS = {"key_value", "position"}
PAGE_RULES = {"first", "rest", "last", "all"}


def rule_matches(rule: str, index: int, total: int) -> bool:
    if rule == "first":
        return index == 0
    if rule == "rest":
        return index > 0
    if rule == "last":
        return index == total - 1
    if rule == "all":
        return True
    if rule.startswith("page:"):
        return index == int(rule.split(":")[1]) - 1
    return False


def _check_box(box, where: str, errors: list[str]) -> None:
    valid = (
        isinstance(box, (list, tuple)) and len(box) == 4
        and all(isinstance(v, (int, float)) for v in box)
        and box[0] < box[2] and box[1] < box[3]
    )
    if not valid:
        errors.append(f"{where} 的範圍不正確")


def _check_rule(rule, where: str, errors: list[str]) -> None:
    if rule not in PAGE_RULES and not re.fullmatch(r"page:\d+", str(rule)):
        errors.append(f"{where} 的頁面規則不正確：{rule}")


def _is_repeat(op, av) -> bool:
    return op in _REPEATS and av[1] > 1


def _flatten(items) -> list:
    """把群組攤平成一串元素，方便看重複裡面有什麼。"""
    flat = []
    for op, av in items:
        if op is _sre.SUBPATTERN:
            flat.extend(_flatten(av[-1]))
        else:
            flat.append((op, av))
    return flat


def _has_inner_repeat(op, av) -> bool:
    if _is_repeat(op, av):
        return True
    if op is _sre.BRANCH:
        return any(any(_has_inner_repeat(o, a) for o, a in _flatten(branch)) for branch in av[1])
    return False


def _nested_repeat(items) -> bool:
    """找「無上限的重複裡面又有重複，而且沒有固定字元隔開」，例如 (a+)+、(\\w+\\s?)+。

    這種寫法遇到比不中的長字串時會反覆回溯，時間呈指數增長，單一儲存格就能讓解析卡住。
    (\\d+,)+ 這類中間有固定字元的寫法不受影響。
    """
    for op, av in items:
        if op in _REPEATS:
            body = _flatten(av[2])
            if av[1] == _sre.MAXREPEAT and any(_has_inner_repeat(o, a) for o, a in body):
                anchored = any(not _has_inner_repeat(o, a) and _sre_parse.SubPattern(av[2].state, [(o, a)]).getwidth()[0] > 0
                               for o, a in body)
                if not anchored:
                    return True
            if _nested_repeat(av[2]):
                return True
        elif op is _sre.SUBPATTERN and _nested_repeat(av[-1]):
            return True
        elif op is _sre.BRANCH and any(_nested_repeat(branch) for branch in av[1]):
            return True
        elif op in (_sre.ASSERT, _sre.ASSERT_NOT) and _nested_repeat(av[1]):
            return True
    return False


def _check_regex(spec: dict, keys: tuple[str, ...], where: str, errors: list[str]) -> None:
    for key in keys:
        pattern = spec.get(key)
        if not pattern:
            continue
        if not isinstance(pattern, str) or len(pattern) > MAX_PATTERN_LENGTH:
            errors.append(f"{where} 的正規表達式太長（上限 {MAX_PATTERN_LENGTH} 字）")
            continue
        try:
            re.compile(pattern)
        except re.error as exc:
            errors.append(f"{where} 的正規表達式有誤：{pattern}（{exc}）")
            continue
        if _nested_repeat(_sre_parse.parse(pattern)):
            errors.append(f"{where} 的正規表達式可能讓解析卡住：{pattern}。"
                          "重複的內容裡又有重複（例如 (\\d+)+），請改成不巢狀的寫法（例如 \\d+）")


def validate(template: dict) -> list[str]:
    errors: list[str] = []
    if not template.get("template_id"):
        errors.append("範本缺少 template_id")
    if template.get("schema_version", SCHEMA_VERSION) > SCHEMA_VERSION:
        errors.append("這個範本由較新版本建立，請更新工具")
    ids: set[str] = set()
    for f in template.get("fields", []):
        where = f"欄位「{f.get('name', '?')}」"
        if f.get("id") in ids:
            errors.append(f"{where} 的 id 重複")
        ids.add(f.get("id"))
        if f.get("kind") not in FIELD_KINDS:
            errors.append(f"{where} 的類型不正確")
        _check_box(f.get("value_box"), where, errors)
        _check_regex(f, ("extract", "pattern"), where, errors)
        _check_rule(f.get("page_rule", "first"), where, errors)
        if f.get("kind") == "key_value":
            _check_box((f.get("label") or {}).get("box"), f"{where} 的標題", errors)
        if f.get("continuation"):
            _check_box(f["continuation"].get("box"), f"{where} 的接續範圍", errors)
    for t in template.get("tables", []):
        where = f"表格「{t.get('name', '?')}」"
        if t.get("id") in ids:
            errors.append(f"{where} 的 id 重複")
        ids.add(t.get("id"))
        columns = t.get("columns", [])
        _check_regex(t, ("key_pattern", "stop_pattern"), where, errors)
        for column in columns:
            _check_regex(column, ("extract", "pattern"), f"{where} 的欄「{column.get('name', '?')}」", errors)
        if not columns:
            errors.append(f"{where} 沒有欄")
        if not t.get("regions"):
            errors.append(f"{where} 沒有範圍")
        for region in t.get("regions", []):
            _check_box(region.get("box"), where, errors)
            _check_rule(region.get("page_rule", "first"), where, errors)
            bands = len(region.get("dividers", [])) - 1
            needed = max((c.get("band", i) for i, c in enumerate(columns)), default=0) + 1
            if bands < needed:
                errors.append(f"{where} 的分隔線數量與欄數不符")
            if region.get("header"):
                _check_box(region["header"].get("box"), f"{where} 的表頭", errors)
        if t.get("end_marker"):
            _check_box(t["end_marker"].get("box"), f"{where} 的表尾標記", errors)
        key = t.get("key_column")
        if key and key not in {c.get("id") for c in columns}:
            errors.append(f"{where} 的列判斷欄不存在")
    return errors


def load(path: str | Path) -> dict:
    template = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate(template)
    if errors:
        raise ValueError("；".join(errors))
    return template


def save(template: dict, path: str | Path) -> Path:
    errors = validate(template)
    if errors:
        raise ValueError("；".join(errors))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def collect_anchors(template: dict) -> list[dict]:
    """定位點來自兩處：手動加的定位點，以及「有標題的欄位」的標題。"""
    anchors = list(template.get("anchors", []))
    for f in template.get("fields", []):
        if f.get("kind") == "key_value" and f.get("label"):
            label = f["label"]
            anchors.append({
                "id": f"label:{f['id']}",
                "page_rule": f.get("page_rule", "first"),
                "ref_page": f.get("ref_page", 0),
                **label,
            })
    return anchors


def finalize(template: dict, reference: Document, pages: set[int] | None = None) -> dict:
    """用基準範例補齊每個定位點的影像圖塊與文字中心，之後解析就不用再開基準檔。

    pages 有指定時只補這幾頁（換基準時只補實際換算過的頁面）。
    """
    label_items = [f["label"] | {"ref_page": f.get("ref_page", 0), "_owner": f}
                   for f in template.get("fields", []) if f.get("kind") == "key_value" and f.get("label")]
    marker_items = []
    for table in template.get("tables", []):
        for region in table.get("regions", []):
            if region.get("header"):
                marker_items.append(region["header"] | {"ref_page": region.get("ref_page", 0),
                                                        "_owner": {"label": region["header"]}})
        if table.get("end_marker"):
            marker_items.append(table["end_marker"] | {"_owner": {"label": table["end_marker"]}})
    for item in template.get("anchors", []) + label_items + marker_items:
        page_index = item.get("ref_page", 0)
        if page_index >= len(reference) or (pages is not None and page_index not in pages):
            continue  # 這份基準沒有這一頁：保留原本的圖塊，不拿別頁的影像頂替
        page = reference.pages[page_index]
        target = item["_owner"]["label"] if "_owner" in item else item
        box = tuple(target["box"])
        if not target.get("patch"):
            target["patch"] = make_patch(page, box)
        if target.get("text") and not target.get("text_center"):
            found = find_text(page.glyphs, target["text"], near=box_center(box))
            if not found and ocr_engine.available():
                found = find_text(page.ocr(), target["text"], near=box_center(box), fuzzy=True)
            target["text_center"] = list(found[:2]) if found else list(box_center(box))
    if template.get("anchors") is None:
        template["anchors"] = []
    return template


def suggest_anchors(page: Page, avoid: list, rule: str, limit: int = 6) -> list[dict]:
    """自動挑分散在頁面四周、不在資料區內的固定文字當定位點。"""
    glyphs = [g for g in page.ocr()] if ocr_engine.available() else list(page.glyphs)
    candidates = []
    for line in group_lines(glyphs):
        # OCR 可能把多欄併成一行，切成不含大間隔的片段
        segment: list = []
        segments = []
        for g in line:
            if segment and g.x0 - segment[-1].x1 > g.height * 1.2:
                segments.append(segment)
                segment = []
            segment.append(g)
        segments.append(segment)
        for part in segments:
            text = line_text(part)
            if len(part) < 2 or is_garbled(text) or sum(g.score for g in part) / len(part) < 0.9:
                continue
            if not any("一" <= c <= "鿿" or c.isalpha() for c in text):
                continue
            box = (min(g.x0 for g in part), min(g.y0 for g in part),
                   max(g.x1 for g in part), max(g.y1 for g in part))
            if any(_overlaps(box, tuple(a)) for a in avoid):
                continue
            candidates.append((text, expand(box, 0.003)))
    picked: list[tuple[str, tuple]] = []
    targets = [(0.1, 0.1), (0.9, 0.1), (0.1, 0.9), (0.9, 0.9), (0.5, 0.5), (0.5, 0.1)]
    for tx, ty in targets[:limit]:
        pool = [c for c in candidates if c not in picked]
        if not pool:
            break
        picked.append(min(pool, key=lambda c: (box_center(c[1])[0] - tx) ** 2 + (box_center(c[1])[1] - ty) ** 2))
    return [
        {"id": f"auto_{page.index}_{i}", "text": text, "box": [round(v, 5) for v in box],
         "page_rule": rule, "ref_page": page.index}
        for i, (text, box) in enumerate(picked)
    ]


def _overlaps(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# ---------- 換基準時重新對位 ----------
# 範本的座標屬於建立時的基準範例。換一份格式略有差異的 PDF 當基準時，
# 用解析時同一套定位點對位，把座標一次換算成新基準的座標，之後照常編輯。
SAME_PAGE = 0.002  # 換算後移動不到這個距離就當作同一份，不改座標也不重抓圖塊


def _items_on(template: dict, page: int) -> list[tuple[dict, str]]:
    """這一頁上所有帶座標的東西：(所在的 dict, 座標的鍵)。"""
    items = []
    for f in template.get("fields", []):
        if f.get("ref_page", 0) == page:
            items.append((f, "value_box"))
            if f.get("label"):
                items.append((f["label"], "box"))
        if f.get("continuation") and f["continuation"].get("ref_page", 0) == page:
            items.append((f["continuation"], "box"))
    for a in template.get("anchors", []):
        if a.get("ref_page", 0) == page:
            items.append((a, "box"))
    for t in template.get("tables", []):
        for r in t.get("regions", []):
            if r.get("ref_page", 0) == page:
                items.append((r, "box"))
                if r.get("header"):
                    items.append((r["header"], "box"))
        if t.get("end_marker") and t["end_marker"].get("ref_page", 0) == page:
            items.append((t["end_marker"], "box"))
    return items


def _pages_used(template: dict) -> set[int]:
    pages = set()
    for f in template.get("fields", []):
        pages.add(f.get("ref_page", 0))
        if f.get("continuation"):
            pages.add(f["continuation"].get("ref_page", 0))
    for a in template.get("anchors", []):
        pages.add(a.get("ref_page", 0))
    for t in template.get("tables", []):
        pages.update(r.get("ref_page", 0) for r in t.get("regions", []))
        if t.get("end_marker"):
            pages.add(t["end_marker"].get("ref_page", 0))
    return pages


def _round_box(box) -> list[float]:
    x0, y0, x1, y1 = (min(1.0, max(0.0, round(v, 5))) for v in box)
    return [x0, y0, x1, y1]


def _movement(transform: Transform, items: list[tuple[dict, str]]) -> float:
    worst = 0.0
    for owner, key in items:
        for x, y in ((owner[key][0], owner[key][1]), (owner[key][2], owner[key][3])):
            nx, ny = transform.point(x, y)
            worst = max(worst, abs(nx - x), abs(ny - y))
    return worst


def _apply(transform: Transform, template: dict, page: int) -> None:
    for owner, key in _items_on(template, page):
        owner[key] = _round_box(transform.box(tuple(owner[key])))
        owner.pop("patch", None)  # 圖塊和文字中心改由新基準重新擷取
        owner.pop("text_center", None)
    for t in template.get("tables", []):
        for r in t.get("regions", []):
            if r.get("ref_page", 0) == page and r.get("dividers"):
                y = (r["box"][1] + r["box"][3]) / 2
                inner = [round(transform.point(x, y)[0], 5) for x in r["dividers"][1:-1]]
                r["dividers"] = [r["box"][0], *sorted(inner), r["box"][2]]


def rebase(template: dict, reference: Document, include_weak: bool = False) -> dict:
    """依新基準對位，回傳換算後的範本與每一頁的結果。

    每頁只用定義在這一頁的定位點；這一頁沒有時，才用頁面規則適用的定位點。
    對位好的頁面才換算；不穩的頁面要使用者同意（include_weak）；對不上的不動。
    基準沒有的頁面一律保留原樣，等換回夠長的範例再處理。
    """
    template = json.loads(json.dumps(template))
    anchors = collect_anchors(template)
    total = len(reference)
    used = _pages_used(template)
    pages = []
    for index in sorted(p for p in used if p < total):
        own = [a for a in anchors if a.get("ref_page", 0) == index]
        candidates = own or [a for a in anchors if rule_matches(a.get("page_rule", "first"), index, total)]
        transform = align_page(reference.pages[index], candidates, allow_ocr=True)
        status = transform.quality  # good / weak / none / fixed
        if status in ("good", "weak") and _movement(transform, _items_on(template, index)) < SAME_PAGE:
            status = "same"
        applied = status == "good" or (status == "weak" and include_weak)
        if applied:
            _apply(transform, template, index)
        pages.append({"page": index + 1, "status": status, "applied": applied,
                      "found": transform.found, "total": transform.total})
    # 換算過的頁面立刻從新基準重抓圖塊，下次再對位時才會以新基準為準，不會一直累積誤差
    finalize(template, reference, {p["page"] - 1 for p in pages if p["applied"]})
    beyond = sorted(p + 1 for p in used if p >= total)
    return {"template": template, "pages": pages, "beyond": beyond}
