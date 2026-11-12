"""解析畫面：處理紀錄、就地修改。"""
from playwright.sync_api import expect

from helpers import pending_count, run_parse


def test_handled_items_stay_as_records(page, samples):
    run_parse(page, samples, ["sample_6_invoice.pdf"])  # 用不合的範本，警示比較多
    right = page.locator("#right")
    total = pending_count(page)
    assert total >= 3

    first = right.locator(".review-item.review, .review-item.missing").first
    name = first.locator("h3").inner_text()
    first.get_by_role("button", name="確認").click()
    record = right.locator(".review-item.handled", has_text=name)
    record.wait_for()
    assert pending_count(page) == total - 1
    assert right.locator("h2", has_text="處理紀錄 1 項").count() == 1
    assert "原本需檢查" in record.inner_text()

    second = right.locator(".review-item.review, .review-item.missing").first
    second_name = second.locator("h3").inner_text()
    ref = second.get_attribute("data-ref")
    second.locator("textarea").fill("人工值")
    second.get_by_role("button", name="確認").click()
    changed = right.locator(".review-item.handled", has_text=second_name)
    changed.wait_for()
    assert "已人工修改" in changed.inner_text()
    assert "改成「人工值」" in changed.locator(".change").inner_text()
    cell = page.locator(f'#drawer td[data-ref="{ref}"]')
    assert cell.inner_text() == "人工值"
    assert "handled" in cell.get_attribute("class")

    changed.get_by_role("button", name="還原，放回待檢查").click()
    right.locator(f'.review-item.review[data-ref="{ref}"], .review-item.missing[data-ref="{ref}"]').wait_for()
    assert pending_count(page) == total - 1
    assert cell.inner_text() != "人工值"

    while pending_count(page):  # 全部處理完，仍看得到做了什麼
        before = pending_count(page)
        right.locator(".review-item.review, .review-item.missing").first.get_by_role("button", name="確認").click()
        expect(right.locator(".review-item.review, .review-item.missing")).to_have_count(before - 1)
    assert "待檢查都已處理" in page.locator("#pendingNote").inner_text()
    assert right.locator(".review-item.handled").count() == total


def test_edit_any_cell_in_place(page, samples):
    run_parse(page, samples, ["sample_1_standard.pdf"])
    assert "這份沒有需要檢查的值" in page.locator("#pendingNote").inner_text()
    cells = page.locator("#drawer td[data-ref]")
    cell = cells.nth(0)
    ref = cell.get_attribute("data-ref")
    original = cell.inner_text()

    cell.dblclick()
    page.locator(".cell-edit").fill("改過")
    page.keyboard.press("Enter")
    cell = page.locator(f'#drawer td[data-ref="{ref}"]')
    expect(cell).to_have_text("改過")
    assert "handled" in cell.get_attribute("class")
    record = page.locator("#right .review-item.handled")
    assert record.count() == 1 and original in record.inner_text()

    other = page.locator("#drawer td[data-ref]").nth(1)
    other_ref = other.get_attribute("data-ref")
    other_text = other.inner_text()
    other.dblclick()
    page.locator(".cell-edit").fill("不要存")
    page.keyboard.press("Escape")  # Esc 取消
    assert page.locator(f'#drawer td[data-ref="{other_ref}"]').inner_text() == other_text

    page.locator(f'#drawer td[data-ref="{other_ref}"]').dblclick()
    page.locator(".cell-edit").fill("第一行")
    page.keyboard.press("Shift+Enter")  # Shift+Enter 換行
    page.keyboard.type("第二行")
    page.keyboard.press("Enter")
    expect(page.locator(f'#drawer td[data-ref="{other_ref}"]')).to_have_text("第一行\n第二行")

    record.first.get_by_role("button", name="還原成抓到的值").click()
    expect(page.locator(f'#drawer td[data-ref="{ref}"]')).to_have_text(original)


def test_selected_value_can_be_edited_from_panel(page, samples):
    run_parse(page, samples, ["sample_1_standard.pdf"])
    cell = page.locator("#drawer td[data-ref]").nth(2)
    ref = cell.get_attribute("data-ref")
    cell.click()
    assert "focus" in cell.get_attribute("class")
    panel = page.locator("#right .review-item.selected")
    panel.locator("textarea").fill("從右邊改")
    panel.get_by_role("button", name="儲存修改").click()
    expect(page.locator(f'#drawer td[data-ref="{ref}"]')).to_have_text("從右邊改")
    assert page.locator(".box.handled.focus").count() >= 1  # PDF 上的框也標成人工處理過


def test_hover_marks_one_cell(page, samples):
    run_parse(page, samples, ["sample_1_standard.pdf"])
    row = page.locator("#drawer table").last.locator("tbody tr").first
    cells = row.locator("td")
    background = "el => getComputedStyle(el).backgroundColor"
    resting = cells.nth(2).evaluate(background)
    cells.nth(1).hover()
    page.wait_for_timeout(250)
    assert cells.nth(1).evaluate(background) != resting
    assert cells.nth(2).evaluate(background) == resting
