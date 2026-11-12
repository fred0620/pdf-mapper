"""畫面測試共用的操作。"""
from __future__ import annotations

from playwright.sync_api import expect


def run_parse(page, samples, files: list[str], template_name: str = "報單") -> None:
    """在「解析 PDF」加入檔案、選範本、開始解析，等到完成。"""
    folder, _ = samples
    page.click("#tabRun")
    page.set_input_files("#filePicker", [str(folder / name) for name in files])
    page.wait_for_selector(".docs li")
    page.locator(".template-picks label", has_text=template_name).locator("input").check()
    page.get_by_role("button", name="開始解析").click()
    # 「待檢查」標題和「開始解析」按鈕在解析前就存在，不能拿來判斷完成：
    # 要等每份檔案都有結果，按鈕也從「解析中」變回來
    done = page.locator(".docs .meta.warn, .docs .meta.good, .docs .meta.bad")
    expect(done).to_have_count(len(files), timeout=120_000)
    expect(page.get_by_role("button", name="開始解析")).to_be_enabled(timeout=120_000)
    page.locator("#drawer td[data-ref]").first.wait_for()


def pending_count(page) -> int:
    text = page.locator("#right h2", has_text="待檢查").inner_text()
    return int(text.split()[1])
