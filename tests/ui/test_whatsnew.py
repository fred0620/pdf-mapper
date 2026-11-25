"""新功能導覽：第一次使用不顯示、升級後的小點與小卡、逐項導覽、之後再說、導覽進行中與另開視窗。

導覽的機制用固定的假資料測（FROZEN），之後發版新增條目不會讓這些測試失敗。
另有一個測試讀真實的 whatsnew.json，確認目前這一版的條目有顯示出來。
"""
import json
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect

KEY = "pdfmapper.onboarding.v1"
REAL = Path(__file__).resolve().parents[2] / "app" / "pdfmapper" / "web" / "whatsnew.json"

# 固定的假資料：內容是 0.4.0 當時的 4 項，指到的說明卡都是既有的
ITEMS = [
    {"id": "t-help-menu", "title": "找導覽與進階功能",
     "body": "忘了功能在哪時，點頂列「說明」：導覽、進階功能與手冊都在這裡。", "spotlight": "help-menu"},
    {"id": "t-next-flagged", "title": "直接跳到下一個要看的",
     "body": "待檢查分散在不同頁或檔案時，按表格右上角「跳到待檢查」。",
     "tab": "run", "spotlight": "run-next-flagged", "needsDoc": True},
    {"id": "t-demo", "title": "跟著示範發票學",
     "body": "第一次用時，畫面中間可以跟著示範發票做範本、練習核對。", "tab": "train", "spotlight": "welcome-demo"},
    {"id": "t-labs", "title": "進階功能可以實地練習",
     "body": "在進階功能的說明卡按「實地練習」，用練習 PDF 邊做邊驗證。", "tab": "train", "spotlight": "feat-pos-field"},
]
EXTRA = [  # 超過導覽上限（5 項）時用
    {"id": "t-regex", "title": "用規則抓特定格式的值", "body": "值有固定格式時，用規則描述它。", "spotlight": "feat-regex"},
    {"id": "t-header", "title": "表格開始的位置不固定", "body": "框住表頭，表格會跟著移動。", "spotlight": "feat-header"},
]
FROZEN = {"versions": [{"version": "0.4.0", "date": "未發布", "items": ITEMS},
                       {"version": "0.3.1", "date": "未發布", "items": []}]}
FROZEN_SIX = {"versions": [{"version": "0.4.0", "date": "未發布", "items": ITEMS + EXTRA},
                           {"version": "0.3.1", "date": "未發布", "items": []}]}


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


@pytest.fixture
def serve_whatsnew(context):
    """把 whatsnew.json 換成指定的內容；要在 reload_with 之前呼叫。"""
    def serve(data):
        context.route("**/web/whatsnew.json", lambda route: route.fulfill(json=data))
    return serve


def current_version(page) -> str:
    return page.locator("#version").inner_text().lstrip("v")


def stored(page) -> dict:
    return json.loads(page.evaluate(f"localStorage.getItem('{KEY}')") or "{}")


def reload_with(page, prefs: dict) -> None:
    page.evaluate(f"localStorage.setItem('{KEY}', {json.dumps(json.dumps(prefs))})")
    page.reload()
    page.wait_for_selector("#version:not(:empty)")


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def test_first_use_does_not_show_whats_new(page):
    expect(page.locator("#helpBtn")).to_be_visible()
    page.wait_for_timeout(1600)  # 小卡在啟動 1.2 秒後才會出現
    expect(page.locator("#whatsNewCard")).to_be_hidden()
    expect(page.locator("#helpBtn .help-dot")).to_be_hidden()
    assert stored(page)["whatsnewSeen"] == current_version(page)


def test_upgrade_shows_dot_card_and_tour(page, serve_whatsnew):
    serve_whatsnew(FROZEN)
    reload_with(page, {"whatsnewSeen": "0.3.1"})
    dot = page.locator("#helpBtn .help-dot")
    card = page.locator("#whatsNewCard")
    expect(dot).to_be_visible()
    expect(card).to_be_visible()
    expect(card).to_contain_text("更新了 4 項")
    expect(card).to_contain_text("找導覽與進階功能、直接跳到下一個要看的…")
    expect(card.get_by_role("button", name="看全部")).to_have_count(0)  # 沒超過導覽上限
    card.get_by_role("button", name="看看").click()
    expect(card).to_be_hidden()
    coach = page.locator("#coachCard")
    expect(coach).to_contain_text("找導覽與進階功能")
    expect(coach).to_contain_text("什麼時候用：")  # 新功能和進階功能用同一種卡片
    expect(coach).to_contain_text("1 / 4")
    expect(page.locator("#helpBtn")).to_have_class(re.compile(r"\bguide-target\b"))
    coach.get_by_role("button", name="下一項").click()
    expect(coach).to_contain_text("直接跳到下一個要看的")
    expect(coach.get_by_role("button", name="用示範發票看")).to_be_visible()  # 需要 PDF 才能指給你看
    coach.get_by_role("button", name="下一項").click()
    expect(coach).to_contain_text("跟著示範發票學")
    expect(page.locator("#tabTrain")).to_have_attribute("aria-current", "page")
    expect(dot).to_be_visible()
    coach.get_by_role("button", name="下一項").click()
    expect(coach).to_contain_text("值旁邊沒有標題怎麼抓")
    coach.get_by_role("button", name="完成").click()
    expect(dot).to_be_hidden()  # 看完最後一項，小點消失
    assert stored(page)["whatsnewSeen"] == current_version(page)


def test_later_keeps_dot_until_history_is_opened(page, serve_whatsnew):
    serve_whatsnew(FROZEN)
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
    expect(row).to_contain_text("新增 4 項")
    row.click()
    popover = page.locator("#helpPopover")
    expect(popover.locator(".whatsnew-version")).to_have_count(2)
    expect(popover.locator('[data-spotlight="run-next-flagged"]')).to_be_visible()  # 最新的一版預設展開
    expect(popover.locator(".help-empty")).to_have_count(1)
    expect(popover.locator(".help-empty")).to_be_hidden()  # 沒有項目的舊版預設收合
    popover.locator(".whatsnew-version", has_text="0.3.1").locator("summary").click()
    expect(popover.locator(".help-empty")).to_be_visible()  # 點標題可以展開
    expect(dot).to_be_hidden()
    popover.locator('[data-spotlight="help-menu"]').click()
    expect(page.locator("#coachCard")).to_contain_text("找導覽與進階功能")


def test_more_than_the_tour_limit_tours_five_and_offers_all(page, serve_whatsnew):
    serve_whatsnew(FROZEN_SIX)
    reload_with(page, {"whatsnewSeen": "0.3.1"})
    card = page.locator("#whatsNewCard")
    expect(card).to_contain_text("更新了 6 項")
    expect(card.get_by_role("button", name="看全部")).to_be_visible()
    card.get_by_role("button", name="看看").click()
    expect(page.locator("#coachCard")).to_contain_text("1 / 5")  # 導覽最多走 5 項


def test_see_all_opens_the_whole_history(page, serve_whatsnew):
    serve_whatsnew(FROZEN_SIX)
    reload_with(page, {"whatsnewSeen": "0.3.1"})
    card = page.locator("#whatsNewCard")
    expect(card).to_be_visible()
    card.get_by_role("button", name="看全部").click()
    expect(card).to_be_hidden()
    popover = page.locator("#helpPopover")
    expect(popover.locator(".whatsnew-version")).to_have_count(2)
    expect(popover).to_contain_text("表格開始的位置不固定")  # 第 6 項，導覽走不到，清單裡有
    expect(page.locator("#helpBtn .help-dot")).to_be_hidden()  # 打開清單就算看過


def test_real_whatsnew_entries_show_for_the_current_version(page):
    """讀真實的 whatsnew.json：從上一個版本升級時，這一版的條目要顯示出來。"""
    data = json.loads(REAL.read_text(encoding="utf-8"))
    current = current_version(page)
    older = [v["version"] for v in data["versions"] if version_key(v["version"]) < version_key(current)]
    seen = max(older, key=version_key, default="0.0.0")
    fresh = sorted((v for v in data["versions"] if version_key(seen) < version_key(v["version"]) <= version_key(current)),
                   key=lambda v: version_key(v["version"]), reverse=True)  # 新的在前
    items = [item for v in fresh for item in v["items"]]
    reload_with(page, {"whatsnewSeen": seen})
    card = page.locator("#whatsNewCard")
    dot = page.locator("#helpBtn .help-dot")
    if not items:  # 這一版沒有畫面上的改變
        page.wait_for_timeout(1600)
        expect(card).to_be_hidden()
        expect(dot).to_be_hidden()
        return
    expect(dot).to_be_visible()
    expect(card).to_contain_text(f"更新了 {len(items)} 項")
    expect(card).to_contain_text("、".join(item["title"] for item in items[:2]) + ("…" if len(items) > 2 else ""))


def test_guide_running_only_lights_dot(page, serve_whatsnew):
    serve_whatsnew(FROZEN)
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
