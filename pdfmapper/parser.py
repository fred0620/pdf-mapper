"""解析主流程：PDF + 範本 → 結構化結果與檢查報告。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterator

from .align import Transform, align_page
from .document import Document
from .extract import REASONS, extract_field, extract_table
from .template import collect_anchors, rule_matches

MIN_TEMPLATE_MATCH = 0.5
MATCH_PAGES = 3
SHORTLIST_MARGIN = 0.1
MAX_FINALISTS = 3
AMBIGUOUS_MARGIN = 0.03


def _anchors_for(anchors: list[dict], index: int, total: int) -> list[dict]:
    return [a for a in anchors if rule_matches(a.get("page_rule", "first"), index, total)]


def _align_all(doc: Document, template: dict, use_ocr: bool) -> dict[int, Transform]:
    anchors = collect_anchors(template)
    total = len(doc)
    return {page.index: align_page(page, _anchors_for(anchors, page.index, total), use_ocr)
            for page in doc.pages}


def _to_number(text: str) -> float | None:
    cleaned = re.sub(r"[,\s%]", "", text or "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _flag(value: dict | None, code: str) -> None:
    if value and code not in value["reasons"]:
        value["reasons"].append(code)
        if value["status"] == "ok":
            value["status"] = "review"


def _run_validations(template: dict, fields: dict, tables: dict, page_count: int) -> list[dict]:
    issues = []
    for rule in template.get("validations", []):
        kind = rule.get("type")
        target = fields.get(rule.get("equals") or rule.get("field"))
        if kind == "page_count":
            numbers = re.findall(r"\d+", (target or {}).get("value", ""))
            if numbers and int(numbers[-1]) != page_count:
                _flag(target, "sum_mismatch")
                issues.append({"code": "page_count", "page": None,
                               "message": f"單據標示共 {numbers[-1]} 頁，實際 {page_count} 頁"})
            continue
        if kind == "sum_column":
            table = tables.get(rule.get("table"))
            texts = [row["cells"].get(rule.get("column"), {}).get("value", "")
                     for row in (table or {}).get("rows", [])]
            label = f"「{rule.get('column')}」欄加總"
        elif kind == "sum_fields":
            texts = [fields.get(name, {}).get("value", "") for name in rule.get("fields", [])]
            label = "欄位加總"
        else:
            continue
        numbers = [_to_number(text) for text in texts]
        expected = _to_number((target or {}).get("value", ""))
        if expected is None or not numbers or None in numbers:
            issues.append({"code": "cannot_verify", "page": (target or {}).get("page"),
                           "message": f"{label}無法驗證，有數值讀不出來"})
            continue
        actual = sum(numbers)
        if abs(actual - expected) > rule.get("tolerance", 0.01):
            _flag(target, "sum_mismatch")
            issues.append({"code": "sum_mismatch", "page": target.get("page"),
                           "message": f"{label} {actual:,.2f}，與單據的 {expected:,.2f} 不符"})
    return issues


def iter_values(result: dict) -> Iterator[tuple[str, str, dict]]:
    """逐一列出結果中的每個值：(參照代號, 顯示名稱, 值)。"""
    for field in result.get("fields", []):
        yield f"f:{field['id']}", field["name"], field
    for table in result.get("tables", []):
        names = {c["id"]: c["name"] for c in table["columns"]}
        for r, row in enumerate(table["rows"]):
            for column, cell in row["cells"].items():
                yield f"t:{table['id']}:{r}:{column}", f"{table['name']} 第 {r + 1} 列 {names[column]}", cell


def find_value(result: dict, ref: str) -> dict | None:
    return next((value for key, _name, value in iter_values(result) if key == ref), None)


def summarize(result: dict) -> None:
    values = [value for _ref, _name, value in iter_values(result)]
    review = sum(v["status"] == "review" for v in values)
    missing = sum(v["status"] == "missing" for v in values)
    result["counts"] = {"total": len(values), "review": review, "missing": missing}
    if result.get("error"):
        result["status"] = "failed"
    elif missing or review or result.get("issues"):
        result["status"] = "review"
    else:
        result["status"] = "ok"


def parse_pdf(path: str | Path, template: dict, use_ocr: bool = True,
              progress: Callable[[str], None] | None = None) -> dict:
    path = Path(path)
    result: dict = {"file": path.name, "path": str(path), "template_id": template.get("template_id"),
                    "template_name": template.get("name") or template.get("template_id"),
                    "pages": 0, "fields": [], "tables": [], "issues": [], "align": []}
    try:
        with Document(path) as doc:
            total = len(doc)
            result["pages"] = total
            if progress:
                progress("對位中")
            transforms = _align_all(doc, template, use_ocr)
            result["align"] = [{"page": i + 1, **transforms[i].summary()} for i in range(total)]
            found = sum(t.found for t in transforms.values())
            expected = sum(t.total for t in transforms.values())
            result["match"] = round(found / expected, 3) if expected else None
            if expected and found / expected < MIN_TEMPLATE_MATCH:
                result["issues"].append({
                    "code": "wrong_template", "page": None,
                    "message": f"只找到 {found}/{expected} 個定位點，這份 PDF 可能不適用此範本",
                })
            for t_page, transform in transforms.items():
                if transform.quality == "none":
                    result["issues"].append({"code": "no_alignment", "page": t_page + 1,
                                             "message": REASONS["no_alignment"]})
            if progress:
                progress("取值中")
            fields: dict[str, dict] = {}
            for spec in template.get("fields", []):
                pages = [p for p in doc.pages
                         if rule_matches(spec.get("page_rule", "first"), p.index, total)]
                value = extract_field(spec, pages, transforms, use_ocr, doc.pages)
                value.update(id=spec["id"], name=spec.get("name", spec["id"]))
                fields[spec["id"]] = value
                result["fields"].append(value)
            tables: dict[str, dict] = {}
            for spec in template.get("tables", []):
                table = extract_table(spec, doc.pages, transforms, total, use_ocr)
                if not table["rows"] and spec.get("required", True):
                    result["issues"].append({"code": "empty_table", "page": None,
                                             "message": f"表格「{table['name']}」沒有抓到任何列"})
                result["issues"].extend(table.pop("issues"))
                tables[spec["id"]] = table
                result["tables"].append(table)
            result["issues"].extend(_run_validations(template, fields, tables, total))
    except Exception as exc:  # 單一檔案失敗不該中斷整批
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["issues"].append({"code": "failed", "page": None, "message": f"無法解析這份 PDF：{exc}"})
    summarize(result)
    return result


def _match_score(doc: Document, template: dict) -> float:
    """定位點命中率。只看前幾頁、不用 OCR，範本多時也不會太慢。"""
    anchors = collect_anchors(template)
    found = expected = 0
    for page in doc.pages[:MATCH_PAGES]:
        applicable = _anchors_for(anchors, page.index, len(doc))
        if applicable:
            transform = align_page(page, applicable, allow_ocr=False)
            found += transform.found
            expected += transform.total
    return found / expected if expected else 0.0


def _quality(result: dict) -> float:
    """綜合分數：定位點命中率，再扣掉實際取值的問題比例。"""
    counts = result["counts"]
    if result.get("error") or not counts["total"]:
        return -1.0
    problems = 2 * counts["missing"] + counts["review"] + 2 * len(result["issues"])
    return (result.get("match") or 0.0) - 0.5 * min(1.0, problems / counts["total"])


def parse_best(path: str | Path, templates: list[dict], use_ocr: bool = True,
               progress: Callable[[str], None] | None = None) -> dict:
    """從多個範本中挑最符合這份 PDF 的，並在結果中記錄挑選依據。"""
    if len(templates) == 1:
        return parse_pdf(path, templates[0], use_ocr, progress)
    try:
        with Document(path) as doc:
            scored = sorted(((_match_score(doc, t), i) for i, t in enumerate(templates)), reverse=True)
    except Exception:  # 打不開的檔案交給 parse_pdf 回報
        return parse_pdf(path, templates[0], use_ocr, progress)

    top = scored[0][0]
    # 命中率接近時才實際解析比較，取值結果比定位點更能分出高下
    finalists = [i for score, i in scored if score >= top - SHORTLIST_MARGIN][:MAX_FINALISTS]
    parsed = sorted(((_quality(r), order, r) for order, r in enumerate(
        parse_pdf(path, templates[i], use_ocr, progress) for i in finalists)),
        key=lambda item: (-item[0], item[1]))
    best = parsed[0][2]
    best["selection"] = {
        "auto": True,
        "candidates": [{"id": templates[i].get("template_id"),
                        "name": templates[i].get("name") or templates[i].get("template_id"),
                        "match": round(score, 3)} for score, i in scored],
    }
    if top == 0:
        best["issues"].append({"code": "no_template_match", "page": None,
                               "message": "選取的範本都找不到定位點，這份 PDF 可能沒有適用的範本"})
    elif len(parsed) > 1 and parsed[0][0] - parsed[1][0] < AMBIGUOUS_MARGIN:
        other = parsed[1][2]["template_name"]
        best["issues"].append({"code": "ambiguous_template", "page": None,
                               "message": f"「{best['template_name']}」和「{other}」分數接近，請確認用對範本"})
    summarize(best)
    return best
