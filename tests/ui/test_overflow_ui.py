"""內容超出分隔線：分段選擇的點選、鍵盤操作與說明卡。"""
from playwright.sync_api import expect
from test_advanced import no_console_errors, open_feature  # noqa: F401  no_console_errors 是 autouse fixture


def test_overflow_segmented_control(page):
    card = open_feature(page, "feat-column-preview")
    card.get_by_role("button", name="用示範發票看").click()
    expect(card.get_by_role("button", name="試試看")).to_be_visible(timeout=30_000)
    page.keyboard.press("Escape")

    group = page.locator('#right [role="radiogroup"][aria-label="內容超出分隔線"]')
    # exact：name 預設是子字串比對，「可超出」會同時比對到「不可超出」
    auto = group.get_by_role("radio", name="自動", exact=True)
    allow = group.get_by_role("radio", name="可超出", exact=True)
    deny = group.get_by_role("radio", name="不可超出", exact=True)
    expect(group).to_be_visible()
    expect(auto).to_have_attribute("aria-checked", "true")
    expect(page.locator("#right .overflow-note")).to_contain_text("自動判斷歸屬")

    deny.click()
    expect(deny).to_have_attribute("aria-checked", "true")
    expect(auto).to_have_attribute("aria-checked", "false")
    expect(page.locator("#right .overflow-note")).to_contain_text("硬邊界")

    deny.press("ArrowLeft")  # 鍵盤切換，焦點跟著走
    expect(allow).to_have_attribute("aria-checked", "true")
    expect(allow).to_be_focused()

    # 收合再打開同一欄，設定還在
    opener = page.locator("#right .column-more[aria-expanded='true']")
    label = opener.get_attribute("aria-label")
    opener.click()
    page.locator(f'#right .column-more[aria-label="{label}"]').click()
    expect(page.locator('#right [role="radio"][aria-checked="true"]')).to_have_text("可超出")


def test_overflow_help_card_opens(page):
    card = open_feature(page, "feat-overflow")
    expect(card).to_contain_text("長內容壓到隔壁欄")
