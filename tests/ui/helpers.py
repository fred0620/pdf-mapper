"""畫面測試共用的操作。"""
from __future__ import annotations


def run_parse(page, samples, files: list[str], template_name: str = "報單") -> None:
    """在「解析 PDF」加入檔案、選範本、開始解析，等到完成。"""
    folder, _ = samples
    page.click("#tabRun")
    page.set_input_files("#filePicker", [str(folder / name) for name in files])
    page.wait_for_selector(".docs li")
    page.locator(".template-picks label", has_text=template_name).locator("input").check()
    page.get_by_role("button", name="開始解析").click()
    page.wait_for_selector("#right h2:has-text('待檢查')", timeout=120_000)
    page.get_by_role("button", name="開始解析").wait_for(timeout=120_000)


def pending_count(page) -> int:
    text = page.locator("#right h2", has_text="待檢查").inner_text()
    return int(text.split()[1])
