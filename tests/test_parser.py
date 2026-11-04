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


def _table_values(result):
    return [{key: cell["value"] for key, cell in row["cells"].items()} for row in result["tables"][0]["rows"]]


def test_header_and_end_marker_follow_the_table(samples, floating_template):
    folder, _ = samples
    for name, count in (("sample_7_table_a.pdf", 5), ("sample_8_table_b.pdf", 3)):
        result = parse_pdf(folder / name, floating_template)
        rows = _table_values(result)
        assert len(rows) == count, name
        assert [r["no"] for r in rows] == [str(i + 1) for i in range(count)]
        assert result["issues"] == []


def test_overlapping_and_multiline_cells(samples, floating_template):
    folder, _ = samples
    rows = _table_values(parse_pdf(folder / "sample_7_table_a.pdf", floating_template))
    assert rows[0] == {"no": "1", "body": "1243\n1234\ndfegfrgs\nsfg", "code": "A", "amount": "1"}
    assert rows[1]["code"] == "12345667765-long-code"
    assert rows[1]["amount"] == "20"
    assert rows[3]["body"] == "a\nb"


def test_missing_header_and_end_are_reported(samples, floating_template):
    folder, _ = samples
    table = floating_template["tables"][0]
    broken = {**floating_template, "tables": [{
        **table,
        "regions": [{**table["regions"][0], "header": {"text": "不存在", "box": table["regions"][0]["header"]["box"]}}],
        "end_marker": {"text": "不存在", "box": table["end_marker"]["box"]},
    }]}
    result = parse_pdf(folder / "sample_7_table_a.pdf", broken, use_ocr=False)
    codes = {issue["code"] for issue in result["issues"]}
    assert {"header_not_found", "end_not_found"} <= codes


def test_header_found_by_text_without_image(samples, floating_template):
    folder, _ = samples
    table = floating_template["tables"][0]
    region = table["regions"][0]
    header = {k: v for k, v in region["header"].items() if k != "patch"}
    marker = {k: v for k, v in table["end_marker"].items() if k != "patch"}
    text_only = {**floating_template, "tables": [{**table, "regions": [{**region, "header": header}], "end_marker": marker}]}
    rows = _table_values(parse_pdf(folder / "sample_8_table_b.pdf", text_only))
    assert [r["no"] for r in rows] == ["1", "2", "3"]


def test_key_position_detection():
    from pdfmapper.extract import _key_on_first_line

    key = [Glyph("1", 0.1, 0.30, 0.11, 0.32)]
    assert _key_on_first_line([key], key + [Glyph("a", 0.3, 0.30, 0.31, 0.32)])
    assert not _key_on_first_line([key], key + [Glyph("a", 0.3, 0.25, 0.31, 0.27)])


def _split_result(tmp_path, pages, key_position, required=False):
    import make_samples

    path = tmp_path / "split.pdf"
    make_samples.write_split(path, pages)
    template = make_samples.build_split_template(key_position, required)
    with Document(path) as reference:
        tpl.finalize(template, reference)
    return parse_pdf(path, template)


TOP_PAGES = [
    [(0, 0.20, "1"), (1, 0.20, "one"), (2, 0.20, "A1"),
     (0, 0.30, "2"), (1, 0.30, "two-a"), (1, 0.33, "two-b"), (2, 0.30, "A2")],
    [(1, 0.16, "two-c"), (1, 0.19, "two-d"),
     (0, 0.26, "3"), (1, 0.26, "three"), (2, 0.26, "A3")],
]
# 項次在中間：每列內容在項次上方一行、下方一行
MIDDLE_ROWS = [(0, 0.23, "1"), (1, 0.20, "one-a"), (1, 0.26, "one-b"), (2, 0.20, "A1"),
               (0, 0.33, "2"), (1, 0.30, "two-a"), (1, 0.36, "two-b"), (2, 0.30, "A2")]
MIDDLE_NEXT = [(0, 0.23, "3"), (1, 0.20, "three-a"), (1, 0.26, "three-b"), (2, 0.20, "A3")]


def test_row_split_with_key_on_first_line(tmp_path):
    result = _split_result(tmp_path, TOP_PAGES, "top")
    rows = _table_values(result)
    assert [r["no"] for r in rows] == ["1", "2", "3"]
    assert rows[1]["body"] == "two-a\ntwo-b\ntwo-c\ntwo-d"
    cell = result["tables"][0]["rows"][1]["cells"]["body"]
    assert "row_spans_pages" in cell["reasons"] and cell["extra_boxes"][0]["page"] == 2


def test_row_split_auto_detects_key_on_first_line(tmp_path):
    rows = _table_values(_split_result(tmp_path, TOP_PAGES, "auto"))
    assert [r["no"] for r in rows] == ["1", "2", "3"] and rows[1]["body"].endswith("two-d")


def test_pick_line_works_across_pages(tmp_path):
    import make_samples

    path = tmp_path / "split.pdf"
    make_samples.write_split(path, TOP_PAGES)
    template = make_samples.build_split_template("top")
    template["tables"][0]["columns"][1]["pick_line"] = 3
    with Document(path) as reference:
        tpl.finalize(template, reference)
    assert _table_values(parse_pdf(path, template))[1]["body"] == "two-c"


def test_middle_key_normal_page_is_not_flagged(tmp_path):
    result = _split_result(tmp_path, [MIDDLE_ROWS, MIDDLE_NEXT], "middle")
    rows = _table_values(result)
    assert rows[2]["body"] == "three-a\nthree-b"
    assert result["status"] == "ok"


def test_middle_key_incomplete_row_takes_the_lead(tmp_path):
    first = [item for item in MIDDLE_ROWS if item[2] != "A2"]
    second = [(1, 0.15, "two-c"), (2, 0.15, "A2")] + [(c, y + 0.1, t) for c, y, t in MIDDLE_NEXT]
    result = _split_result(tmp_path, [first, second], "middle", required=True)
    rows = _table_values(result)
    assert rows[1]["code"] == "A2" and rows[1]["body"].endswith("two-c")
    assert rows[2]["body"] == "three-a\nthree-b" and rows[2]["code"] == "A3"
    assert "row_spans_pages" in result["tables"][0]["rows"][1]["cells"]["code"]["reasons"]


def test_middle_key_complete_row_keeps_lead(tmp_path):
    second = [(1, 0.15, "extra")] + [(c, y + 0.1, t) for c, y, t in MIDDLE_NEXT]
    result = _split_result(tmp_path, [MIDDLE_ROWS, second], "middle", required=True)
    assert _table_values(result)[2]["body"].startswith("extra")
    assert "row_spans_pages" not in str(result["tables"][0]["rows"][1])


def test_middle_key_without_rule_is_flagged_not_guessed(tmp_path):
    second = [(1, 0.15, "extra")] + [(c, y + 0.1, t) for c, y, t in MIDDLE_NEXT]
    result = _split_result(tmp_path, [MIDDLE_ROWS, second], "middle")
    assert "possible_row_split" in result["tables"][0]["rows"][2]["cells"]["no"]["reasons"]


def test_required_cell_missing_is_flagged(tmp_path):
    first = [item for item in MIDDLE_ROWS if item[2] != "A2"]
    result = _split_result(tmp_path, [first, MIDDLE_NEXT], "middle", required=True)
    cell = result["tables"][0]["rows"][1]["cells"]["code"]
    assert cell["status"] == "missing" and "row_incomplete" in cell["reasons"]


def test_key_value_continuation(tmp_path):
    import make_samples

    path = tmp_path / "split.pdf"
    make_samples.write_split(path, [[(1, 0.85, "first part")], [(1, 0.15, "second part")]])
    template = make_samples.build_split_template("top")
    template["tables"] = []
    template["fields"] = [{"id": "note", "name": "備註", "kind": "position", "page_rule": "first", "ref_page": 0,
                           "value_box": [0.2, 0.83, 0.9, 0.88], "required": True,
                           "continuation": {"box": [0.2, 0.13, 0.9, 0.18], "ref_page": 1}}]
    with Document(path) as reference:
        tpl.finalize(template, reference)
    field = parse_pdf(path, template)["fields"][0]
    assert field["value"] == "first part second part"
    assert field["status"] == "review" and "value_spans_pages" in field["reasons"]
    assert field["extra_boxes"][0]["page"] == 2


def test_key_value_without_continuation_text_is_unchanged(tmp_path):
    import make_samples

    path = tmp_path / "split.pdf"
    make_samples.write_split(path, [[(1, 0.85, "only")], [(1, 0.5, "elsewhere")]])
    template = make_samples.build_split_template("top")
    template["tables"] = []
    template["fields"] = [{"id": "note", "name": "備註", "kind": "position", "page_rule": "first", "ref_page": 0,
                           "value_box": [0.2, 0.83, 0.9, 0.88], "required": True,
                           "continuation": {"box": [0.2, 0.13, 0.9, 0.18], "ref_page": 1}}]
    with Document(path) as reference:
        tpl.finalize(template, reference)
    field = parse_pdf(path, template)["fields"][0]
    assert field["value"] == "only" and field["status"] == "ok"


def test_split_sections_with_uneven_subs():
    from pdfmapper.extract import split_sections

    text = "sub1:jijijij sub2: knni nininininin sub3: njnnn sub4: ji"
    sections = split_sections(text, ["sub1:", "sub2:", "sub3:", "sub4:"])
    assert {key: value.strip() for key, value in sections.items()} == {
        "sub1:": "jijijij", "sub2:": "knni nininininin", "sub3:": "njnnn", "sub4:": "ji"}


def test_split_sections_tolerates_spacing_case_and_full_width_colon():
    from pdfmapper.extract import split_sections

    assert split_sections("sub 2： abc", ["sub2:"])["sub2:"].strip() == "abc"
    assert split_sections("Eccn : 5A992", ["ECCN:"])["ECCN:"].strip() == "5A992"


def test_split_sections_any_order():
    from pdfmapper.extract import split_sections

    sections = split_sections("sub2: b sub1: a", ["sub1:", "sub2:"])
    assert (sections["sub1:"].strip(), sections["sub2:"].strip()) == ("a", "b")


ECCN_LINES = ["Laptop model X", "ECCN: 5A992.c rev 2", "Origin: TW"]


@pytest.mark.parametrize("end, expected", [
    ("line", "5A992.c rev 2"), ("word", "5A992.c"), ("next", "5A992.c rev 2 Origin: TW"),
])
def test_start_text_takes_only_the_value(end, expected):
    from pdfmapper.extract import read_after_start

    assert read_after_start(ECCN_LINES, {"start": "ECCN:", "end": end}, ["ECCN:"]) == expected


def test_start_text_stops_at_next_key_on_the_same_line():
    from pdfmapper.extract import read_after_start

    lines = ["sub3: njnnn sub4: ji"]
    assert read_after_start(lines, {"start": "sub3:", "end": "line"}, ["sub3:", "sub4:"]) == "njnnn"
    assert read_after_start(lines, {"start": "sub4:", "end": "line"}, ["sub3:", "sub4:"]) == "ji"


def test_start_text_value_on_the_next_line():
    from pdfmapper.extract import read_after_start

    assert read_after_start(["ECCN:", "5A992"], {"start": "ECCN:", "end": "line"}, ["ECCN:"]) == "5A992"


def test_start_text_missing_gives_blank():
    from pdfmapper.extract import read_after_start

    assert read_after_start(["no key here"], {"start": "ECCN:", "end": "line"}, ["ECCN:"]) == ""


def test_table_columns_split_by_start_text(tmp_path):
    import make_samples

    path = tmp_path / "split.pdf"
    pages = [[(0, 0.20, "1"), (1, 0.20, "sub1: aaa"), (1, 0.23, "sub2: bbb"), (1, 0.26, "ccc"),
              (1, 0.29, "sub3: ddd sub4: eee"), (2, 0.20, "A1"),
              (0, 0.36, "2"), (1, 0.36, "sub1: fff"), (2, 0.36, "A2"),
              (0, 0.42, "3"), (1, 0.42, "plain text"), (2, 0.42, "A3")]]
    make_samples.write_split(path, pages)
    template = make_samples.build_split_template("top")
    columns = template["tables"][0]["columns"]
    columns[1:2] = [{"id": f"s{i}", "name": f"sub{i}", "band": 1, "start": f"sub{i}:"} for i in range(1, 5)]
    with Document(path) as reference:
        tpl.finalize(template, reference)
    rows = _table_values(parse_pdf(path, template))
    assert (rows[0]["s1"], rows[0]["s2"], rows[0]["s3"], rows[0]["s4"]) == ("aaa", "bbb ccc", "ddd", "eee")
    assert rows[1]["s1"] == "fff" and rows[1]["s2"] == ""
    assert rows[2]["s1"] == ""  # 沒有開頭就留空，不把其他文字塞進來


def test_key_extraction_keeps_whole_cell_beside_it(tmp_path):
    columns = [{"id": "whole", "name": "原文", "band": 1},
               {"id": "eccn", "name": "ECCN", "band": 1, "start": "ECCN:", "end": "word"}]
    result = _band_result(tmp_path, ECCN_LINES, columns)
    rows = _table_values(result)
    assert rows[0]["eccn"] == "5A992.c"
    assert rows[0]["whole"].startswith("Laptop model X ECCN: 5A992.c")
    assert result["tables"][0]["rows"][0]["cells"]["eccn"]["raw"].startswith("Laptop")


def _band_template(columns):
    import make_samples

    template = make_samples.build_split_template("top")
    template["tables"][0]["columns"][1:2] = columns
    return template


def _band_result(tmp_path, lines, columns):
    import make_samples

    path = tmp_path / "band.pdf"
    items = [(0, 0.20, "1"), (2, 0.20, "A1")] + [(1, 0.20 + i * 0.03, text) for i, text in enumerate(lines)]
    make_samples.write_split(path, [items])
    template = _band_template(columns)
    with Document(path) as reference:
        tpl.finalize(template, reference)
    return parse_pdf(path, template)


def test_default_keeps_whole_cell(tmp_path):
    rows = _table_values(_band_result(tmp_path, ["sub3: x sub4: y", "more"], [{"id": "a", "name": "A", "band": 1}]))
    assert rows[0]["a"] == "sub3: x sub4: y more"


def test_split_by_regex_and_no_match_is_blank(tmp_path):
    columns = [{"id": "a", "name": "A", "band": 1, "extract": r"ECCN:\s*(\S+)"},
               {"id": "b", "name": "B", "band": 1, "extract": r"HTS:\s*(\S+)"}]
    result = _band_result(tmp_path, ECCN_LINES, columns)
    cells = result["tables"][0]["rows"][0]["cells"]
    assert cells["a"]["value"] == "5A992.c" and cells["a"]["status"] == "ok"
    assert cells["b"]["value"] == "" and cells["b"]["status"] == "ok"


def test_optional_regex_group_does_not_crash(tmp_path):
    columns = [{"id": "a", "name": "A", "band": 1, "extract": r"(HTS:)?\s*Laptop"}]
    result = _band_result(tmp_path, ECCN_LINES, columns)
    assert "error" not in result
    assert shape_value("abc", ["abc"], {"extract": r"(x)?abc"})[0] == ""


def test_regex_with_required_column_flags_blank(tmp_path):
    columns = [{"id": "b", "name": "B", "band": 1, "extract": r"HTS:\s*(\S+)", "row_required": True}]
    cell = _band_result(tmp_path, ECCN_LINES, columns)["tables"][0]["rows"][0]["cells"]["b"]
    assert cell["status"] == "missing" and "row_incomplete" in cell["reasons"]


def _part_columns(mode, count=2):
    return [{"id": f"p{i}", "name": f"P{i}", "band": 1, "part_by": mode, "part": i} for i in range(1, count + 1)]


def test_split_by_space(tmp_path):
    rows = _table_values(_band_result(tmp_path, ["njnnn ji"], _part_columns("space")))
    assert (rows[0]["p1"], rows[0]["p2"]) == ("njnnn", "ji")


def test_split_count_mismatch_is_blank_and_keeps_raw(tmp_path):
    result = _band_result(tmp_path, ["one two three"], _part_columns("space"))
    cells = result["tables"][0]["rows"][0]["cells"]
    for cell in (cells["p1"], cells["p2"]):
        assert cell["value"] == "" and cell["status"] == "review"
        assert "split_count_mismatch" in cell["reasons"] and cell["raw"] == "one two three"


def test_non_consecutive_parts_are_blank_and_flagged(tmp_path):
    columns = [{"id": "p1", "name": "P1", "band": 1, "part_by": "space", "part": 2},
               {"id": "p2", "name": "P2", "band": 1, "part_by": "space", "part": 3}]
    cells = _band_result(tmp_path, ["aa bb"], columns)["tables"][0]["rows"][0]["cells"]
    assert cells["p1"]["value"] == "" and cells["p1"]["raw"] == "aa bb"
    assert "split_count_mismatch" in cells["p2"]["reasons"]


def test_field_extract_no_match_is_blank_and_keeps_raw(samples, template):
    folder, docs = samples
    spec = next(f for f in template["fields"] if f["id"] == "tax_id")
    changed = {**template, "tables": [], "validations": [], "fields": [{**spec, "extract": r"NOPE(\d+)", "pattern": None}]}
    field = parse_pdf(folder / "sample_1_standard.pdf", changed)["fields"][0]
    assert field["value"] == "" and field["status"] == "missing"
    assert field["raw"] == docs["sample_1_standard.pdf"]["tax_id"]
    assert "extract_no_match" in field["reasons"]


def test_column_with_no_values_warns_about_rule(tmp_path):
    columns = [{"id": "a", "name": "A", "band": 1, "start": "NOPE:"}]
    result = _band_result(tmp_path, ECCN_LINES, columns)
    assert "column_all_blank" in {issue["code"] for issue in result["issues"]}


def test_split_by_gap_uses_real_distance(tmp_path):
    rows = _table_values(_band_result(tmp_path, ["two words      ji"], _part_columns("gap")))
    assert (rows[0]["p1"], rows[0]["p2"]) == ("two words", "ji")


def test_bad_regex_is_rejected_when_saving():
    template = _band_template([{"id": "a", "name": "A", "band": 1, "extract": "("}])
    assert any("正規表達式" in error for error in tpl.validate(template))


def test_output_columns_defaults_and_new_fields():
    from pdfmapper.clean import output_columns

    available = [("a", "A"), ("b", "B"), ("c", "C")]
    assert output_columns(None, available) == available
    saved = [{"id": "b", "name": "乙"}, {"id": "a", "include": False}, {"id": "gone", "name": "X"}]
    assert output_columns(saved, available) == [("b", "乙"), ("c", "C")]


def _sheet_rows(sheet):
    return [list(row) for row in sheet.iter_rows(values_only=True)]


def test_clean_export(samples, template, tmp_path):
    from openpyxl import load_workbook
    from pdfmapper.clean import write_clean

    folder, _ = samples
    results = [parse_pdf(folder / name, template) for name in ("sample_1_standard.pdf", "sample_5_errors.pdf")]
    configured = {**template, "output": {"tables": {"items": [
        {"id": "code", "name": "HS Code"}, {"id": "ref", "include": False}]}}}
    book = load_workbook(write_clean(results, {"customs_demo": configured}, tmp_path / "clean.xlsx"))
    assert book.sheetnames == ["欄位", "貨物明細"]
    rows = _sheet_rows(book["貨物明細"])
    assert rows[0][:5] == ["來源檔名", "範本", "頁碼", "列號", "HS Code"]
    assert "參考號" not in rows[0] and rows[0][-3:] == ["檢查狀態", "檢查原因", "整份檢查"]
    assert book["貨物明細"]["A2"].fill.fgColor.rgb == "00000000"  # 沒有顏色
    assert book["貨物明細"].merged_cells.ranges == [] or not list(book["貨物明細"].merged_cells.ranges)
    status = rows[0].index("檢查狀態")
    assert {row[status] for row in rows[1:]} == {"正常", "需檢查"}
    fields = _sheet_rows(book["欄位"])
    assert "稅費合計" in fields[0] and len(fields) == 3


def test_clean_export_only_confirmed(samples, template, tmp_path):
    from openpyxl import load_workbook
    from pdfmapper.clean import write_clean

    folder, _ = samples
    results = [parse_pdf(folder / "sample_5_errors.pdf", template)]
    book = load_workbook(write_clean(results, {}, tmp_path / "clean.xlsx", only_confirmed=True))
    rows = _sheet_rows(book["貨物明細"])
    status = rows[0].index("檢查狀態")
    assert len(rows) == 8 and {row[status] for row in rows[1:]} == {"正常"}  # 8 列資料少了 1 列待檢查
    assert len(_sheet_rows(book["欄位"])) == 1  # 稅費合計待檢查，整列排除


def test_clean_export_separates_templates(samples, template, invoice_template, tmp_path):
    from openpyxl import load_workbook
    from pdfmapper.clean import write_clean

    folder, _ = samples
    pair = [template, invoice_template]
    results = [parse_best(folder / name, pair) for name in ("sample_1_standard.pdf", "sample_6_invoice.pdf")]
    book = load_workbook(write_clean(results, {t["template_id"]: t for t in pair}, tmp_path / "clean.xlsx"))
    assert "欄位_商業發票（示範）" in book.sheetnames and "商業發票（示範）_品項明細" in book.sheetnames
    assert "報單號碼" not in _sheet_rows(book["欄位_商業發票（示範）"])[0]


def test_clean_export_with_only_a_failed_file_still_writes(template, tmp_path):
    from openpyxl import load_workbook
    from pdfmapper.clean import write_clean

    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf")
    book = load_workbook(write_clean([parse_pdf(bad, template)], {}, tmp_path / "clean.xlsx"))
    assert book.sheetnames == ["沒有資料"]


def test_formula_like_text_stays_text(samples, template, tmp_path):
    from openpyxl import load_workbook
    from pdfmapper.clean import write_clean

    folder, _ = samples
    result = parse_pdf(folder / "sample_1_standard.pdf", template)
    result["fields"][0]["value"] = "=1+1"
    for path in (write_excel([result], tmp_path / "a.xlsx"),
                 write_clean([result], {}, tmp_path / "b.xlsx")):
        book = load_workbook(path)
        sheet = book["欄位資料" if "欄位資料" in book.sheetnames else "欄位"]
        cell = next(c for row in sheet.iter_rows() for c in row if c.value == "=1+1")
        assert cell.data_type == "s"


def test_duplicate_output_names_stay_unique():
    from pdfmapper.clean import _unique

    assert _unique(["金額", "金額", "金額"]) == ["金額", "金額_2", "金額_3"]


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
