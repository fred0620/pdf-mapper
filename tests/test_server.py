"""確認網頁用到的匯出路由都存在，單元測試碰不到這一層。"""
import pdfmapper.server as server
from pdfmapper.parser import parse_pdf


def test_export_routes(samples, template, tmp_path, monkeypatch):
    folder, _ = samples
    monkeypatch.setattr(server, "OUTPUT", tmp_path)
    result = parse_pdf(folder / "sample_1_standard.pdf", template)
    server._runs["t"] = {"total": 1, "done": 1, "current": "", "results": [result], "finished": True}
    server._run_templates["t"] = {template["template_id"]: template}
    client = server.app.test_client()
    try:
        for path in ("/api/runs/t/excel", "/api/runs/t/clean", "/api/runs/t/clean?only_confirmed=1"):
            response = client.get(path)
            assert response.status_code == 200, path
            assert response.data[:2] == b"PK"
        assert client.get("/api/runs/t").status_code == 200
        assert "乾淨資料" not in str(client.get("/api/runs/t").json)  # 範本圖塊不會傳到頁面
    finally:
        server._runs.pop("t")
        server._run_templates.pop("t")


def test_rejects_foreign_host_and_origin():
    """擋 DNS rebinding 和其他網站對本機服務發出的請求。"""
    client = server.app.test_client()
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/status", headers={"Host": "evil.example:8765"}).status_code == 403
    assert client.post("/api/heartbeat?client=a", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/heartbeat?client=a", headers={"Origin": "null"}).status_code == 403
    assert client.get("/api/templates", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    ok = client.post("/api/heartbeat?client=a", headers={"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"})
    assert ok.status_code == 200
    server._clients.pop("a", None)


def test_security_headers_and_ping():
    client = server.app.test_client()
    page = client.get("/")
    assert "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
    assert page.headers["X-Content-Type-Options"] == "nosniff"
    ping = client.get("/api/ping")
    assert ping.headers["Cache-Control"] == "no-store"
    assert str(server.ROOT) not in ping.get_data(as_text=True)  # 不外洩本機路徑


def test_errors_do_not_leak_details():
    client = server.app.test_client()
    assert client.get("/api/runs/nope").status_code == 404
    bad = client.post("/api/runs/nope/edit", data="x", content_type="application/json")
    assert bad.status_code in (400, 404) and "Traceback" not in bad.get_data(as_text=True)
    assert client.post("/api/heartbeat").status_code == 400
    assert client.get("/api/templates/CON").status_code == 400


def test_upload_rejects_non_pdf_and_cleans_name(samples, tmp_path, monkeypatch):
    import io

    folder, _ = samples
    monkeypatch.setattr(server, "UPLOADS", tmp_path)
    client = server.app.test_client()
    data = {"files": [(io.BytesIO(b"MZ not a pdf"), "x.pdf"),
                      (io.BytesIO((folder / "sample_1_standard.pdf").read_bytes()), '..\\..\\a<b>:c.pdf')]}
    body = client.post("/api/docs", data=data, content_type="multipart/form-data").json
    assert body["failed"][0]["error"] == "不是 PDF 檔"
    assert body["docs"][0]["name"] == "a_b__c.pdf"
    assert all(p.parent == tmp_path for p in tmp_path.iterdir())
    for doc in body["docs"]:
        server._docs.pop(doc["id"]).close()


def test_excel_neutralizes_formulas_and_control_chars(samples, template, tmp_path):
    from openpyxl import load_workbook

    from pdfmapper.excel import write_excel

    folder, _ = samples
    result = parse_pdf(folder / "sample_1_standard.pdf", template)
    result["file"] = '=HYPERLINK("http://x","y")'
    result["fields"][0]["value"] = "=1+1\x01"
    book = load_workbook(write_excel([result], tmp_path / "x.xlsx"))
    cells = [c for sheet in book.worksheets for row in sheet.iter_rows() for c in row]
    assert all(c.data_type != "f" for c in cells)
    assert any(c.value == "=1+1" for c in cells)
