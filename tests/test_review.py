"""人工確認、修改、還原：處理過的警示留下紀錄，看得出改了什麼。"""
import copy

import pdfmapper.server as server
from pdfmapper.excel import write_excel
from pdfmapper.parser import handle_value, iter_values, parse_pdf


def _flagged(result):
    return [(ref, value) for ref, _name, value in iter_values(result) if value["status"] in ("review", "missing")]


def test_confirm_keeps_why_it_was_flagged():
    value = {"value": "A", "status": "review", "reasons": ["x"], "source": "text"}
    handle_value(value, "confirm")
    assert value["status"] == "confirmed" and value["reasons"] == []
    assert value["flag"] == {"status": "review", "reasons": ["x"]}
    handle_value(value, "revert")
    assert value == {"value": "A", "status": "review", "reasons": ["x"], "source": "text"}


def test_correct_keeps_original_and_can_revert():
    value = {"value": "A", "status": "missing", "reasons": ["y"], "source": "ocr"}
    handle_value(value, "correct", "B")
    handle_value(value, "correct", "C")  # 再改一次，原值仍是第一次抓到的
    assert (value["value"], value["original"], value["status"], value["source"]) == ("C", "A", "corrected", "manual")
    handle_value(value, "revert")
    assert value == {"value": "A", "status": "missing", "reasons": ["y"], "source": "ocr"}


def test_correct_back_to_original():
    flagged = {"value": "A", "status": "review", "reasons": ["x"], "source": "text"}
    handle_value(flagged, "correct", "A")  # 有警示時改回原值等於確認
    assert flagged["status"] == "confirmed" and "original" not in flagged
    plain = {"value": "A", "status": "ok", "reasons": [], "source": "text"}
    handle_value(plain, "correct", "B")
    assert plain["status"] == "corrected" and "flag" not in plain
    handle_value(plain, "correct", "A")  # 沒警示的改回原值就回到原狀
    assert plain == {"value": "A", "status": "ok", "reasons": [], "source": "text"}


def test_edit_route_any_value_and_excel_record(samples, template, tmp_path, monkeypatch):
    from openpyxl import load_workbook

    folder, _ = samples
    monkeypatch.setattr(server, "OUTPUT", tmp_path)
    result = parse_pdf(folder / "sample_6_invoice.pdf", template)  # 用不合的範本，警示比較多
    flagged = _flagged(result)
    assert len(flagged) >= 2
    ok_ref = next(ref for ref, _n, v in iter_values(result) if v["status"] == "ok")
    server._runs["r"] = {"total": 1, "done": 1, "current": "", "results": [result], "finished": True}
    server._run_templates["r"] = {template["template_id"]: template}
    client = server.app.test_client()
    try:
        before = result["counts"]["review"] + result["counts"]["missing"]
        edit = lambda ref, action, value=None: client.post(  # noqa: E731
            "/api/runs/r/edit", json={"file_index": 0, "ref": ref, "action": action, "value": value})
        assert edit(flagged[0][0], "confirm").status_code == 200
        body = edit(flagged[1][0], "correct", "改過的值").json
        assert body["counts"]["review"] + body["counts"]["missing"] == before - 2
        assert edit(ok_ref, "correct", "沒警示也能改").status_code == 200  # 正常的值也能改
        assert edit(ok_ref, "nope").status_code == 400

        path = write_excel(copy.deepcopy(server._runs["r"]["results"]), tmp_path / "out.xlsx")
        sheet = load_workbook(path)["待檢查"]
        header = [c.value for c in sheet[1]]
        rows = [dict(zip(header, (c.value for c in row))) for row in sheet.iter_rows(min_row=2)]
        handled = [r["處理"] for r in rows if r["處理"]]
        assert "已確認無誤" in handled
        assert any(text.startswith("已人工修改") for text in handled)
        assert sum(1 for r in rows if r["抓到的值"] == "沒警示也能改") == 1

        body = edit(flagged[1][0], "revert").json  # 還原後回到待檢查
        assert body["counts"]["review"] + body["counts"]["missing"] == before - 1
    finally:
        server._runs.pop("r")
        server._run_templates.pop("r")


def test_multiline_correction_in_excel(samples, floating_template, tmp_path):
    """多行的值修改後，Excel 保留換行並自動換行顯示。"""
    from openpyxl import load_workbook

    folder, _ = samples
    result = parse_pdf(folder / "sample_7_table_a.pdf", floating_template)
    ref, value = next((r, v) for r, _n, v in iter_values(result) if "\n" in v["value"])
    original = value["value"]
    handle_value(value, "correct", original + "\n補一行")
    assert value["original"] == original
    path = write_excel([result], tmp_path / "out.xlsx")
    book = load_workbook(path)
    cells = [c for sheet in book.worksheets for row in sheet.iter_rows() for c in row
             if c.value == original + "\n補一行"]
    assert cells and all(c.alignment.wrap_text for c in cells if c.parent.title != "待檢查")
    review = book["待檢查"]
    header = [c.value for c in review[1]]
    row = next(dict(zip(header, (c.value for c in r))) for r in review.iter_rows(min_row=2)
               if r[header.index("抓到的值")].value == original + "\n補一行")
    assert original in row["處理"]  # 原值的換行也留著
    handle_value(value, "revert")
    assert value["value"] == original
