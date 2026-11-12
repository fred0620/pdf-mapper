"""儲存格可以有多行：確認、修改、就地編輯、另開視窗都要保留換行。"""
from helpers import run_parse

PENDING = "#right .review-item.review, #right .review-item.missing"


def _multiline_pending(page):
    """回傳第一個值有換行的待檢查項目與它的值。"""
    items = page.locator(PENDING)
    for i in range(items.count()):
        item = items.nth(i)
        value = item.locator("textarea").input_value()
        if "\n" in value:
            return item, value
    raise AssertionError("範例裡應該有多行的值")


def _cell(page, ref):
    return page.locator(f'#drawer td[data-ref="{ref}"]')


def _wait_text(locator, text):
    """多行文字要逐字比對（expect 的 to_have_text 會把換行當空白）。"""
    for _ in range(50):
        if locator.inner_text() == text:
            return
        locator.page.wait_for_timeout(100)
    assert locator.inner_text() == text


def test_confirm_keeps_lines(page, samples):
    run_parse(page, samples, ["sample_7_table_a.pdf"], "浮動表格")
    item, value = _multiline_pending(page)
    ref = item.get_attribute("data-ref")
    lines = value.count("\n") + 1
    assert int(item.locator("textarea").get_attribute("rows")) == min(lines, 6)  # 每行都看得到
    assert _cell(page, ref).inner_text() == value  # 表格也顯示換行

    item.get_by_role("button", name="確認").click()
    record = page.locator(f'#right .review-item.handled[data-ref="{ref}"]')
    record.wait_for()
    assert "已確認" in record.locator(".why").inner_text()  # 沒改就是確認，不會變成修改
    assert record.locator(".change strong").inner_text() == value
    assert _cell(page, ref).inner_text() == value


def test_correct_adds_a_line(page, samples):
    run_parse(page, samples, ["sample_7_table_a.pdf"], "浮動表格")
    item, value = _multiline_pending(page)
    ref = item.get_attribute("data-ref")
    box = item.locator("textarea")
    box.click()
    page.keyboard.press("Control+End")
    page.keyboard.press("Shift+Enter")  # Shift+Enter 換行，不會送出
    page.keyboard.type("補一行")
    assert page.locator(f'#right .review-item.handled[data-ref="{ref}"]').count() == 0
    page.keyboard.press("Enter")
    record = page.locator(f'#right .review-item.handled[data-ref="{ref}"]')
    record.wait_for()
    expected = value + "\n補一行"
    assert record.locator(".change .old").inner_text() == value
    assert record.locator(".change strong").inner_text() == expected
    _wait_text(_cell(page, ref), expected)


def test_edit_multiline_cell_in_place(page, samples):
    run_parse(page, samples, ["sample_7_table_a.pdf"], "浮動表格")
    _item, value = _multiline_pending(page)
    ref = _item.get_attribute("data-ref")
    cell = _cell(page, ref)

    cell.dblclick()
    editor = page.locator(".cell-edit")
    assert editor.input_value() == value  # 打開時是完整的多行內容
    height = editor.evaluate("el => el.clientHeight")
    assert height >= editor.evaluate("el => el.scrollHeight") - 2  # 不用捲動就看得到全部
    page.keyboard.press("Enter")  # 沒改就按 Enter，不算修改
    page.wait_for_timeout(300)
    assert page.locator(f'#right .review-item.handled[data-ref="{ref}"]').count() == 0
    assert cell.inner_text() == value

    cell.dblclick()
    page.keyboard.press("Control+Home")
    page.keyboard.press("Shift+End")
    page.keyboard.type("改第一行")
    page.keyboard.press("Enter")
    expected = "\n".join(["改第一行", *value.split("\n")[1:]])
    _wait_text(_cell(page, ref), expected)
    record = page.locator(f'#right .review-item.handled[data-ref="{ref}"]')
    assert record.locator(".change .old").inner_text() == value

    # 點選後在右邊修改，看到的也是完整的多行內容
    _cell(page, ref).click()
    panel = page.locator("#right .review-item.selected textarea")
    assert panel.input_value() == expected

    record.get_by_role("button", name="還原，放回待檢查").click()
    page.locator(f'#right .review-item.review[data-ref="{ref}"], #right .review-item.missing[data-ref="{ref}"]').wait_for()
    _wait_text(_cell(page, ref), value)


def test_popout_keeps_lines(page, context, samples):
    run_parse(page, samples, ["sample_7_table_a.pdf"], "浮動表格")
    _item, value = _multiline_pending(page)
    ref = _item.get_attribute("data-ref")
    with context.expect_page() as info:
        page.locator(".drawer-bar").get_by_role("button", name="在新視窗開啟").click()
    popup = info.value
    cell = popup.locator(f'#drawer td[data-ref="{ref}"]')
    cell.wait_for()
    assert cell.inner_text() == value

    cell.dblclick()
    popup.keyboard.press("Control+End")
    popup.keyboard.press("Shift+Enter")
    popup.keyboard.type("視窗加的")
    popup.keyboard.press("Enter")
    expected = value + "\n視窗加的"
    record = page.locator(f'#right .review-item.handled[data-ref="{ref}"]')
    record.wait_for()
    assert record.locator(".change strong").inner_text() == expected
    _wait_text(popup.locator(f'#drawer td[data-ref="{ref}"]'), expected)
