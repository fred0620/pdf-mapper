"""解析範本（JSON）的讀寫、檢查與完成處理。格式說明見 docs/template-format.md。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import ocr as ocr_engine
from .align import box_center, find_text, make_patch
from .document import Document, Page, expand, group_lines, is_garbled, line_text

SCHEMA_VERSION = 1
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
        _check_rule(f.get("page_rule", "first"), where, errors)
        if f.get("kind") == "key_value":
            _check_box((f.get("label") or {}).get("box"), f"{where} 的標題", errors)
    for t in template.get("tables", []):
        where = f"表格「{t.get('name', '?')}」"
        if t.get("id") in ids:
            errors.append(f"{where} 的 id 重複")
        ids.add(t.get("id"))
        columns = t.get("columns", [])
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


def finalize(template: dict, reference: Document) -> dict:
    """用基準範例補齊每個定位點的影像圖塊與文字中心，之後解析就不用再開基準檔。"""
    label_items = [f["label"] | {"ref_page": f.get("ref_page", 0), "_owner": f}
                   for f in template.get("fields", []) if f.get("kind") == "key_value" and f.get("label")]
    for item in template.get("anchors", []) + label_items:
        page_index = min(item.get("ref_page", 0), len(reference) - 1)
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
