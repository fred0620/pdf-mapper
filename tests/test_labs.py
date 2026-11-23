"""實地練習（labs）：labs.json、練習 PDF、練習範本與 /api/demo-samples 的 lab 模式。"""
import json
import re
from pathlib import Path

import pytest

import pdfmapper.server as server
from pdfmapper import template as tpl
from pdfmapper.document import Document
from pdfmapper.clean import output_columns
from pdfmapper.parser import parse_best, parse_pdf

DEMO = Path(server.DEMO)
LABS = json.loads((DEMO / "labs.json").read_text(encoding="utf-8"))
LABS_JS = (server.WEB / "labs.js").read_text(encoding="utf-8")
SPOTLIGHTS_JS = (server.WEB / "spotlights.js").read_text(encoding="utf-8")


def solved(lab_id):
    """照練習的標準做法改好範本。"""
    template = tpl.load(DEMO / LABS[lab_id]["template"])
    if lab_id == "pos-field":
        template["fields"].append({"id": "f2", "name": "單號", "kind": "position", "page_rule": "first", "ref_page": 0,
                                   "value_box": [0.62, 0.046, 0.84, 0.08], "type": "text", "required": True})
    elif lab_id == "cell-extract":
        column = template["tables"][0]["columns"][2]
        column.update(start="ECCN:", end="line")
    elif lab_id == "regex":
        template["tables"][0]["columns"][1]["extract"] = r"INV-\d{4}-\d{4}"
    elif lab_id == "format-check":
        template["fields"][0]["pattern"] = r"^\d{8}$"
    elif lab_id == "cross-page":
        table = template["tables"][0]
        table["regions"].append({"page_rule": "rest", "ref_page": 1, "box": [0.08, 0.22, 0.92, 0.6],
                                 "dividers": table["regions"][0]["dividers"]})
    elif lab_id == "header":
        template["tables"][0]["regions"][0]["header"] = {"text": "Line", "box": [0.085, 0.165, 0.17, 0.195]}
    elif lab_id == "sum-fields":
        template["validations"] = [{"type": "sum_fields", "fields": ["subtotal", "tax"], "equals": "total", "tolerance": 1}]
    elif lab_id == "output":
        template["output"] = {"fields": [{"id": "invoice_no", "include": True, "name": "Doc No"},
                                         {"id": "amount", "include": True, "name": ""},
                                         {"id": "customer", "include": True, "name": ""},
                                         {"id": "note", "include": False, "name": ""}]}
    elif lab_id == "endmark":
        template["tables"][0]["end_marker"] = {"text": "Total", "box": [0.2, 0.5, 0.29, 0.54], "ref_page": 0}
    return template


def lab_pdfs(lab):
    return lab.get("pdfs") or [lab["pdf"]]


def table_column(result, verify):
    table = next(t for t in result["tables"] if t["id"] == verify["table"])
    return [row["cells"][verify["column"]]["value"] for row in table["rows"]]


def lab_templates(lab):
    return lab.get("templates") or [lab["template"]]


@pytest.mark.parametrize("lab_id", sorted(LABS))
def test_lab_files_steps_and_expected_values(lab_id):
    lab = LABS[lab_id]
    assert all((DEMO / pdf).is_file() for pdf in lab_pdfs(lab)) and all((DEMO / t).is_file() for t in lab_templates(lab))
    assert len(lab.get("doc_names") or [lab["doc_name"]]) == len(lab_pdfs(lab))
    for step in lab["steps"]:
        assert re.search(rf'id: "{step}"|lab(?:Verify|Place)Step\("{step}"', LABS_JS), step
    assert re.search(rf'id: "feat-[\w-]+".*?lab: "{lab_id}"', SPOTLIGHTS_JS, re.S)
    assert lab["spotlight"] in SPOTLIGHTS_JS
    if lab.get("templates"):
        assert lab.get("view") == "run" and len(lab["template_names"]) == len(lab["templates"]) == len(lab_pdfs(lab))
        assert re.search(rf'LAB_RUN_VIEW = \[[^\]]*"{lab_id}"', LABS_JS)
        return _check_run_lab(lab)
    template = solved(lab_id)
    with Document(DEMO / lab_pdfs(lab)[0]) as reference:
        tpl.finalize(template, reference)
    results = [parse_pdf(DEMO / pdf, template) for pdf in lab_pdfs(lab)]
    verify = lab["verify"]
    if verify["kind"] == "new_field":
        got = [f["value"] for f in results[0]["fields"] if f["id"] == "f2"]
        assert got == [verify["expect"]]
    elif verify["kind"] == "field_flag":
        field = next(f for f in results[0]["fields"] if f["id"] == verify["field"])
        assert field["value"] == verify["value"] and verify["reason"] in field["reasons"]
    elif verify["kind"] == "sum_check":
        field = next(f for f in results[0]["fields"] if f["id"] == verify["equals"])
        assert verify["reason"] in field["reasons"]
        rule = template["validations"][0]
        assert rule["fields"] == verify["fields"] and rule["equals"] == verify["equals"]
    elif verify["kind"] == "output":
        available = [(f["id"], f["name"]) for f in template["fields"]]
        assert [name for _id, name in output_columns(template["output"]["fields"], available)] == verify["expect"]
    elif verify.get("per_doc"):
        assert len(results) == len(verify["expect"])
        for result, expect in zip(results, verify["expect"]):
            assert [v.replace("\r\n", "\n") for v in table_column(result, verify)] == expect
    else:
        assert [v.replace("\r\n", "\n") for v in table_column(results[0], verify)] == verify["expect"]
    assert all(r["status"] in ("ok", "review") for r in results)
    if verify["kind"] not in ("field_flag", "sum_check"):
        assert all(r["status"] == "ok" for r in results)


def _check_run_lab(lab):
    """兩個格式的練習 PDF 同時丟給兩個範本，每份都要自己挑到自己的範本（和 /api/runs 的練習解析相同的做法）。"""
    templates = []
    for file, pdf in zip(lab["templates"], lab_pdfs(lab)):
        template = tpl.load(DEMO / file)
        with Document(DEMO / pdf) as reference:
            tpl.finalize(template, reference)
        templates.append(template)
    for pdf, expect in zip(lab_pdfs(lab), lab["verify"]["expect"]):
        result = parse_best(DEMO / pdf, templates)
        assert result["template_id"] == expect and result["status"] == "ok", pdf
    # 只勾一個範本時，另一份會被硬套，驗證不會過
    wrong = parse_best(DEMO / lab_pdfs(lab)[1], templates[:1])
    assert wrong["template_id"] != lab["verify"]["expect"][1]


def test_lab_unsolved_templates_fail_the_check():
    """沒做步驟的練習範本一開始不能已經通過驗證，否則練習沒意義。"""
    for lab_id in ("format-check", "cross-page", "header", "endmark", "sum-fields"):
        lab = LABS[lab_id]
        template = tpl.load(DEMO / lab["template"])
        with Document(DEMO / lab_pdfs(lab)[0]) as reference:
            tpl.finalize(template, reference)
        results = [parse_pdf(DEMO / pdf, template) for pdf in lab_pdfs(lab)]
        verify = lab["verify"]
        if verify["kind"] == "field_flag":
            assert verify["reason"] not in results[0]["fields"][0]["reasons"]
            continue
        if verify["kind"] == "sum_check":
            assert not template["validations"] and verify["reason"] not in next(
                f for f in results[0]["fields"] if f["id"] == verify["equals"])["reasons"]
            continue
        expects = verify["expect"] if verify.get("per_doc") else [verify["expect"]]
        assert any(table_column(r, verify) != e for r, e in zip(results, expects)), lab_id


def test_lab_pdfs_stay_small():
    assert sum(p.stat().st_size for p in (DEMO / "labs").glob("*.pdf")) < 300_000


def test_demo_samples_lab_mode(tmp_path, monkeypatch):
    uploads, templates = tmp_path / "uploads", tmp_path / "templates"
    templates.mkdir()
    monkeypatch.setattr(server, "UPLOADS", uploads)
    monkeypatch.setattr(server, "TEMPLATES", templates)
    client = server.app.test_client()
    try:
        _check_lab_mode(client, templates)
    finally:
        for doc_id in list(server._docs):
            server._docs.pop(doc_id).close()


def _check_lab_mode(client, templates):
    for body in ({"mode": "lab"}, {"mode": "lab", "lab": "nope"}, {"mode": "lab", "lab": "../labs"},
                 {"mode": "lab", "lab": 3}, {"mode": "lab", "lab": ["regex"]}):
        assert client.post("/api/demo-samples", json=body).status_code == 400, body
    blocked = client.post("/api/demo-samples", json={"mode": "lab", "lab": "regex"}, headers={"Origin": "https://evil.example"})
    assert blocked.status_code == 403
    cross = client.post("/api/demo-samples", json={"mode": "lab", "lab": "regex"}, headers={"Sec-Fetch-Site": "cross-site"})
    assert cross.status_code == 403
    assert client.post("/api/demo-samples", json={"mode": "lab", "lab": "regex"}, headers={"Host": "evil.example"}).status_code == 403
    for lab_id, lab in LABS.items():
        data = client.post("/api/demo-samples", json={"mode": "lab", "lab": lab_id}).json
        if lab.get("templates"):
            assert [t["name"] for t in data["templates"]] == lab["template_names"] and "template" not in data
            assert [t["id"] for t in data["templates"]] == lab["verify"]["expect"]
            assert len(data["docs"]) == len(lab_pdfs(lab)) and "patch" not in json.dumps(data)
            assert data["lab"]["steps"] == lab["steps"] and data["lab"]["view"] == "run"
            continue
        assert data["lab"]["id"] == lab_id and data["lab"]["steps"] == lab["steps"] and data["lab"]["verify"] == lab["verify"]
        assert "pdf" not in data["lab"] and "template" not in data["lab"]
        assert len(data["docs"]) == len(lab_pdfs(lab)) and all(d["demo"] for d in data["docs"])
        assert [d["name"] for d in data["docs"]] == (lab.get("doc_names") or [lab["doc_name"]])
        assert data["template"]["template_id"].startswith("lab_")
        assert "patch" not in json.dumps(data["template"])
    assert not list(templates.iterdir())  # 練習範本不寫入範本資料夾


def test_lab_run_endpoint_only_uses_the_lab_templates(tmp_path, monkeypatch):
    import time
    uploads, templates = tmp_path / "uploads", tmp_path / "templates"
    templates.mkdir()
    monkeypatch.setattr(server, "UPLOADS", uploads)
    monkeypatch.setattr(server, "TEMPLATES", templates)
    client = server.app.test_client()
    try:
        data = client.post("/api/demo-samples", json={"mode": "lab", "lab": "multi-template"}).json
        docs = [d["id"] for d in data["docs"]]
        ids = [t["id"] for t in data["templates"]]
        post = lambda body: client.post("/api/runs", json=body)  # noqa: E731
        for body in ({"demo": "lab", "docs": docs, "template_ids": ids},  # 沒有 lab id
                     {"demo": "lab", "lab": "regex", "docs": docs, "template_ids": ids},  # 不是解析練習
                     {"demo": "lab", "lab": "nope", "docs": docs, "template_ids": ids},
                     {"demo": "lab", "lab": ["multi-template"], "docs": docs, "template_ids": ids},
                     {"demo": "lab", "lab": "multi-template", "docs": docs, "template_ids": ["customs"]},
                     {"demo": "lab", "lab": "multi-template", "docs": docs, "template_ids": "lab_run_a"}):
            assert post(body).status_code == 400, body
        assert post({"demo": "lab", "lab": "multi-template", "docs": docs, "template_ids": []}).status_code in (400, 422)
        run_id = post({"demo": "lab", "lab": "multi-template", "docs": docs, "template_ids": ids}).json["run_id"]
        for _ in range(100):
            status = client.get(f"/api/runs/{run_id}").json
            if status["finished"]:
                break
            time.sleep(0.2)
        assert [r["template_id"] for r in status["results"]] == ids and status["demo"] is True
        assert not list(templates.iterdir())
    finally:
        for doc_id in list(server._docs):
            server._docs.pop(doc_id).close()
