"""畫面測試：在本機啟動工具，用電腦上已有的 Edge 或 Chrome 實際操作。

執行：uv run --project app --group ui pytest tests/ui
沒有安裝 playwright 或找不到瀏覽器時整組跳過（CI 映像檔沒有瀏覽器）。
指定瀏覽器：設定環境變數 PDFMAPPER_TEST_BROWSER 為瀏覽器執行檔路徑。
"""
from __future__ import annotations

import os
import threading

import pytest

sync_api = pytest.importorskip("playwright.sync_api", reason="沒有安裝 playwright（uv sync --group ui）")

import pdfmapper.server as server  # noqa: E402
from pdfmapper import template as tpl  # noqa: E402


def _launch(playwright):
    chromium = playwright.chromium
    attempts = []
    if os.environ.get("PDFMAPPER_TEST_BROWSER"):
        attempts.append({"executable_path": os.environ["PDFMAPPER_TEST_BROWSER"]})
    attempts += [{"channel": "msedge"}, {"channel": "chrome"}, {}]
    for options in attempts:
        try:
            return chromium.launch(**options)
        except Exception:  # noqa: BLE001 這個瀏覽器不在，換下一個
            continue
    pytest.skip("找不到 Edge 或 Chrome，可設定 PDFMAPPER_TEST_BROWSER")


@pytest.fixture(scope="session")
def browser():
    with sync_api.sync_playwright() as playwright:
        browser = _launch(playwright)
        yield browser
        browser.close()


@pytest.fixture(scope="session")
def app_url(tmp_path_factory, template, invoice_template):
    """啟動真正的本機服務，範本、上傳與輸出都放在暫存資料夾。"""
    from werkzeug.serving import make_server

    home = tmp_path_factory.mktemp("ui-home")
    saved = {name: getattr(server, name) for name in ("TEMPLATES", "UPLOADS", "OUTPUT")}
    for name in saved:
        folder = home / name.lower()
        folder.mkdir()
        setattr(server, name, folder)
    tpl.save({**template, "template_id": "customs", "name": "報單"}, server.TEMPLATES / "customs.json")
    tpl.save({**invoice_template, "template_id": "invoice", "name": "發票"}, server.TEMPLATES / "invoice.json")
    httpd = make_server("127.0.0.1", 0, server.app, threaded=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    for name, value in saved.items():
        setattr(server, name, value)


@pytest.fixture
def context(browser):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    errors: list[str] = []
    context.on("weberror", lambda error: errors.append(str(error.error)))
    yield context
    context.close()
    assert not errors, f"頁面發生錯誤：{errors}"


@pytest.fixture
def page(context, app_url):
    page = context.new_page()
    page.goto(app_url)
    page.wait_for_selector("#version:not(:empty)")
    return page
