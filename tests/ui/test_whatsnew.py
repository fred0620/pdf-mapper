"""新功能導覽：第一次使用不顯示、升級後的小點與小卡、逐項導覽、之後再說、導覽進行中與另開視窗。"""
import json
import re

import pytest
from playwright.sync_api import expect

KEY = "pdfmapper.onboarding.v1"


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


def current_version(page) -> str:
    return page.locator("#version").inner_text().lstrip("v")


def stored(page) -> dict:
    return json.loads(page.evaluate(f"localStorage.getItem('{KEY}')") or "{}")


def reload_with(page, prefs: dict) -> None:
    page.evaluate(f"localStorage.setItem('{KEY}', {json.dumps(json.dumps(prefs))})")
    page.reload()
    page.wait_for_selector("#version:not(:empty)")


def test_first_use_does_not_show_whats_new(page):
    expect(page.locator("#helpBtn")).to_be_visible()
    page.wait_for_timeout(1600)  # 小卡在啟動 1.2 秒後才會出現
    expect(page.locator("#whatsNewCard")).to_be_hidden()
    expect(page.locator("#helpBtn .help-dot")).to_be_hidden()
    assert stored(page)["whatsnewSeen"] == current_version(page)


def test_upgrade_shows_dot_card_and_tour(page):
    reload_with(page, {"whatsnewSeen": "0.3.1"})
    dot = page.locator("#helpBtn .help-dot")
    card = page.locator("#whatsNewCard")
    expect(dot).to_be_visible()
    expect(card).to_be_visible()
    expect(card).to_contain_text("更新了 3 項")
    expect(card).to_contain_text("說明選單、跳到下一個待檢查…")
    card.get_by_role("button", name="看看").click()
    expect(card).to_be_hidden()
    coach = page.locator("#coachCard")
    expect(coach).to_contain_text("說明選單")
    expect(coach).to_contain_text("1 / 3")
    expect(page.locator("#helpBtn")).to_have_class(re.compile(r"\bguide-target\b"))
    coach.get_by_role("button", name="下一項").click()
    expect(coach).to_contain_text("跳到下一個待檢查")
    expect(coach.get_by_role("button", name="用示範發票看")).to_be_visible()  # 需要 PDF 才能指給你看
    coach.get_by_role("button", name="下一項").click()
    expect(coach).to_contain_text("用示範發票邊做邊學")
    expect(page.locator("#tabTrain")).to_have_attribute("aria-current", "page")
    expect(dot).to_be_visible()
    coach.get_by_role("button", name="完成").click()
    expect(dot).to_be_hidden()  # 看完最後一項，小點消失
    assert stored(page)["whatsnewSeen"] == current_version(page)


def test_later_keeps_dot_until_history_is_opened(page):
    reload_with(page, {"whatsnewSeen": "0.3.1"})
    card = page.locator("#whatsNewCard")
    dot = page.locator("#helpBtn .help-dot")
    expect(card).to_be_visible()
    card.get_by_role("button", name="之後再說").click()
    expect(card).to_be_hidden()
    expect(dot).to_be_visible()
    page.reload()
    page.wait_for_selector("#version:not(:empty)")
    expect(dot).to_be_visible()
    page.wait_for_timeout(1600)
    expect(card).to_be_hidden()  # 小卡只出現一次

    page.locator("#helpBtn").click()
    row = page.locator("#helpWhatsNew")
    expect(row).to_contain_text("新增 3 項")
    row.click()
    popover = page.locator("#helpPopover")
    expect(popover.locator(".whatsnew-version")).to_have_count(1)
    expect(popover).to_contain_text("跳到下一個待檢查")
    expect(dot).to_be_hidden()
    popover.locator('[data-spotlight="help-menu"]').click()
    expect(page.locator("#coachCard")).to_contain_text("說明選單")


def test_guide_running_only_lights_dot(page):
    reload_with(page, {"whatsnewSeen": "0.3.1", "trainStep": "train-1"})
    expect(page.locator("#guideBar")).to_be_visible()
    expect(page.locator("#helpBtn .help-dot")).to_be_visible()
    page.wait_for_timeout(1600)
    expect(page.locator("#whatsNewCard")).to_be_hidden()


def test_popouts_hide_guide_parts(context, app_url):
    for mode in ("pdf", "table"):
        popout = context.new_page()
        popout.add_init_script(f"localStorage.setItem('{KEY}', JSON.stringify({{whatsnewSeen: '0.3.1', trainStep: 'train-1'}}))")
        popout.goto(f"{app_url}/?popout={mode}")
        popout.wait_for_selector("body.popout")
        popout.wait_for_timeout(1600)
        for sel in ("#guideBar", "#missionStrip", "#coachCard", "#helpPopover", "#whatsNewCard", "#missionPointer",
                    "#helpBtn"):
            expect(popout.locator(sel)).to_be_hidden()
        popout.close()
