"""實地練習（labs）：labs.json、練習 PDF、練習範本與 /api/demo-samples 的 lab 模式。"""
import json
import re
from pathlib import Path

import pytest

import pdfmapper.server as server
from pdfmapper import template as tpl
from pdfmapper.document import Document
from pdfmapper.parser import parse_pdf

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
    return template


@pytest.mark.parametrize("lab_id", sorted(LABS))
def test_lab_files_steps_and_expected_values(lab_id):
    lab = LABS[lab_id]
    assert (DEMO / lab["pdf"]).is_file() and (DEMO / lab["template"]).is_file()
    for step in lab["steps"]:
        assert re.search(rf'id: "{step}"|labVerifyStep\("{step}"', LABS_JS), step
    assert re.search(rf'id: "feat-[\w-]+".*?lab: "{lab_id}"', SPOTLIGHTS_JS, re.S)
    assert lab["spotlight"] in SPOTLIGHTS_JS
    template = solved(lab_id)
    with Document(DEMO / lab["pdf"]) as reference:
        tpl.finalize(template, reference)
    result = parse_pdf(DEMO / lab["pdf"], template)
    verify = lab["verify"]
    if verify["kind"] == "new_field":
        got = [f["value"] for f in result["fields"] if f["id"] == "f2"]
        expect = [verify["expect"]]
    else:
        table = next(t for t in result["tables"] if t["id"] == verify["table"])
        got = [row["cells"][verify["column"]]["value"] for row in table["rows"]]
        expect = verify["expect"]
    assert [v.replace("\r\n", "\n") for v in got] == expect
    assert result["status"] == "ok"


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
        assert data["lab"]["id"] == lab_id and data["lab"]["steps"] == lab["steps"] and data["lab"]["verify"] == lab["verify"]
        assert "pdf" not in data["lab"] and "template" not in data["lab"]
        assert len(data["docs"]) == 1 and data["docs"][0]["demo"] and data["template"]["template_id"].startswith("lab_")
        assert "patch" not in json.dumps(data["template"])
    assert not list(templates.iterdir())  # 練習範本不寫入範本資料夾
