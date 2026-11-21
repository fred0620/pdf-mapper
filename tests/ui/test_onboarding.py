"""新手導覽：建立範本 8 步、解析 PDF 6 步、說明選單與進階功能入口、共用規則。"""
import json
import re

from playwright.sync_api import expect

from helpers import click_at, draw_box, visible_emphasis

import pdfmapper.server as server

# 示範發票（sample_6_invoice.pdf）上的位置，和 app/pdfmapper/demo/invoice_demo.json 相同
INVOICE_NO = ([0.1, 0.173, 0.2, 0.196], [0.28, 0.17, 0.9, 0.21])
ISSUE_DATE = ([0.1, 0.233, 0.2, 0.256], [0.28, 0.23, 0.9, 0.27])
TOTAL = ([0.6, 0.858, 0.68, 0.881], [0.76, 0.855, 0.92, 0.89])
ITEMS = [0.08, 0.47, 0.92, 0.8]
ITEM_DIVIDERS = [0.18, 0.58, 0.76]
TARGET = re.compile(r"\bguide-pointed\b")  # 浮標正指著的目標


def strip(page):
    return page.locator("#missionStrip")


def expect_step(page, number: int, text: str) -> None:
    expect(strip(page).locator(".mission-badge")).to_have_text(str(number))
    expect(strip(page).locator(".mission-action")).to_contain_text(text)


def test_train_journey_with_demo_invoice(page):
    page.click("#demoStartBtn")
    expect(page.locator("#guideBar")).to_be_visible(timeout=30_000)
    expect(strip(page)).to_have_attribute("aria-live", "polite")
    expect_step(page, 1, "在左欄輸入範本名稱")
    expect(page.locator("#missionPointer")).to_be_visible()
    expect(page.locator("#templateName")).to_have_class(TARGET)

    strip(page).get_by_role("button", name="幫我填").click()
    expect(page.locator("#templateName")).to_have_value("商業發票（練習）")
    expect_step(page, 2, "發票號碼")
    ghost = page.locator("#overlay .guide-ghost")
    expect(ghost).to_have_count(1)
    expect(ghost.locator(".guide-ghost-tag")).to_contain_text("發票號碼")
    rect, sheet = ghost.bounding_box(), page.locator("#overlay").bounding_box()
    assert abs((rect["x"] - sheet["x"]) / sheet["width"] - INVOICE_NO[0][0]) < 0.01  # 虛線指向「發票號碼」標題
    assert visible_emphasis(page) <= 1

    page.keyboard.press("k")
    draw_box(page, INVOICE_NO[0])
    expect(ghost.locator(".guide-ghost-tag")).to_contain_text("再框住它的值")  # 記下標題後切到值框
    rect = ghost.bounding_box()
    assert abs((rect["x"] - sheet["x"]) / sheet["width"] - INVOICE_NO[1][0]) < 0.01
    draw_box(page, INVOICE_NO[1])
    expect_step(page, 3, "開立日期")
    expect(page.locator(".guide-step.done")).to_have_count(2)

    draw_box(page, ISSUE_DATE[0])
    expect(ghost.locator(".guide-ghost-tag")).to_contain_text("再框住它的值")  # 等標題讀完再框值
    draw_box(page, ISSUE_DATE[1])
    type_select = page.locator('#right select[aria-label="資料類型"]')
    expect(type_select).to_have_class(TARGET)
    assert visible_emphasis(page) <= 1
    type_select.select_option("date")
    expect_step(page, 4, "明細")

    page.keyboard.press("t")
    draw_box(page, ITEMS)
    lines = page.locator("#overlay .guide-ghost-line")
    expect(lines).to_have_count(3)
    for remaining, x in zip((2, 1, 0), ITEM_DIVIDERS):
        click_at(page, x, 0.6)
        expect(lines).to_have_count(remaining)  # 每切一條就隱藏那一條
    expect_step(page, 5, "判斷新列")
    expect(page.locator("#keyColumn")).to_have_class(TARGET)
    assert visible_emphasis(page) <= 1

    page.locator("#keyColumn").select_option(index=1)
    expect_step(page, 6, "自動找")
    page.locator("#suggestAnchorsBtn").click()
    expect_step(page, 7, "總金額")

    page.keyboard.press("k")
    draw_box(page, TOTAL[0])
    expect(ghost.locator(".guide-ghost-tag")).to_contain_text("再框住它的值")
    draw_box(page, TOTAL[1])
    expect(page.locator("#rightBackBtn")).to_have_class(TARGET)
    page.locator("#rightBackBtn").click()
    page.locator("#checksDetails > summary").click()
    expect(page.locator("#checkAddBtn")).to_have_class(TARGET)
    page.locator("#checkTypeSelect").select_option("sum_column")
    page.locator("#checkColSelect").select_option(index=4)
    page.locator("#checkTargetSelect").select_option(label="總金額")
    page.locator("#checkAddBtn").click()
    expect_step(page, 8, "測試")

    page.locator("#testBtn").click()
    expect(page.locator("#saveButton")).to_have_class(TARGET, timeout=60_000)
    page.locator("#saveButton").click()
    expect(strip(page).locator(".mission-action")).to_have_text("範本做好了")
    expect(page.locator(".guide-step.done")).to_have_count(8)
    assert (server.TEMPLATES / "商業發票_練習_.json").exists()
    page.once("dialog", lambda dialog: dialog.accept())
    strip(page).get_by_role("button", name="刪除練習範本").click()
    expect(page.locator("#toast")).to_contain_text("已刪除練習範本")
    assert not [p for p in server.TEMPLATES.glob("*.json") if "練習" in json.loads(p.read_text("utf-8"))["name"]]


def start_run_demo(page):
    page.click("#tabRun")
    page.click("#demoStartBtn")
    expect(page.locator(".docs .meta.warn, .docs .meta.good")).to_have_count(2, timeout=120_000)


def test_run_journey_with_demo_files(page, context):
    start_run_demo(page)
    expect(page.locator(".docs li[aria-current=true]")).to_contain_text("有疑點")  # 解析完切到異常檔
    expect_step(page, 2, "橘色")
    expect(strip(page).locator(".legend-row li")).to_have_count(5)
    expect(strip(page).locator(".legend-row")).to_contain_text("待檢查缺值已處理正常整份提示")

    # 直接修改第一個示警（沒先按定位）：停在第 3 步並指向還原，看見處理紀錄後才到第 4 步
    item = page.locator("#right .review-item.review, #right .review-item.missing").first
    item.locator("textarea").fill("人工值")
    item.locator("textarea").press("Enter")
    expect_step(page, 3, "改對按 Enter")
    expect(page.locator("#right .review-item.handled .linkish")).to_have_class(TARGET)
    expect(strip(page).locator(".mission-tip")).to_contain_text("還原")
    expect_step(page, 4, "正常格")

    normal = page.locator("#drawer td[data-ref]:not(.review):not(.missing):not(.handled)").first
    expect(normal).to_have_class(TARGET)
    page.locator("#drawer td.handled").first.click()  # 剛處理過的格子不算正常格
    page.wait_for_timeout(400)
    expect_step(page, 4, "正常格")

    # 在另開的表格視窗點選正常格並修改，主視窗也會推進
    with context.expect_page() as info:
        page.locator("#popTableBtn").click()
    popup = info.value
    popup.wait_for_selector("#drawer td[data-ref]")
    expect(popup.locator("#nextFlaggedBtn")).to_be_visible()  # 實用功能，表格視窗保留
    for hidden in ("#guideBar", "#missionStrip", "#missionPointer", ".drawer-tip"):
        expect(popup.locator(hidden)).to_be_hidden()
    cell = popup.locator("#drawer td[data-ref]:not(.review):not(.missing):not(.handled)").nth(1)
    ref = cell.get_attribute("data-ref")
    cell.click()
    expect_step(page, 5, "儲存修改")
    popup.locator(f'#drawer td[data-ref="{ref}"]').dblclick()
    popup.locator(".cell-edit").fill("微調\n第二行")
    popup.locator(".cell-edit").press("Enter")
    expect_step(page, 6, "匯出")
    with popup.expect_event("close"):
        page.locator("#popnote").get_by_role("button", name="收回").click()
    expect(page.locator(f'#drawer td[data-ref="{ref}"]')).to_have_text("微調\n第二行")

    with page.expect_download() as download:
        page.locator("#exportExcelBtn").click()
    assert download.value.suggested_filename.startswith("示範_")
    expect(strip(page).locator(".mission-action")).to_have_text("核對流程走完了")
    assert [run for run in server._runs.values() if run.get("demo")]  # 示範解析另外標記，不佔正式紀錄


def test_next_flagged_jumps_across_files(page, samples):
    from helpers import run_parse

    run_parse(page, samples, ["sample_1_standard.pdf", "sample_5_errors.pdf"])
    page.locator(".docs li", has_text="sample_1_standard.pdf").locator(".doc-open").click()
    page.locator("#nextFlaggedBtn").click()
    expect(page.locator(".docs li[aria-current=true]")).to_contain_text("sample_5_errors.pdf")
    expect(page.locator("#overlay .box.focus")).to_have_count(1)
    expect(page.locator("#drawer td.focus")).to_have_count(1)


def open_help(page):
    page.locator("#helpBtn").click()
    expect(page.locator("#helpPopover")).to_be_visible()


def test_help_menu_stays_after_closing_guide(page):
    page.click("#demoStartBtn")
    expect(page.locator("#guideBar")).to_be_visible(timeout=30_000)
    page.locator("#guideCloseBtn").click()
    expect(page.locator("#guideBar")).to_be_hidden()
    page.reload()
    page.wait_for_selector("#version:not(:empty)")
    expect(page.locator("#guideBar")).to_be_hidden()
    expect(page.locator("#missionStrip")).to_be_hidden()
    expect(page.locator("#helpBtn")).to_be_visible()
    stored = json.loads(page.evaluate("localStorage.getItem('pdfmapper.onboarding.v1')"))
    assert stored["dismissed"] is True and stored["trainStep"] == "train-1"  # 進度保留，只存步驟 id 與旗標
    assert "示範" not in json.dumps(stored, ensure_ascii=False)

    open_help(page)
    expect(page.locator("#helpGuide-train")).to_contain_text("進行到 1/8")
    expect(page.locator("#helpManual")).to_have_attribute("href", "/manual")
    page.locator('#helpPopover [data-spotlight="feat-output"]').click()
    expect(page.locator("#helpPopover")).to_be_hidden()
    card = page.locator("#coachCard")
    expect(card).to_contain_text("輸出整理")
    expect(page.locator("#outputBtn")).to_have_class(re.compile(r"\bguide-target\b"))
    page.keyboard.press("Escape")
    expect(card).to_be_hidden()

    # 另一分頁的項目：先切換分頁
    open_help(page)
    page.locator('#helpPopover [data-spotlight="run-multi-template"]').click()
    expect(page.locator("#tabRun")).to_have_attribute("aria-current", "page")
    expect(card).to_contain_text("多個範本自動挑選")
    expect(page.locator("#left .template-picks")).to_have_class(re.compile(r"\bguide-target\b"))
    open_help(page)
    expect(page.locator('#helpPopover [data-spotlight="run-multi-template"]')).to_contain_text("已看過")
    page.keyboard.press("Escape")  # Esc 先關說明選單
    expect(page.locator("#helpPopover")).to_be_hidden()

    # 從說明選單繼續導覽
    page.click("#tabTrain")
    open_help(page)
    page.locator("#helpGuide-train").click()
    expect(page.locator("#guideBar")).to_be_visible()


def test_feature_needing_pdf_offers_demo(page):
    open_help(page)
    page.locator('#helpPopover [data-spotlight="feat-cell-extract"]').click()
    card = page.locator("#coachCard")
    expect(card).to_contain_text("需要先有表格")
    card.get_by_role("button", name="用示範發票看").click()
    expect(card).to_contain_text("表格 6 種取值", timeout=30_000)
    expect(card.get_by_role("button", name="用示範發票看")).to_have_count(0)
    expect(page.locator('#right select[aria-label="這一欄怎麼取值"]')).to_have_class(re.compile(r"\bguide-target\b"))
    expect(page.locator("#saveButton")).to_have_text("另存成我的範本")  # 觀摩範本唯讀
    expect(page.locator("#guideBar")).to_be_hidden()  # 只看功能，不開始新手關卡

    # 右欄的 ? 只開說明卡，不切換畫面
    page.keyboard.press("Escape")
    hint = page.locator("#right .help-hint", has_text="?").first
    hint.click()
    expect(card).to_be_visible()
    expect(page.locator('#right select[aria-label="這一欄怎麼取值"]')).to_be_visible()
    assert page.locator(".guide-target").count() == 0
    page.keyboard.press("Escape")
    expect(card).to_be_hidden()


def test_showcase_tour_and_reopen_with_work(page, samples):
    page.locator("#showcaseBtn").click()
    card = page.locator("#coachCard")
    expect(card).to_contain_text("框好的欄位", timeout=30_000)
    expect(card).to_contain_text("1 / 4")
    for title in ("表格的直欄與判斷列", "加總檢查", "測試與另存"):
        card.get_by_role("button", name="下一項").click()
        expect(card).to_contain_text(title)
    card.get_by_role("button", name="完成").click()
    expect(card).to_be_hidden()

    # 已有工作時重開導覽：先問要在目前的 PDF 上繼續，還是改用示範發票
    open_help(page)
    page.locator("#helpGuide-train").click()
    expect(card).to_contain_text("要怎麼開始導覽？")
    card.get_by_role("button", name="在目前的 PDF 上繼續").click()
    expect(page.locator("#guideBar")).to_be_visible()
    expect(page.locator("#overlay .guide-ghost")).to_have_count(0)  # 不是示範模式，不畫虛線靶框


def test_escape_in_cell_edit_only_cancels_edit(page):
    start_run_demo(page)
    expect(page.locator("#missionStrip")).to_be_visible()
    cell = page.locator("#drawer td[data-ref]:not(.review):not(.missing)").first
    text = cell.inner_text()
    cell.dblclick()
    page.locator(".cell-edit").fill("不要存\n第二行")
    page.locator(".cell-edit").press("Escape")
    expect(page.locator(".cell-edit")).to_have_count(0)
    expect(cell).to_have_text(text)
    expect(page.locator("#missionStrip")).to_be_visible()
    expect(page.locator("#missionPointer")).to_be_visible()


def test_legacy_dismissed_key_is_migrated(page):
    page.evaluate("localStorage.clear(); localStorage.setItem('pdfmapper.onboarding.dismissed', '1')")
    page.reload()
    page.wait_for_selector("#version:not(:empty)")
    stored = json.loads(page.evaluate("localStorage.getItem('pdfmapper.onboarding.v1')"))
    assert stored["dismissed"] is True
    assert page.evaluate("localStorage.getItem('pdfmapper.onboarding.dismissed')") is None
    expect(page.locator("#demoStartBtn")).to_have_class("welcome-card quiet")  # 關閉過導覽：入口改成不搶眼


def test_demo_samples_rejects_bad_mode_and_foreign_origin(page, app_url):
    assert page.request.post(f"{app_url}/api/demo-samples", data={"mode": "../etc"}).status == 400
    blocked = page.request.post(f"{app_url}/api/demo-samples", data={"mode": "run"},
                                headers={"Origin": "https://evil.example"})
    assert blocked.status == 403
