"""版面與一致性：清單和右邊的待檢查數一致、頁面縮小時的框名稱、選取框的顏色、視窗太窄的提醒、解析進度只拿新結果。"""
from playwright.sync_api import expect

from helpers import pending_count, run_parse


def test_list_count_matches_review_panel(page, samples):
    run_parse(page, samples, ["sample_6_invoice.pdf"])  # 用不合的範本，有值要檢查，也有整份檔案的提醒
    meta = page.locator(".docs li", has_text="sample_6_invoice.pdf").locator(".meta").inner_text()
    assert f"{pending_count(page)} 項待檢查" in meta
    assert "個提醒" in meta


def test_progress_polls_only_new_results(page, samples):
    seen: list[str] = []
    page.on("request", lambda request: seen.append(request.url) if "/api/runs/" in request.url else None)
    run_parse(page, samples, ["sample_1_standard.pdf", "sample_5_errors.pdf", "sample_2_shifted.pdf"])
    polls = [url for url in seen if "since=" in url]
    assert polls, "解析進度沒有用 since 查詢"
    assert any("since=0" not in url for url in polls), "拿到結果之後應該只查之後的"
    expect(page.locator(".docs .meta.warn, .docs .meta.good, .docs .meta.bad")).to_have_count(3)


def test_tags_hide_when_page_is_small(page, samples):
    folder, _ = samples
    page.set_input_files("#filePicker", str(folder / "sample_1_standard.pdf"))
    page.wait_for_selector(".docs li")
    page.select_option("select[aria-label=開啟已存的範本]", "customs")
    page.wait_for_selector("#overlay .box .tag")
    tag = page.locator("#overlay .box:not(.label) .tag").first
    expect(tag).to_be_visible()
    page.get_by_role("button", name="縮小").click()
    page.get_by_role("button", name="縮小").click()
    page.get_by_role("button", name="縮小").click()
    page.get_by_role("button", name="縮小").click()
    expect(page.locator("#sheet")).to_have_class("sheet compact")
    expect(tag).to_be_hidden()
    box = page.locator("#overlay .box:not(.label)").first
    box.hover()
    expect(box.locator(".tag")).to_be_visible()


def test_focused_box_uses_accent(page, samples):
    run_parse(page, samples, ["sample_6_invoice.pdf"])
    page.locator("#drawer td[data-ref]").first.click()
    focus = page.locator("#overlay .box.focus")
    expect(focus).to_have_count(1)
    shadow = focus.evaluate("node => getComputedStyle(node).boxShadow")
    assert "rgb(59, 130, 246)" in shadow  # Stageshow accent，不是黑色
    cell = page.locator("#drawer td.focus")
    assert "rgb(59, 130, 246)" in cell.evaluate("node => getComputedStyle(node).boxShadow")


def test_narrow_window_note(page):
    note = page.locator(".narrow-note")
    expect(note).to_be_hidden()
    page.set_viewport_size({"width": 900, "height": 800})
    expect(note).to_be_visible()
    page.set_viewport_size({"width": 1440, "height": 900})
    expect(note).to_be_hidden()
