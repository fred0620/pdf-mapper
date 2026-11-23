"""使用手冊的畫面：左側目錄、離線搜尋，以及工具裡「複製給 AI 的提問」按鈕。"""
import re

import pytest
from playwright.sync_api import expect


@pytest.fixture
def manual(context, app_url):
    page = context.new_page()
    page.emulate_media(reduced_motion="reduce")  # 不用平滑捲動，位置立刻到位
    page.goto(f"{app_url}/manual")
    expect(page.locator("#manualBody h1")).to_be_visible()
    return page


def test_manual_search_jumps_to_anchor(manual):
    manual.locator("#manualSearch").fill("開頭文字")
    results = manual.locator("#manualResults a")
    expect(results.first).to_be_visible()
    assert results.count() >= 2
    expect(manual.locator("#manualResults mark").first).to_have_text("開頭文字")
    href = results.first.get_attribute("href")
    results.first.click()
    expect(manual).to_have_url(re.compile(rf"#{re.escape(href[1:])}$"))
    expect(manual.locator("#manualResults")).to_be_hidden()
    target = manual.locator(f'[id="{href[1:]}"]')
    expect(target).to_be_in_viewport()
    # 目錄也跟著標示到這一節
    expect(manual.locator(f'nav.sidebar a[aria-current="true"]')).to_have_count(1)


def test_manual_search_by_title_and_keyboard(manual):
    manual.keyboard.press("/")
    expect(manual.locator("#manualSearch")).to_be_focused()
    manual.keyboard.type("格式檢查")
    expect(manual.locator("#manualResults a").first).to_contain_text("格式")
    manual.keyboard.press("Enter")
    expect(manual).to_have_url(re.compile(r"#.+"))
    manual.locator("#manualSearch").fill("zzzz不存在的字")
    expect(manual.locator("#manualResults .none")).to_have_text("找不到符合的內容")
    manual.keyboard.press("Escape")
    expect(manual.locator("#manualResults")).to_be_hidden()


def test_manual_sidebar_tracks_scroll_and_print_hides_chrome(manual):
    sidebar = manual.locator("nav.sidebar")
    expect(sidebar).to_be_visible()
    chapters = sidebar.locator(":scope > ul > li > a")
    assert chapters.count() >= 8  # 7 章加附錄
    assert sidebar.locator("ul ul a").count() > 10  # 節
    manual.evaluate("location.hash = 'regex'")  # h4 不在目錄，標示它所在的節「抓值」
    expect(sidebar.locator('a[aria-current="true"]')).to_have_text("抓值")
    manual.evaluate("location.hash = 'ai'")
    expect(sidebar.locator('a[aria-current="true"]')).to_have_text("5. 讓 AI 幫你設定")
    manual.emulate_media(media="print")
    expect(sidebar).to_be_hidden()
    expect(manual.locator(".topbar")).to_be_hidden()


def test_manual_uses_images_and_readable_fonts(manual):
    assert manual.locator("#manualBody img[src^='data:image/png']").count() >= 10
    sizes = manual.evaluate("""() => [...document.querySelectorAll('#manualBody p, #manualBody td, #manualBody code, nav.sidebar a, .search input')]
        .map(e => parseFloat(getComputedStyle(e).fontSize))""")
    assert min(sizes) >= 12.5
    assert manual.evaluate("getComputedStyle(document.querySelector('#manualBody p')).fontSize") == "14px"


def test_whats_new_page_shares_layout(context, app_url):
    page = context.new_page()
    page.goto(f"{app_url}/docs/%E6%8F%9B%E7%89%88%E8%AA%AA%E6%98%8E.html")
    expect(page.locator("nav.sidebar")).to_be_visible()
    expect(page.locator("#manualSearch")).to_be_visible()


# 複製給 AI 的提問

@pytest.fixture
def clip_page(browser, app_url):
    context = browser.new_context(viewport={"width": 1440, "height": 900}, permissions=["clipboard-read", "clipboard-write"])
    errors: list[str] = []
    context.on("weberror", lambda error: errors.append(str(error.error)))
    page = context.new_page()
    page.goto(app_url)
    page.wait_for_selector("#version:not(:empty)")
    yield page
    context.close()
    assert not errors, errors


def read_clipboard(page) -> str:
    return page.evaluate("navigator.clipboard.readText()")


def open_card(page, spotlight: str):
    page.locator("#helpBtn").click()
    page.locator(f'#helpPopover [data-spotlight="{spotlight}"]').click()
    expect(page.locator("#coachCard #trialText")).to_be_visible()


def test_copy_ai_prompt_from_regex_card(clip_page):
    page = clip_page
    open_card(page, "feat-regex")
    page.locator("#trialText").fill("Ref INV-2026-0301\n第二行 rev2")
    page.locator("#trialPattern").fill(r"(INV-\d{4}-\d{4})")
    expect(page.locator("#trialResult")).to_contain_text("INV-2026-0301")
    page.locator("#trialCopyAi").click()
    expect(page.locator("#toast")).to_have_text("已複製，貼到公司的 AI")
    text = read_clipboard(page)
    assert "請幫我寫一個 Python re 語法的正規表達式，用在一個 PDF 擷取工具。" in text
    assert "取第一個括號裡的內容" in text and "(?i)" in text
    assert "Ref INV-2026-0301\n第二行 rev2" in text  # 多行原始內容原樣保留
    assert r"目前的規則：(INV-\d{4}-\d{4})" in text
    assert "目前的試算結果：抓到「INV-2026-0301」" in text


def test_copy_ai_prompt_format_check_uses_format_template(clip_page):
    page = clip_page
    open_card(page, "feat-format-check")
    page.locator("#trialText").fill("1234567")
    page.locator("#trialPattern").fill(r"^\d{8}$")
    expect(page.locator("#trialResult")).to_contain_text("不符合")
    page.locator("#trialCopyAi").click()
    text = read_clipboard(page)
    assert "用來檢查欄位格式" in text and "用在一個 PDF 擷取工具" not in text
    assert "1234567" in text and "應該通過：" in text and "目前的試算結果：不符合" in text


def test_copy_ai_prompt_from_column_settings_uses_preview_rows(clip_page):
    page = clip_page
    page.locator("#showcaseBtn").click()
    page.wait_for_selector("#coachCard:not([hidden])", timeout=30_000)
    page.keyboard.press("Escape")
    page.locator("#right .items li button", has_text="品項明細").click()
    page.locator('button.column-more[aria-label="品項 的設定"]').click()
    page.locator("#columnCopyAi").click()  # 還沒試抓：請使用者自己貼例子
    assert "（請貼上幾個真實的例子）" in read_clipboard(page)
    page.locator("#right .column-preview-btn").click()
    expect(page.locator("#right .preview-list li").first).to_be_visible(timeout=60_000)
    raws = page.locator("#right .preview-list li span").all_inner_texts()
    page.locator("#columnCopyAi").click()
    text = read_clipboard(page)
    assert len(raws) >= 2 and "原始內容 1：" in text and "原始內容 4：" not in text  # 最多帶前 3 列
    for raw in raws[:3]:
        assert raw in text


def test_copy_ai_prompt_falls_back_to_textarea(clip_page):
    page = clip_page
    open_card(page, "feat-regex")
    page.evaluate("""() => {
      Object.defineProperty(navigator, 'clipboard', { value: { writeText: () => Promise.reject(new Error('blocked')) } });
      document.execCommand = () => { window.__copied = document.querySelector('#aiPromptFallback').value; return true; };
    }""")
    page.locator("#trialText").fill("共 11 頁")
    page.locator("#trialCopyAi").click()
    expect(page.locator("#toast")).to_have_text("已複製，貼到公司的 AI")
    assert "共 11 頁" in page.evaluate("window.__copied")
    expect(page.locator("#aiPromptFallback")).to_have_count(0)
