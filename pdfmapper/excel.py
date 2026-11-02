"""輸出 Excel：資料頁加上一張附原圖截圖的待檢查清單。"""
from __future__ import annotations

import io
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


def _fields_sheet(book: Workbook, results: list[dict]) -> None:
    sheet = book.active
    sheet.title = "欄位資料"
    specs: dict[str, str] = {}
    for result in results:
        specs.update({field["id"]: field["name"] for field in result["fields"]})
    _header(sheet, ["檔名", "狀態", *specs.values()])
    for result in results:
        sheet.append([result["file"], STATUS_TEXT.get(result["status"], result["status"])])
        row = sheet.max_row
        by_id = {field["id"]: field for field in result["fields"]}
        for offset, field_id in enumerate(specs, start=3):
            if field_id in by_id:
                _write(sheet.cell(row=row, column=offset), by_id[field_id])
    _widths(sheet)


def _table_sheets(book: Workbook, results: list[dict]) -> None:
    tables: dict[str, dict] = {}
    for result in results:
        for table in result["tables"]:
            tables.setdefault(table["id"], {"name": table["name"], "columns": table["columns"]})
    for table_id, meta in tables.items():
        sheet = book.create_sheet(meta["name"][:31] or table_id[:31])
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


def _review_sheet(book: Workbook, results: list[dict]) -> None:
    sheet = book.create_sheet("待檢查", 0)
    _header(sheet, ["檔名", "頁", "項目", "抓到的值", "狀態", "原因", "來源", "原圖"])
    for result in results:
        for issue in result.get("issues", []):
            sheet.append([result["file"], issue.get("page"), "整份檢查", "", "需檢查", issue["message"]])
        pending = [(name, value) for _ref, name, value in iter_values(result)
                   if value.get("status") in ("review", "missing")]
        if not pending:
            continue
        try:
            doc = Document(result["path"])
        except Exception:
            doc = None
        for name, value in pending:
            sheet.append([result["file"], value.get("page"), name, value.get("value", ""),
                          VALUE_STATUS[value["status"]], reason_text(value),
                          SOURCE_TEXT.get(value.get("source", ""), "")])
            row = sheet.max_row
            sheet.cell(row=row, column=4).fill = FILL[value["status"]]
            crop = _crop_image(doc, value)
            if crop:
                picture = XLImage(crop)
                sheet.add_image(picture, f"H{row}")
                sheet.row_dimensions[row].height = max(18, picture.height * 0.78)
        if doc:
            doc.close()
    _widths(sheet)
    sheet.column_dimensions["H"].width = 48
    if sheet.max_row == 1:
        sheet.append(["沒有需要檢查的項目"])


def write_excel(results: list[dict], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    _fields_sheet(book, results)
    _table_sheets(book, results)
    _review_sheet(book, results)
    for sheet in book.worksheets:  # 列印時整張縮到一頁寬
        sheet.page_setup.orientation = "landscape"
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)
    book.save(path)
    return path
