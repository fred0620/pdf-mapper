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
