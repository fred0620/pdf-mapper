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
