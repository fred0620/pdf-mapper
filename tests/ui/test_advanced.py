"""進階功能：分組選單與目標導向標題、說明卡結構、看手冊連結、小導覽、規則試算、套用到這一欄、可點的圖例。"""
import re

import pytest
from playwright.sync_api import expect

GUIDE_TARGET = re.compile(r"\bguide-target\b")


@pytest.fixture(autouse=True)
def no_console_errors(context):
    """頁面不能有任何 console error（瀏覽器自己要的 favicon 除外）。"""
    errors: list[str] = []

    def collect(msg):
        if msg.type == "error" and "favicon" not in (msg.location or {}).get("url", ""):
            errors.append(f"{msg.text} {(msg.location or {}).get('url', '')}")
    context.on("console", collect)
    yield
    assert not errors, f"console error：{errors}"


def open_feature(page, spotlight: str):
    page.locator("#helpBtn").click()
    page.locator(f'#helpPopover [data-spotlight="{spotlight}"]').click()
    card = page.locator("#coachCard")
    expect(card).to_be_visible()
    return card


def test_menu_groups_and_goal_titles(page, app_url):
    page.locator("#helpBtn").click()
    popover = page.locator("#helpPopover")
    sections = popover.locator(".help-section h3")
    expect(sections).to_contain_text(["新手導覽", "進階功能：建立範本", "進階功能：解析 PDF"])
    expect(popover.locator(".help-group")).to_have_text(["抓值", "表格", "檢查與輸出", "核對", "瀏覽", "匯出"])
    for title in ("值旁邊沒有標題怎麼抓", "一格有好幾個值，只取一個", "用規則抓特定格式的值", "內容格式不對就標記",
                  "改完設定，先試抓這一欄", "明細接到下一頁", "表格開始的位置不固定", "表格長度不固定",
                  "加總對不上時提醒我", "只輸出需要的欄位、改欄名", "顏色代表什麼", "直接跳到下一個要看的",
                  "在表格裡直接改字", "兩個螢幕對照", "只交出確認過的資料", "一次丟不同格式的 PDF"):
        expect(popover.get_by_role("button", name=title)).to_have_count(1)
    page.click("#tabRun")
    page.locator("#helpBtn").click()
    page.locator("#helpBtn").click()
    expect(popover.locator(".help-group").first).to_have_text("核對")  # 目前分頁的排前面

    # 看手冊：新分頁開啟、連到手冊裡明確的錨點
    card = open_feature(page, "feat-regex")
    link = card.locator("#spotManualLink")
    expect(link).to_have_attribute("href", "/docs/使用手冊.html#regex")
    expect(link).to_have_attribute("target", "_blank")
    manual = page.request.get(f"{app_url}/docs/使用手冊.html")
    assert manual.ok and 'id="regex"' in manual.text()


def test_regex_trial(page):
    card = open_feature(page, "feat-regex")
    expect(card.locator(".card-symbols dt")).to_have_count(4)  # 4 行符號速查
    result = card.locator("#trialResult")
    expect(result).to_have_text("抓到「11」")  # 預設範例：第1頁/共11頁
    text, pattern = card.locator("#trialText"), card.locator("#trialPattern")
    text.fill("ECCN: 5A992\nOrigin: TW")  # 多行內容
    pattern.fill(r"Origin:\s*(\S+)")
    expect(result).to_have_text("抓到「TW」")
    pattern.fill(r"Invoice:\s*(\S+)")
    expect(result).to_have_text("沒抓到，這格會留空並標記")
    pattern.fill(r"(\d+\s?)+")
    expect(result).to_contain_text("卡住")  # 危險寫法和儲存範本時一樣被擋
    card.locator("#trialPreset").select_option(label="日期")
    expect(result).to_have_text("抓到「2026/03/01」")
    expect(card.locator("#trialApply")).to_have_count(0)  # 從選單打開，沒有可以套用的欄
    page.keyboard.press("Escape")

    card = open_feature(page, "feat-format-check")
    result = card.locator("#trialResult")
    expect(result).to_have_text("不符合，這格會標記給人看")  # 1234567 少一碼
    card.locator("#trialText").fill("12345678")
    expect(result).to_have_text("符合")


def test_cross_page_mini_tour_with_demo(page):
    card = open_feature(page, "feat-cross-page")
    expect(card.locator(".card-examples")).to_contain_text("一張表 14 列")
    expect(card).to_contain_text("需要先載入範例 PDF")
    card.get_by_role("button", name="用示範發票看").click()
    expect(card).to_contain_text("切到「位置」分頁", timeout=30_000)
    expect(card).to_contain_text("1 / 3")
    tab = page.locator('#right .subtabs [data-tab="place"]')
    expect(tab).to_have_class(GUIDE_TARGET)
    tab.click()
    expect(card).to_contain_text("翻到第 2 頁")  # 做到了自動跳下一步
    expect(card).to_contain_text("2 / 3")
    card.get_by_role("button", name="下一項").click()  # 示範發票只有 1 頁
    expect(card).to_contain_text("按「在目前這一頁加範圍」")
    button = page.locator("#addRegionBtn")
    expect(button).to_have_class(GUIDE_TARGET)
    button.click()
    expect(page.locator('[data-tool]').first).to_be_visible()
    expect(page.locator("#hint")).to_contain_text("框住這一頁的資料區")
    card.get_by_role("button", name="完成").click()
    expect(card).to_be_hidden()


def test_apply_regex_to_column_and_try_preview(page):
    card = open_feature(page, "feat-column-preview")
    card.get_by_role("button", name="用示範發票看").click()
    expect(card.get_by_role("button", name="試試看")).to_be_visible(timeout=30_000)
    card.get_by_role("button", name="試試看").click()
    expect(page.locator("#right .preview-list li").first).to_be_visible(timeout=30_000)  # 直接試抓這一欄
    page.keyboard.press("Escape")

    page.locator('#right select[aria-label="這一欄怎麼取值"]').select_option("regex")
    hint = page.locator('#right .help-hint[data-spotlight="feat-regex"]')
    hint.click()
    card = page.locator("#coachCard")
    expect(card.locator("#trialText")).to_have_value(re.compile(r"\S"))  # 帶入這一欄試抓到的原始內容
    card.locator("#trialPattern").fill(r"(\d+)")
    expect(card.locator("#trialResult")).to_contain_text("抓到「")
    card.get_by_role("button", name="套用到這一欄").click()
    expect(card).to_be_hidden()
    expect(page.locator('#right input[aria-label="正規表達式"]')).to_have_value(r"(\d+)")
    expect(page.locator("#toast")).to_contain_text("已把規則套用到")


def test_legend_jumps_and_try_next_flagged(page):
    page.click("#tabRun")
    page.click("#demoStartBtn")
    expect(page.locator(".docs .meta.warn, .docs .meta.good")).to_have_count(2, timeout=120_000)
    page.locator(".docs li", has_text="正常").locator(".doc-open").click()
    card = open_feature(page, "run-alert-legend")
    card.locator('.legend-chip.pick[data-kind="review"]').click()  # 點色塊跳到第一個待檢查
    expect(page.locator(".docs li[aria-current=true]")).to_contain_text("有疑點")
    expect(page.locator("#drawer td.focus")).to_have_class(re.compile(r"\breview\b"))

    page.locator(".docs li", has_text="正常").locator(".doc-open").click()
    card = open_feature(page, "run-next-flagged")
    card.get_by_role("button", name="試試看").click()
    expect(page.locator(".docs li[aria-current=true]")).to_contain_text("有疑點")
    expect(page.locator("#overlay .box.focus")).to_have_count(1)
    inline = open_feature(page, "run-inline-edit")
    expect(inline.locator(".card-list")).to_contain_text("Shift+Enter")


def test_regex_trial_preset_changes_text_and_pattern(page):
    """換個例子：原始內容與規則都要換掉，結果跟著更新，之後的重繪不能把內容洗回預設。"""
    card = open_feature(page, "feat-regex")
    text, pattern, result = card.locator("#trialText"), card.locator("#trialPattern"), card.locator("#trialResult")
    expect(result).to_have_text("抓到「11」")
    preset = card.locator("#trialPreset")
    preset.focus()
    page.keyboard.press("ArrowDown")  # 鍵盤逐項切換：第一項是預設例子，再往下才會換內容
    page.keyboard.press("ArrowDown")
    expect(text).to_have_value("ECCN: 5A992 Origin: TW")
    expect(pattern).to_have_value(r"ECCN:\s*(\S+)")
    expect(result).to_have_text("抓到「5A992」")
    # 使用者手動改過內容後，視窗大小改變等重繪不能洗掉
    text.fill("ECCN: 9X999")
    expect(result).to_have_text("抓到「9X999」")
    page.set_viewport_size({"width": 1100, "height": 760})
    page.wait_for_timeout(300)
    expect(text).to_have_value("ECCN: 9X999")
    expect(pattern).to_have_value(r"ECCN:\s*(\S+)")
