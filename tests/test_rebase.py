"""換基準範例時的重新對位。"""
import copy

from pdfmapper import template as tpl
from pdfmapper.document import Document
from pdfmapper.parser import parse_pdf


def _values(result):
    """所有取到的值（不含座標），依出現順序。"""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("value"), str):
                found.append(node["value"])
            for key, child in node.items():
                if key != "value":
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk([result["fields"], result["tables"]])
    return found


def test_same_reference_changes_nothing(samples, template):
    folder, _ = samples
    with Document(folder / "sample_1_standard.pdf") as doc:
        out = tpl.rebase(template, doc)
    assert {p["status"] for p in out["pages"]} == {"same"}
    assert out["template"] == template  # 座標和圖塊都不動


def test_shifted_reference_moves_boxes_and_still_parses(samples, template):
    folder, _ = samples
    with Document(folder / "sample_2_shifted.pdf") as doc:
        out = tpl.rebase(template, doc)
        rebased = tpl.finalize(out["template"], doc)
    assert all(p["applied"] for p in out["pages"])
    assert rebased["fields"][0]["value_box"] != template["fields"][0]["value_box"]
    for name in ("sample_1_standard.pdf", "sample_2_shifted.pdf"):
        before = parse_pdf(folder / name, template)
        after = parse_pdf(folder / name, rebased)
        assert after["counts"] == before["counts"]
        assert _values(after) == _values(before)


def test_unrelated_reference_keeps_everything(samples, template):
    folder, _ = samples
    original = copy.deepcopy(template)
    with Document(folder / "sample_6_invoice.pdf") as doc:
        out = tpl.rebase(template, doc, include_weak=True)
    assert out["pages"][0]["status"] == "none" and not out["pages"][0]["applied"]
    assert out["template"] == original
    assert template == original  # 不改到傳進來的範本


def test_shorter_reference_keeps_later_pages(samples, template):
    """基準頁數比較少時，沒有的頁面保留原本的座標與圖塊，存檔也不會拿別頁的影像頂替。"""
    folder, _ = samples
    later = [a for a in tpl.collect_anchors(template) if a.get("ref_page", 0) >= 1]
    assert later
    with Document(folder / "sample_6_invoice.pdf") as doc:
        out = tpl.rebase(template, doc)
        saved = tpl.finalize(copy.deepcopy(out["template"]), doc)
    assert out["beyond"] == [2]
    after = {a["id"]: a for a in tpl.collect_anchors(saved)}
    for anchor in later:
        assert after[anchor["id"]]["box"] == anchor["box"]
        assert after[anchor["id"]].get("patch") == anchor.get("patch")


def test_rebase_route(samples, template):
    import io

    import pdfmapper.server as server

    folder, _ = samples
    client = server.app.test_client()
    files = {"files": [(io.BytesIO((folder / "sample_2_shifted.pdf").read_bytes()), "b.pdf")]}
    doc = client.post("/api/docs", data=files, content_type="multipart/form-data").json["docs"][0]
    try:
        body = client.post("/api/rebase", json={"template": template, "reference": doc["id"]}).json
        assert [p["status"] for p in body["pages"]] == ["good", "good"]
    finally:
        client.delete(f"/api/docs/{doc['id']}")
