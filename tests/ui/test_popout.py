"""另開視窗核對：PDF 與結果表格移到另一個視窗，兩邊同步。"""
from playwright.sync_api import expect

from helpers import pending_count, run_parse


def _open(page, context, button):
    with context.expect_page() as info:
        button.click()
    popup = info.value
    popup.wait_for_load_state()
    return popup


def test_table_popout_syncs_both_ways(page, context, samples):
    run_parse(page, samples, ["sample_6_invoice.pdf"])
    popup = _open(page, context, page.locator(".drawer-bar").get_by_role("button", name="在新視窗開啟"))
    popup.wait_for_selector("#drawer td[data-ref]")
    page.wait_for_selector("body.table-out")
    assert not page.locator("#drawer").is_visible()
    assert "結果表格在另一個視窗" in page.locator("#popnote").inner_text()
    assert not popup.locator("#right").is_visible() and not popup.locator("#stage").is_visible()

    # 在表格視窗點一格，主視窗的 PDF 標出位置
    cell = popup.locator("#drawer td.review, #drawer td.missing").first
    ref = cell.get_attribute("data-ref")
    cell.click()
    page.wait_for_selector(".box.focus")

    # 在主視窗點待檢查，表格視窗跟著選到
    item = page.locator("#right .review-item.review, #right .review-item.missing").nth(1)
    other = item.get_attribute("data-ref")
    item.locator("button.locate").click()
    popup.wait_for_selector(f'#drawer td.focus[data-ref="{other}"]')

    # 在表格視窗修改，主視窗的待檢查與處理紀錄跟著更新
    total = pending_count(page)
    popup.locator(f'#drawer td[data-ref="{ref}"]').dblclick()
    popup.locator(".cell-edit").fill("視窗改的")
    popup.keyboard.press("Enter")
    page.locator(f'#right .review-item.handled[data-ref="{ref}"]').wait_for()
    assert pending_count(page) == total - 1

    with popup.expect_event("close"):
        page.locator("#popnote").get_by_role("button", name="收回").click()
    page.wait_for_selector("body:not(.table-out)")
    assert page.locator("#drawer").is_visible()
    assert page.locator(f'#drawer td[data-ref="{ref}"]').inner_text() == "視窗改的"


def test_pdf_popout_follows_selection(page, context, samples):
    run_parse(page, samples, ["sample_1_standard.pdf"])
    popup = _open(page, context, page.locator("#toolbar").get_by_role("button", name="在新視窗開啟"))
    popup.wait_for_selector("#pageImage")
    page.wait_for_selector("body.pdf-out")
    assert not page.locator("#stage").is_visible() and page.locator("#drawer").is_visible()
    assert not popup.locator("#drawer").is_visible()

    # 主視窗點第 2 頁的明細，PDF 視窗翻到第 2 頁並標出位置
    row = page.locator("#drawer table").last.locator("tbody tr", has=page.locator("td:first-child", has_text="2")).first
    row.locator("td[data-ref]").first.click()
    expect(popup.locator("#toolbar .pager")).to_contain_text("第 2 /")
    popup.wait_for_selector(".box.focus")

    # PDF 視窗翻頁，主視窗也記住目前頁數；收回後看到同一頁
    popup.get_by_role("button", name="下一頁").click()
    popup.get_by_role("button", name="收回到主視窗").click()
    page.wait_for_selector("body:not(.pdf-out)")
    assert "第 3 /" in page.locator("#toolbar .pager").inner_text()


def test_main_reload_closes_popouts(page, context, samples):
    run_parse(page, samples, ["sample_6_invoice.pdf"])
    popup = _open(page, context, page.locator(".drawer-bar").get_by_role("button", name="在新視窗開啟"))
    popup.wait_for_selector("#drawer td[data-ref]")
    page.evaluate("window.onbeforeunload = null")
    with popup.expect_event("close"):
        page.reload()
