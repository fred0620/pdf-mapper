"""每個導覽步驟都要有看得見的指引（浮標、虛線靶框或外框高亮），而且行動句不能是空的。
掃過 10 個實地練習與 2 個新手關卡；完成畫面不檢查。"""
import pytest
from playwright.sync_api import expect

from helpers import visible_emphasis

LABS = [
    "feat-pos-field", "feat-cell-extract", "feat-regex", "feat-format-check", "feat-cross-page",
    "feat-header", "feat-endmark", "feat-checks", "feat-output", "run-multi-template",
]


def scan(page) -> list[str]:
    """用指令條的「下一步」逐步往前，記下哪些步驟沒有指引或沒有行動句。"""
    problems: list[str] = []
    strip = page.locator("#missionStrip")
    for _ in range(14):
        badge = strip.locator(".mission-badge")
        if "done" in (badge.get_attribute("class") or ""):
            break  # 完成畫面
        number = badge.inner_text().split()[0]
        action = strip.locator(".mission-action").inner_text().strip()
        seen = 0
        for _ in range(12):  # 靶框、浮標會在切頁或重繪後才出現，最多等 3 秒
            seen = visible_emphasis(page)
            if seen:
                break
            page.wait_for_timeout(250)
        if not action:
            problems.append(f"第 {number} 步沒有行動句")
        if not seen:
            problems.append(f"第 {number} 步沒有浮標、虛線靶框或外框：{action}")
        nxt = strip.get_by_role("button", name="下一步")
        if nxt.is_disabled():
            break
        nxt.click()
        page.wait_for_timeout(400)
    return problems


@pytest.mark.parametrize("spotlight", LABS)
def test_every_lab_step_has_guidance(page, spotlight):
    page.locator("#helpBtn").click()
    page.locator(f'#helpPopover [data-spotlight="{spotlight}"]').click()
    page.locator("#spotLabBtn").click()
    expect(page.locator("#guideBar .guide-name")).to_have_text("實地練習", timeout=30_000)
    problems = scan(page)
    assert not problems, f"{spotlight}：{problems}"


def test_every_train_step_has_guidance(page):
    page.click("#demoStartBtn")
    expect(page.locator("#guideBar .guide-name")).to_be_visible(timeout=30_000)
    problems = scan(page)
    assert not problems, f"新手建立範本：{problems}"


def test_every_run_step_has_guidance(page):
    page.click("#tabRun")
    page.click("#demoStartBtn")
    expect(page.locator(".docs .meta.warn, .docs .meta.good")).to_have_count(2, timeout=120_000)
    problems = scan(page)
    assert not problems, f"新手解析 PDF：{problems}"


def start(page, spotlight):
    page.locator("#helpBtn").click()
    page.locator(f'#helpPopover [data-spotlight="{spotlight}"]').click()
    page.locator("#spotLabBtn").click()
    expect(page.locator("#guideBar .guide-name")).to_have_text("實地練習", timeout=30_000)


def has_guidance(page):
    """靶框、浮標或外框要在 3 秒內出現，同時行動句不是空的。"""
    expect(page.locator("#missionStrip .mission-action")).not_to_have_text("")
    for _ in range(12):
        if visible_emphasis(page):
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"沒有指引：{page.locator('#missionStrip .mission-action').inner_text()}")


def test_header_lab_real_flow_always_has_guidance(page):
    start(page, "feat-header")
    has_guidance(page)  # 步驟 1
    page.locator('#right .subtabs [data-tab="place"]').click()
    has_guidance(page)  # 步驟 2：指向「框選表頭」
    expect(page.locator("#missionPointer")).to_be_visible()
    page.locator("#right .header-pick").click()
    has_guidance(page)  # 進入框選模式：畫布虛線靶框
    expect(page.locator("#overlay .guide-ghost")).to_be_visible()


def test_cross_page_lab_real_flow_always_has_guidance(page):
    start(page, "feat-cross-page")
    has_guidance(page)
    page.locator('#right .subtabs [data-tab="place"]').click()
    has_guidance(page)  # 步驟 2：翻頁
    page.locator('#toolbar button[aria-label="下一頁"]').click()
    has_guidance(page)  # 步驟 3：第 2 頁，指向「在目前這一頁加範圍」
    expect(page.locator("#missionStrip .mission-action")).to_contain_text("在目前這一頁加範圍")
    page.locator("#addRegionBtn").click()
    has_guidance(page)
    expect(page.locator("#overlay .guide-ghost")).to_be_visible()
