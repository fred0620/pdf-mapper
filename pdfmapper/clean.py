"""匯出乾淨資料：沒有顏色和說明的純表格，給 Power Query、Python 等後續工具使用。

每種範本的欄位和表格各一張工作表，欄名和順序依範本的 output 設定。
"""
from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook

from .excel import _group_by_template, _sheet_title, keep_as_text, reason_text

ROW_STATUS = {"missing": "缺值", "review": "需檢查", "corrected": "已修正", "confirmed": "已確認", "ok": "正常"}
UNRESOLVED = {"缺值", "需檢查"}


def output_columns(saved: list[dict] | None, available: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """合併範本的輸出設定和實際欄位，回傳 (代號, 輸出欄名)。

    沒設定過的欄位預設輸出，所以舊範本和之後新增的欄位都不會漏掉。
    """
    names = dict(available)
    columns, listed = [], set()
    for item in saved or []:
        if item["id"] not in names:
            continue
        listed.add(item["id"])
        if item.get("include", True):
            columns.append((item["id"], (item.get("name") or "").strip() or names[item["id"]]))
    columns += [(key, name) for key, name in available if key not in listed]
    return columns


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    unique = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        unique.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return unique


def _summary(values: list[dict]) -> tuple[str, str]:
    """一列的狀態取其中最嚴重的，原因列在一起。"""
    statuses = {value.get("status", "ok") for value in values}
    status = next(text for key, text in ROW_STATUS.items() if key in statuses or key == "ok")
    reasons = list(dict.fromkeys(text for value in values for text in [reason_text(value)] if text))
    return status, "；".join(reasons)


def _issues(result: dict) -> str:
    return "；".join(issue["message"] for issue in result.get("issues", []))


def _safe(text: object) -> object:
    """openpyxl 不接受控制字元，文字層偶爾會有。"""
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text) if isinstance(text, str) else text


def _append(sheet, row: list) -> None:
    sheet.append([_safe(value) for value in row])
    for cell in sheet[sheet.max_row]:
        keep_as_text(cell)  # 保持原樣，不讓 Excel 自動轉格式


def _fields_sheet(book, group, output, title, only_confirmed) -> None:
    available: dict[str, str] = {}
    for result in group:
        available.update({field["id"]: field["name"] for field in result["fields"]})
    columns = output_columns(output.get("fields"), list(available.items()))
    if not columns:
        return
    sheet = book.create_sheet(_sheet_title(book, title))
    headers = ["來源檔名", "範本"] + [name for _, name in columns] + ["檢查狀態", "檢查原因", "整份檢查"]
    sheet.append(_unique(headers))
    for result in group:
        if result.get("error"):
            _append(sheet, [result["file"], result.get("template_name", "")] + [""] * len(columns)
                    + ["解析失敗", "", _issues(result)])
            continue
        by_id = {field["id"]: field for field in result["fields"]}
        values = [by_id[key] for key, _ in columns if key in by_id]
        status, reasons = _summary(values)
        if only_confirmed and status in UNRESOLVED:
            continue
        _append(sheet, [result["file"], result.get("template_name", "")]
                + [by_id.get(key, {}).get("value", "") for key, _ in columns] + [status, reasons, _issues(result)])


def _table_sheets(book, group, output, prefix, only_confirmed) -> None:
    tables: dict[str, dict] = {}
    for result in group:
        for table in result["tables"]:
            tables.setdefault(table["id"], table)
    for table_id, meta in tables.items():
        available = [(column["id"], column["name"]) for column in meta["columns"]]
        columns = output_columns((output.get("tables") or {}).get(table_id), available)
        if not columns:
            continue
        sheet = book.create_sheet(_sheet_title(book, f"{prefix}{meta['name']}"))
        headers = ["來源檔名", "範本", "頁碼", "列號"] + [name for _, name in columns] + ["檢查狀態", "檢查原因", "整份檢查"]
        sheet.append(_unique(headers))
        for result in group:
            for table in (t for t in result["tables"] if t["id"] == table_id):
                for number, row in enumerate(table["rows"], start=1):
                    values = [row["cells"][key] for key, _ in columns if key in row["cells"]]
                    status, reasons = _summary(values)
                    if only_confirmed and status in UNRESOLVED:
                        continue
                    _append(sheet, [result["file"], result.get("template_name", ""), row["page"], number]
                            + [row["cells"].get(key, {}).get("value", "") for key, _ in columns]
                            + [status, reasons, _issues(result)])


def write_clean(results: list[dict], templates: dict[str, dict], path: str | Path,
                only_confirmed: bool = False) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    book.remove(book.active)
    groups = _group_by_template(results)
    several = len(groups) > 1
    for template_id, group in groups.items():
        output = (templates.get(template_id) or {}).get("output") or {}
        name = group[0].get("template_name", "")
        _fields_sheet(book, group, output, f"欄位_{name}" if several else "欄位", only_confirmed)
        _table_sheets(book, group, output, f"{name}_" if several else "", only_confirmed)
    if not book.sheetnames:
        book.create_sheet("沒有資料")
    book.save(path)
    return path
