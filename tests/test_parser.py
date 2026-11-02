"""以合成報單驗證：答案已知，所以能確認每個值都正確，而不只是有抓到。"""
import numpy as np
import pytest

from pdfmapper import ocr, template as tpl
from pdfmapper.document import Document, Glyph, group_lines, is_garbled, line_text
from pdfmapper.excel import write_excel
from pdfmapper.extract import read_box, shape_value
from pdfmapper.parser import parse_best, parse_pdf

CLEAN = ["sample_1_standard.pdf", "sample_2_shifted.pdf", "sample_3_hidden_labels.pdf", "sample_4_scanned.pdf"]
FIELD_MAP = {"declaration_no": "no", "tax_id": "tax_id", "fob_amount": "fob", "tax_total": "tax_total"}
CELL_MAP = {"item": "no", "name": "name", "code": "code", "price": "price",
            "weight": "weight", "qty": "qty", "value": "value"}


@pytest.mark.parametrize("name", CLEAN)
def test_every_value_is_correct(samples, template, name):
    folder, docs = samples
    expected = docs[name]
    result = parse_pdf(folder / name, template)
    assert result["pages"] == expected["pages"]
    fields = {f["id"]: f["value"] for f in result["fields"]}
    for field_id, key in FIELD_MAP.items():
        assert fields[field_id] == expected[key]
    rows = result["tables"][0]["rows"]
    assert len(rows) == len(expected["items"])
    for row, item in zip(rows, expected["items"]):
        for column, key in CELL_MAP.items():
            assert row["cells"][column]["value"] == item[key]


def test_scanned_pdf_uses_ocr(samples, template):
    folder, _ = samples
    result = parse_pdf(folder / "sample_4_scanned.pdf", template)
    assert {f["source"] for f in result["fields"]} == {"ocr"}


def test_errors_are_flagged(samples, template):
    folder, _ = samples
    result = parse_pdf(folder / "sample_5_errors.pdf", template)
    codes = {issue["code"] for issue in result["issues"]}
    assert {"sequence_gap", "sum_mismatch"} <= codes
    assert result["status"] == "review"
    assert next(f for f in result["fields"] if f["id"] == "tax_total")["status"] == "review"


def test_wrong_template_is_reported(samples, template):
    folder, _ = samples
    other = {**template, "anchors": [{**a, "patch": "", "text": "這段文字不存在"} for a in template["anchors"]],
             "fields": [], "tables": [], "validations": []}
    result = parse_pdf(folder / "sample_1_standard.pdf", other, use_ocr=False)
    assert "wrong_template" in {issue["code"] for issue in result["issues"]}


def test_required_field_outside_data_is_missing(samples, template):
    folder, _ = samples
    custom = {**template, "tables": [], "validations": [], "fields": [
        {"id": "blank", "name": "空白處", "kind": "position", "value_box": [0.3, 0.86, 0.5, 0.9], "required": True}]}
    result = parse_pdf(folder / "sample_1_standard.pdf", custom)
    assert result["fields"][0]["status"] == "missing"


def test_small_box_is_flagged_not_silently_truncated(samples):
    folder, docs = samples
    with Document(folder / "sample_1_standard.pdf") as doc:
        page = doc.pages[0]
        target = next(g for g in group_lines([g for g in page.glyphs if 0.2 < g.cy < 0.26 and g.cx < 0.5])
                      if line_text(g) == docs["sample_1_standard.pdf"]["fob"])
        cut = (target[1].x0 - 0.05, target[0].y0 - 0.005, target[-2].x1 + 0.0005, target[0].y1 + 0.005)
        reading = read_box(page, cut)

    assert "touches_edge" in reading.reasons


def test_corrupt_pdf_does_not_stop_batch(tmp_path, template):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    result = parse_pdf(bad, template)
    assert result["status"] == "failed"


def test_excel_output(samples, template, tmp_path):
    from openpyxl import load_workbook

    folder, _ = samples
    results = [parse_pdf(folder / name, template) for name in ("sample_1_standard.pdf", "sample_5_errors.pdf")]
    path = write_excel(results, tmp_path / "out.xlsx")
    book = load_workbook(path)
    assert book.sheetnames == ["待檢查", "檔案總覽", "欄位資料", "貨物明細"]
    assert book["欄位資料"].max_row == 3
    assert book["欄位資料"]["A2"].value == "sample_1_standard.pdf"
    assert any(row[0].value == "sample_5_errors.pdf" for row in book["待檢查"].iter_rows(min_row=2))


@pytest.mark.skipif(not ocr.available(), reason="沒有 OCR")
def test_detection_survives_single_line_mode(samples):
    """回歸測試：RapidOCR 會記住 use_det=False，之後的辨識會全部讀錯。"""
    folder, docs = samples
    with Document(folder / "sample_4_scanned.pdf") as doc:
        crop = doc.pages[0].crop((0.19, 0.103, 0.49, 0.132), 300)
    expected = docs["sample_4_scanned.pdf"]["no"]
    assert ocr.read(crop)[0][0] == expected
    blank_with_rule = np.full((60, 300, 3), 255, np.uint8)
    blank_with_rule[30, :] = 0
    ocr.read(blank_with_rule)
    assert ocr.read(crop)[0][0] == expected


@pytest.mark.parametrize("name, expected", [
    ("sample_1_standard.pdf", "customs_demo"),
    ("sample_4_scanned.pdf", "customs_demo"),
    ("sample_6_invoice.pdf", "invoice_demo"),
])
def test_best_template_is_chosen_in_any_order(samples, template, invoice_template, name, expected):
    folder, _ = samples
    for order in ([template, invoice_template], [invoice_template, template]):
        result = parse_best(folder / name, order)
        assert result["template_id"] == expected
        assert result["selection"]["candidates"][0]["id"] == expected
        assert result["match"] >= 0.9


def test_single_template_is_not_auto_selected(samples, template):
    folder, _ = samples
    result = parse_best(folder / "sample_1_standard.pdf", [template])
    assert "selection" not in result


def test_no_matching_template_is_flagged(samples, invoice_template):
    folder, _ = samples
    other = {**invoice_template, "template_id": "other"}
    result = parse_best(folder / "sample_1_standard.pdf", [invoice_template, other])
    assert result["status"] != "ok"
    assert "no_template_match" in {issue["code"] for issue in result["issues"]}


def test_close_templates_are_flagged(samples, template):
    folder, _ = samples
    twin = {**template, "template_id": "twin", "name": "雙胞胎"}
    result = parse_best(folder / "sample_1_standard.pdf", [template, twin])
    assert "ambiguous_template" in {issue["code"] for issue in result["issues"]}


def test_excel_keeps_templates_apart(samples, template, invoice_template, tmp_path):
    from openpyxl import load_workbook

    folder, _ = samples
    pair = [template, invoice_template]
    results = [parse_best(folder / name, pair) for name in ("sample_1_standard.pdf", "sample_6_invoice.pdf")]
    book = load_workbook(write_excel(results, tmp_path / "out.xlsx"))
    assert "欄位_進口報單（示範）" in book.sheetnames
    invoice = book["欄位_商業發票（示範）"]
    headers = [cell.value for cell in invoice[1]]
    assert "發票號碼" in headers and "報單號碼" not in headers
    assert invoice["C2"].value == "商業發票（示範）"
    assert invoice.cell(row=2, column=headers.index("發票號碼") + 1).value == "INV-2023-0042"
    assert len(list(book["商業發票（示範）_品項明細"].iter_rows(min_row=2))) == 2
    overview = book["檔案總覽"]
    assert overview["B3"].value == "商業發票（示範）" and overview["D3"].value == "自動"


def test_garbled_detection():
    assert is_garbled("(cid:1234)")
    assert is_garbled("")
    assert not is_garbled("完稅價格 1,234.50")


def test_value_stays_raw():
    assert shape_value("1,234.50", ["1,234.50"], {"type": "number"}) == ("1,234.50", [])


def test_pick_line_and_extract():
    assert shape_value("a b", ["a", "b"], {"pick_line": 2})[0] == "b"
    assert shape_value("第1頁/共11頁", ["第1頁/共11頁"], {"extract": r"共(\d+)頁"})[0] == "11"
    assert shape_value("abc", ["abc"], {"type": "number"})[1] == ["format_mismatch"]


def test_glyph_lines_keep_reading_order():
    glyphs = [Glyph("b", 0.2, 0.1, 0.21, 0.12), Glyph("a", 0.1, 0.1, 0.11, 0.12), Glyph("c", 0.1, 0.2, 0.11, 0.22)]
    assert [line_text(line) for line in group_lines(glyphs)] == ["a b", "c"]


def test_template_validation():
    errors = tpl.validate({"template_id": "x", "fields": [{"id": "a", "kind": "bad", "value_box": [1, 1, 0, 0]}]})
    assert len(errors) == 2


def test_rule_matching():
    assert tpl.rule_matches("first", 0, 3) and not tpl.rule_matches("first", 1, 3)
    assert tpl.rule_matches("rest", 2, 3) and tpl.rule_matches("last", 2, 3)
    assert tpl.rule_matches("page:2", 1, 3)
