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


def page_point(page, x: float, y: float) -> tuple[float, float]:
    """PDF 頁面上的相對座標（0 到 1）換成視窗座標。"""
    rect = page.locator("#overlay").bounding_box()
    return rect["x"] + x * rect["width"], rect["y"] + y * rect["height"]


def draw_box(page, box) -> None:
    """在頁面上拖曳框出一個範圍（座標同範本，0 到 1）。"""
    x0, y0 = page_point(page, box[0], box[1])
    x1, y1 = page_point(page, box[2], box[3])
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move((x0 + x1) / 2, (y0 + y1) / 2, steps=4)
    page.mouse.move(x1, y1, steps=4)
    page.mouse.up()


def click_at(page, x: float, y: float) -> None:
    page.mouse.click(*page_point(page, x, y))


def visible_emphasis(page) -> int:
    """同一時間的強調點：虛線靶框、指向浮標、外框高亮最多只能有一種。"""
    kinds = ["#overlay .guide-ghost, #overlay .guide-ghost-line", "#missionPointer", ".guide-target"]
    return sum(1 for sel in kinds if any(page.locator(sel).nth(i).is_visible() for i in range(page.locator(sel).count())))
