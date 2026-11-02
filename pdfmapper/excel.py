"""輸出 Excel：資料頁加上一張附原圖截圖的待檢查清單。"""
from __future__ import annotations

import io
import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.properties import PageSetupProperties
from PIL import Image

from .document import Document, expand
from .extract import REASONS
from .parser import iter_values

FILL = {
    "review": PatternFill("solid", fgColor="FBE3D6"),
    "missing": PatternFill("solid", fgColor="F4C7C3"),
    "corrected": PatternFill("solid", fgColor="DDEBDF"),
}
HEADER_FILL = PatternFill("solid", fgColor="2C5F34")
HEADER_FONT = Font(bold=True, color="FFFFFF")
STATUS_TEXT = {"ok": "正常", "review": "需檢查", "failed": "失敗"}
VALUE_STATUS = {"review": "需檢查", "missing": "缺值", "corrected": "已人工修正", "confirmed": "已確認"}
SOURCE_TEXT = {"text": "文字層", "ocr": "影像辨識", "manual": "人工", "": ""}
CROP_DPI = 110


def reason_text(value: dict) -> str:
    return "；".join(REASONS.get(code, code) for code in value.get("reasons", []))


def _header(sheet, titles: list[str]) -> None:
    sheet.append(titles)
    for cell in sheet[sheet.max_row]:
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.freeze_panes = f"A{sheet.max_row + 1}"


def _write(cell, value: dict) -> None:
    cell.value = value.get("value", "")
    cell.number_format = "@"  # 保持原樣，不讓 Excel 自動轉格式
    fill = FILL.get(value.get("status"))
    if fill:
        cell.fill = fill
    note = reason_text(value)
    if value.get("status") == "corrected":
        note = f"原本抓到：{value.get('original', '')}"
    if note:
        cell.comment = Comment(note, "PDF 解析器", width=280, height=90)


def _widths(sheet, limit: int = 40) -> None:
    for index, column in enumerate(sheet.columns, start=1):
        longest = max((sum(2 if ord(c) > 255 else 1 for c in str(cell.value or ""))
                       for cell in column), default=8)
        sheet.column_dimensions[get_column_letter(index)].width = min(limit, max(10, longest + 2))


def _match_text(result: dict) -> str:
    match = result.get("match")
    return "" if match is None else f"{match:.0%}"


def _candidates_text(result: dict) -> str:
    candidates = (result.get("selection") or {}).get("candidates", [])
    return "；".join(f"{c['name']} {c['match']:.0%}" for c in candidates)


def _overview_sheet(book: Workbook, results: list[dict]) -> None:
    sheet = book.create_sheet("檔案總覽")
    _header(sheet, ["檔名", "使用範本", "符合度", "挑選方式", "各範本符合度", "狀態", "待檢查", "缺值"])
    for result in results:
        counts = result.get("counts", {})
        sheet.append([result["file"], result.get("template_name", ""), _match_text(result),
                      "自動" if result.get("selection") else "指定", _candidates_text(result),
                      STATUS_TEXT.get(result["status"], result["status"]),
                      counts.get("review", 0), counts.get("missing", 0)])
    _widths(sheet)


def _group_by_template(results: list[dict]) -> dict[str, list[dict]]:
    # 不同範本的欄位代號可能相同，必須分開，否則資料會混到別人的欄
    groups: dict[str, list[dict]] = {}
    for result in results:
        groups.setdefault(result.get("template_id") or "", []).append(result)
    return groups


def _sheet_title(book: Workbook, title: str) -> str:
    cleaned = re.sub(r"[\\/*?:\[\]]", "_", title)[:31] or "工作表"
    candidate, number = cleaned, 2
    while candidate in book.sheetnames:
        suffix = f"_{number}"
        candidate, number = cleaned[:31 - len(suffix)] + suffix, number + 1
    return candidate


def _fields_sheet(book: Workbook, results: list[dict], title: str) -> None:
    sheet = book.create_sheet(_sheet_title(book, title))
    specs: dict[str, str] = {}
    for result in results:
        specs.update({field["id"]: field["name"] for field in result["fields"]})
    _header(sheet, ["檔名", "狀態", "使用範本", "符合度", *specs.values()])
    for result in results:
        sheet.append([result["file"], STATUS_TEXT.get(result["status"], result["status"]),
                      result.get("template_name", ""), _match_text(result)])
        row = sheet.max_row
        by_id = {field["id"]: field for field in result["fields"]}
        for offset, field_id in enumerate(specs, start=5):
            if field_id in by_id:
                _write(sheet.cell(row=row, column=offset), by_id[field_id])
    _widths(sheet)


def _table_sheets(book: Workbook, results: list[dict], prefix: str) -> None:
    tables: dict[str, dict] = {}
    for result in results:
        for table in result["tables"]:
            tables.setdefault(table["id"], {"name": table["name"], "columns": table["columns"]})
    for table_id, meta in tables.items():
        sheet = book.create_sheet(_sheet_title(book, f"{prefix}{meta['name']}"))
        _header(sheet, ["檔名", "頁", *[c["name"] for c in meta["columns"]]])
        for result in results:
            for table in (t for t in result["tables"] if t["id"] == table_id):
                for row in table["rows"]:
                    sheet.append([result["file"], row["page"]])
                    number = sheet.max_row
                    for offset, column in enumerate(meta["columns"], start=3):
                        if column["id"] in row["cells"]:
                            _write(sheet.cell(row=number, column=offset), row["cells"][column["id"]])
        _widths(sheet)


def _crop_image(doc: Document | None, value: dict) -> io.BytesIO | None:
    if doc is None or not value.get("box") or not value.get("page"):
        return None
    array = doc.pages[value["page"] - 1].crop(expand(tuple(value["box"]), 0.006), CROP_DPI)
    if not array.size:
        return None
    image = Image.fromarray(array)
    image.thumbnail((360, 110))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    buffer.seek(0)
    return buffer


def _write_pending(sheet, result: dict, pending: list, doc: Document | None) -> None:
    for name, value in pending:
        sheet.append([result["file"], result.get("template_name", ""), value.get("page"), name,
                      value.get("value", ""), VALUE_STATUS[value["status"]], reason_text(value),
                      SOURCE_TEXT.get(value.get("source", ""), "")])
        row = sheet.max_row
        sheet.cell(row=row, column=5).fill = FILL[value["status"]]
        crop = _crop_image(doc, value)
        if crop:
            picture = XLImage(crop)
            sheet.add_image(picture, f"I{row}")
            sheet.row_dimensions[row].height = max(18, picture.height * 0.78)


def _review_sheet(book: Workbook, results: list[dict]) -> None:
    sheet = book.create_sheet("待檢查", 0)
    _header(sheet, ["檔名", "使用範本", "頁", "項目", "抓到的值", "狀態", "原因", "來源", "原圖"])
    for result in results:
        for issue in result.get("issues", []):
            sheet.append([result["file"], result.get("template_name", ""), issue.get("page"),
                          "整份檢查", "", "需檢查", issue["message"]])
        pending = [(name, value) for _ref, name, value in iter_values(result)
                   if value.get("status") in ("review", "missing")]
        if not pending:
            continue
        try:
            doc = Document(result["path"])
        except Exception:
            doc = None
        try:
            _write_pending(sheet, result, pending, doc)
        finally:
            if doc:
                doc.close()
    _widths(sheet)
    sheet.column_dimensions["I"].width = 48
    if sheet.max_row == 1:
        sheet.append(["沒有需要檢查的項目"])


def write_excel(results: list[dict], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    book.remove(book.active)
    groups = _group_by_template(results)
    for group in groups.values():
        name = group[0].get("template_name", "")
        several = len(groups) > 1
        _fields_sheet(book, group, f"欄位_{name}" if several else "欄位資料")
        _table_sheets(book, group, f"{name}_" if several else "")
    _review_sheet(book, results)
    _overview_sheet(book, results)
    book.move_sheet("檔案總覽", -(len(book.sheetnames) - 2))
    for sheet in book.worksheets:  # 列印時整張縮到一頁寬
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    book.save(path)
    return path
