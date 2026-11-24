"""版本不一致防護的畫面測試：更新提示列、收起、另開視窗與 heartbeat 連續失敗。"""
from __future__ import annotations

from playwright.sync_api import expect


def test_update_banner_hidden_when_build_matches(context, app_url, monkeypatch):
    """未設定 PDFMAPPER_BUILD_OVERRIDE（指紋一致）時不顯示提示列。"""
    monkeypatch.delenv("PDFMAPPER_BUILD_OVERRIDE", raising=False)
    page = context.new_page()
    page.goto(app_url)
    expect(page.locator("#version")).not_to_be_empty()
    expect(page.locator("#updateBanner")).to_be_hidden()


def test_update_banner_shown_and_dismissible_when_disk_changed(context, app_url, monkeypatch):
    """設 PDFMAPPER_BUILD_OVERRIDE 時顯示 #updateBanner 與正確文字，按「我知道了」收起。"""
    monkeypatch.setenv("PDFMAPPER_BUILD_OVERRIDE", "newhash00001")
    page = context.new_page()
    page.goto(app_url)
    banner = page.locator("#updateBanner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("程式已更新。請關閉所有工具分頁，再重新開啟 run.bat。")
    banner.get_by_role("button", name="我知道了").click()
    expect(banner).to_be_hidden()


def test_update_banner_shown_in_popout(context, app_url, monkeypatch):
    """另開視窗（/?popout=pdf 與 /?popout=table）也會顯示更新提示列。"""
    monkeypatch.setenv("PDFMAPPER_BUILD_OVERRIDE", "newhash00002")
    for mode in ("pdf", "table"):
        popout = context.new_page()
        popout.goto(f"{app_url}/?popout={mode}")
        banner = popout.locator("#updateBanner")
        expect(banner).to_be_visible()
        expect(banner).to_contain_text("程式已更新。請關閉所有工具分頁，再重新開啟 run.bat。")
        popout.close()


def test_heartbeat_three_failures_shows_closed_message(context, app_url, monkeypatch):
    """/api/heartbeat 連續失敗 3 次時，提示文字改為「工具已關閉，請重新開啟 run.bat」。"""
    monkeypatch.setenv("PDFMAPPER_BUILD_OVERRIDE", "newhash00003")
    page = context.new_page()
    page.clock.install()
    page.route("**/api/heartbeat*", lambda route: route.fulfill(status=500, content_type="application/json", body="{}"))
    page.goto(app_url)
    banner = page.locator("#updateBanner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("程式已更新")

    # 載入時已送出第 1 次失敗；再快轉兩次 15 秒間隔共失敗 3 次
    page.clock.run_for(15000)
    page.clock.run_for(15000)
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("工具已關閉，請重新開啟 run.bat")


def test_heartbeat_recovery_hides_closed_message(context, app_url, monkeypatch):
    """「工具已關閉」出現後連線恢復（例如睡眠喚醒），提示列收起；指紋仍不同時改回更新提示。"""
    monkeypatch.delenv("PDFMAPPER_BUILD_OVERRIDE", raising=False)
    page = context.new_page()
    page.clock.install()
    failing = "**/api/heartbeat*"
    page.route(failing, lambda route: route.fulfill(status=500, content_type="application/json", body="{}"))
    page.goto(app_url)
    banner = page.locator("#updateBanner")
    expect(page.locator("#version")).not_to_be_empty()
    page.clock.run_for(15000)
    page.clock.run_for(15000)
    expect(banner).to_contain_text("工具已關閉，請重新開啟 run.bat")

    page.unroute(failing)
    page.clock.run_for(15000)
    expect(banner).to_be_hidden()

    # 再斷一次後恢復，但硬碟上的程式已更新：恢復後顯示更新提示
    page.route(failing, lambda route: route.fulfill(status=500, content_type="application/json", body="{}"))
    for _ in range(3):
        page.clock.run_for(15000)
    expect(banner).to_contain_text("工具已關閉")
    monkeypatch.setenv("PDFMAPPER_BUILD_OVERRIDE", "newhash00004")
    page.unroute(failing)
    page.clock.run_for(15000)
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("程式已更新")
