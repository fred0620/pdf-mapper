"""進階功能的實地練習：練習 PDF 與練習範本、完成條件綁真實畫面、最後一步用試抓結果驗證。"""
import json
import re

import pytest
from playwright.sync_api import expect

from helpers import draw_box

import pdfmapper.server as server

PO_BOX = [0.62, 0.046, 0.84, 0.08]


@pytest.fixture(autouse=True)
def no_console_errors(context):
    errors: list[str] = []

    def collect(msg):
        if msg.type == "error" and "favicon" not in (msg.location or {}).get("url", ""):
            errors.append(msg.text)
    context.on("console", collect)
    yield
    assert not errors, f"console error：{errors}"


def start_lab(page, spotlight: str) -> None:
    page.locator("#helpBtn").click()
    page.locator(f'#helpPopover [data-spotlight="{spotlight}"]').click()
    expect(page.locator("#spotLabBtn")).to_have_text("實地練習")
    expect(page.locator("#spotGoBtn, #spotDemoBtn").first).to_be_visible()  # 原本的入口還在
    page.locator("#spotLabBtn").click()
    expect(page.locator("#guideBar .guide-name")).to_have_text("實地練習", timeout=30_000)


def action(page):
    return page.locator("#missionStrip .mission-action")


def tip(page):
    return page.locator("#missionStrip .mission-tip")


def open_spec_column(page, name: str):
    page.locator(f'button.column-more[aria-label="{name} 的設定"]').click()


def reopen_column(page, name: str) -> None:
    """測試後右欄回到清單：點表格，欄位設定若還開著就不用再點。"""
    page.locator("#right .items li button").last.click()
    button = page.locator(f'button.column-more[aria-label="{name} 的設定"]')
    if button.inner_text() == "設定":
        button.click()


def finish(page, text: str) -> None:
    expect(page.locator("#labResult")).to_contain_text(text, timeout=30_000)
    expect(page.locator("#labLearned")).not_to_be_empty()
    expect(page.locator("#labManualLink")).to_have_attribute("href", re.compile(r"/docs/使用手冊\.html#.+"))
    expect(page.locator("#labRetryBtn")).to_be_visible()
    expect(page.locator("#labBackBtn")).to_be_visible()


def test_pos_field_lab_wrong_then_right(page):
    start_lab(page, "feat-pos-field")
    expect(page.locator("#templateName")).to_have_value("實地練習：沒有標題的值")
    expect(action(page)).to_contain_text("按 P")
    page.locator('[data-tool="pos"]').click()
    expect(action(page)).to_contain_text("框住單號")
    expect(page.locator("#overlay .guide-ghost")).to_be_visible()  # 虛線靶框
    draw_box(page, [0.64, 0.05, 0.7, 0.076])  # 框太小
    expect(action(page)).to_contain_text("用 1 份範例測試")
    page.locator("#testBtn").click()
    expect(tip(page)).to_contain_text("預期「PO-2026-0412」", timeout=30_000)
    expect(tip(page)).to_have_class(re.compile(r"\bwrong\b"))
    expect(tip(page)).to_contain_text("框得太小")
    expect(page.locator("#missionStrip .mission-controls button", has_text="下一步")).to_be_disabled()  # 最後一步不能跳過
    # 修到對為止：刪掉再框一次
    page.locator("#right .items li button").last.click()
    page.keyboard.press("Delete")
    page.locator('[data-tool="pos"]').click()
    draw_box(page, PO_BOX)
    page.locator("#testBtn").click()
    finish(page, "PO-2026-0412")
    # 練習範本不寫入範本資料夾，說明選單標示練習過
    assert not [p for p in server.TEMPLATES.glob("*.json") if "lab" in p.name]
    page.locator("#labBackBtn").click()
    expect(page.locator("#guideBar")).to_be_hidden()
    page.locator("#helpBtn").click()
    expect(page.locator('#helpPopover [data-spotlight="feat-pos-field"]')).to_contain_text("練習過 ✓")
    stored = json.loads(page.evaluate("localStorage.getItem('pdfmapper.onboarding.v1')"))
    assert stored["labsDone"] == ["pos-field"] and "labStep" not in stored


def test_cell_extract_lab_wrong_then_right(page):
    start_lab(page, "feat-cell-extract")
    expect(action(page)).to_contain_text("Spec 欄")
    open_spec_column(page, "Spec")
    expect(action(page)).to_contain_text("開頭文字")
    page.locator('#right select[aria-label="這一欄怎麼取值"]').select_option("start")
    expect(action(page)).to_contain_text("ECCN:")
    page.locator('#right input[aria-label="開頭文字"]').fill("Origin:")  # 取錯值
    page.locator('#right input[aria-label="開頭文字"]').press("Enter")  # 打字中不算完成，按 Enter 才算
    expect(action(page)).to_contain_text("用 1 份範例測試")
    page.locator("#testBtn").click()
    expect(tip(page)).to_contain_text("第 1 列抓到「TW」，預期「5A992」", timeout=30_000)
    expect(tip(page)).to_have_class(re.compile(r"\bwrong\b"))
    # 改回 ECCN:，值到哪裡結束改成「下一個開頭文字」會一路取到格尾，也要提示
    reopen_column(page, "Spec")
    page.locator('#right input[aria-label="開頭文字"]').fill("ECCN:")
    page.locator('#right select[aria-label="值到哪裡結束"]').select_option("next")
    page.locator("#testBtn").click()
    expect(tip(page)).to_contain_text("還帶著 Origin", timeout=30_000)
    reopen_column(page, "Spec")
    page.locator('#right select[aria-label="值到哪裡結束"]').select_option("line")
    page.locator("#testBtn").click()
    finish(page, "5A992、4A003、EAR99、3A001、5D002")


def test_regex_lab_trial_then_apply(page):
    start_lab(page, "feat-regex")
    open_spec_column(page, "Ref")
    page.locator('#right select[aria-label="這一欄怎麼取值"]').select_option("regex")
    expect(action(page)).to_contain_text("試出 INV-2026-0301")
    page.locator('#right .help-hint[data-spotlight="feat-regex"]').click()
    card = page.locator("#coachCard")
    expect(card).to_be_visible()
    expect(card.locator("#spotLabBtn")).to_have_count(0)  # 練習中的說明卡不再提供實地練習
    card.locator("#trialText").fill("Ref INV-2026-0301 rev2")
    card.locator("#trialPattern").fill(r"INV-\d{4}-\d{4} rev\d")
    expect(card.locator("#trialResult")).to_contain_text("抓到「INV-2026-0301 rev2」")
    expect(action(page)).to_contain_text("試出 INV-2026-0301")  # 還沒試到預期的值
    card.locator("#trialPattern").fill(r"INV-\d{4}-\d{4}")
    expect(card.locator("#trialResult")).to_contain_text("抓到「INV-2026-0301」")
    card.locator("#trialApply").click()
    expect(action(page)).to_contain_text("用 1 份範例測試")
    # 先故意改成多取 rev 的規則
    page.locator("#right .column-row.open, #right .column-row").first.wait_for()
    page.locator('#right input[aria-label="正規表達式"]').fill(r"INV-\d{4}-\d{4} rev\d")
    page.locator("#testBtn").click()
    expect(tip(page)).to_contain_text("規則多取到 rev", timeout=30_000)
    reopen_column(page, "Ref")
    page.locator('#right input[aria-label="正規表達式"]').fill(r"INV-\d{4}-\d{4}")
    page.locator("#testBtn").click()
    finish(page, "INV-2026-0301、INV-2026-0302")


def test_lab_restores_work_and_retry(page, samples):
    folder, _ = samples
    page.set_input_files("#filePicker", [str(folder / "sample_6_invoice.pdf")])
    page.wait_for_selector(".docs li")
    page.locator("#templateName").fill("我的未儲存範本")
    page.locator("#templateName").blur()
    page.locator("#helpBtn").click()
    page.locator('#helpPopover [data-spotlight="feat-regex"]').click()
    page.locator("#spotLabBtn").click()
    expect(page.locator("#labConfirmBtn")).to_be_visible()  # 有文件與未儲存範本，先詢問
    page.locator("#labCancelBtn").click()
    expect(page.locator("#guideBar")).to_be_hidden()
    expect(page.locator("#templateName")).to_have_value("我的未儲存範本")
    page.locator("#helpBtn").click()
    page.locator('#helpPopover [data-spotlight="feat-regex"]').click()
    page.locator("#spotLabBtn").click()
    page.locator("#labConfirmBtn").click()
    expect(page.locator("#guideBar .guide-name")).to_have_text("實地練習", timeout=30_000)
    expect(page.locator("#templateName")).to_have_value("實地練習：用規則抓格式")
    expect(page.locator("#saveButton")).to_be_disabled()  # 練習範本不能存檔
    draft = page.evaluate("localStorage.getItem('pdfmapper.draft')")
    assert "我的未儲存範本" in (draft or "")  # 練習中不覆蓋原本的草稿
    # 練習中再練一次不用再問
    page.locator("#helpBtn").click()
    page.locator('#helpPopover [data-spotlight="feat-regex"]').click()
    page.locator("#spotLabBtn").click()
    expect(page.locator("#labConfirmBtn")).to_have_count(0)
    expect(page.locator("#guideBar .guide-name")).to_have_text("實地練習")
    page.locator("#labExitBtn").click()
    expect(page.locator("#guideBar")).to_be_hidden()
    expect(page.locator("#templateName")).to_have_value("我的未儲存範本")
    expect(page.locator(".docs li")).to_have_count(1)
    expect(page.locator(".docs li")).to_contain_text("sample_6_invoice")
    draft = page.evaluate("localStorage.getItem('pdfmapper.draft')")
    assert "我的未儲存範本" in (draft or "")


def test_lab_without_documents_and_missing_card_buttons(page):
    page.locator("#helpBtn").click()
    page.locator('#helpPopover [data-spotlight="feat-cell-extract"]').click()
    card = page.locator("#coachCard")
    expect(card.locator("#spotLabBtn")).to_have_class(re.compile(r"\bprimary\b"))
    expect(card.locator("#spotDemoBtn")).not_to_have_class(re.compile(r"\bprimary\b"))
    card.locator("#spotLabBtn").click()
    expect(page.locator("#guideBar .guide-name")).to_have_text("實地練習", timeout=30_000)
    expect(page.locator("#labConfirmBtn")).to_have_count(0)


def test_format_check_lab_wrong_then_right(page):
    start_lab(page, "feat-format-check")
    expect(page.locator("#templateName")).to_have_value("實地練習：格式檢查")
    expect(action(page)).to_contain_text("Tax ID")
    page.locator("#right .items li button").first.click()
    expect(action(page)).to_contain_text("進階設定")
    page.locator("#fieldAdvanced > summary").click()
    expect(action(page)).to_contain_text("格式檢查")
    page.locator("#fieldPatternInput").fill(r"^\d{7}$")  # 7 碼的規則，8 碼的值不通過，步驟不算完成
    expect(action(page)).to_contain_text("格式檢查")
    expect(tip(page)).to_contain_text("規則要讓 12345678 通過")
    page.locator("#fieldPatternInput").fill(r"^\d{8}$")
    expect(action(page)).to_contain_text("用 1 份範例測試")
    # 完成後又改成 7 碼的規則，試抓會說少一碼的值沒有被標記
    page.locator("#fieldPatternInput").fill(r"^\d{7}$")
    page.locator("#testBtn").click()
    expect(tip(page)).to_contain_text("沒有被標記", timeout=30_000)
    expect(tip(page)).to_have_class(re.compile(r"\bwrong\b"))
    expect(tip(page)).to_contain_text("規則寫成 7 碼")
    page.locator("#right .items li button").first.click()
    page.locator("#fieldPatternInput").fill(r"^\d{8}$")
    page.locator("#testBtn").click()
    finish(page, "1234567 少一碼，已被標記為格式不符")
    assert not [p for p in server.TEMPLATES.glob("*.json") if "lab" in p.name]


def test_cross_page_lab_second_page_range(page):
    start_lab(page, "feat-cross-page")
    expect(action(page)).to_contain_text("「位置」分頁")
    page.locator('#right .subtabs [data-tab="place"]').click()
    expect(action(page)).to_contain_text("翻到第 2 頁")
    page.locator('#toolbar button[aria-label="下一頁"]').click()
    expect(action(page)).to_contain_text("在目前這一頁加範圍")
    page.locator("#addRegionBtn").click()
    expect(page.locator("#overlay .guide-ghost")).to_be_visible()  # 第 2 頁的虛線靶框
    draw_box(page, [0.08, 0.22, 0.92, 0.32])  # 只框到前兩列
    expect(action(page)).to_contain_text("用 1 份範例測試")
    page.locator("#testBtn").click()
    expect(tip(page)).to_contain_text("抓到 6 列，預期 7 列", timeout=30_000)
    expect(tip(page)).to_have_class(re.compile(r"\bwrong\b"))
    page.locator("#right .items li button").last.click()
    page.locator("#right .region-card button", has_text="移除").click()
    if page.locator('#toolbar button[aria-label="下一頁"]').is_enabled():  # 測試後可能回到第 1 頁，範圍要加在第 2 頁
        page.locator('#toolbar button[aria-label="下一頁"]').click()
    page.locator("#addRegionBtn").click()
    draw_box(page, [0.08, 0.22, 0.92, 0.5])
    page.locator("#testBtn").click()
    finish(page, "Bolt M6、Nut M6、Washer 6、Screw M4、Clip A2、Pin 8、Spacer 3")


def test_header_lab_two_documents(page):
    start_lab(page, "feat-header")
    expect(page.locator(".docs li")).to_have_count(2)
    page.locator('#right .subtabs [data-tab="place"]').click()
    expect(action(page)).to_contain_text("框選表頭")
    page.locator("#right .header-pick").click()
    expect(page.locator("#overlay .guide-ghost")).to_be_visible()
    draw_box(page, [0.4, 0.165, 0.5, 0.195])  # 框到沒有字的地方，表頭對不上
    expect(page.locator("#right .region-card .marker-row")).to_contain_text("表頭：")
    expect(action(page)).to_contain_text("用 2 份範例測試")
    page.locator("#testBtn").click()
    expect(tip(page)).to_have_class(re.compile(r"\bwrong\b"), timeout=30_000)
    expect(tip(page)).to_contain_text("第 ")
    page.locator("#right .items li button").last.click()
    page.locator('#right .subtabs [data-tab="place"]').click()
    page.locator("#right .region-card .marker-row button", has_text="移除").click()
    page.locator("#right .header-pick").click()
    draw_box(page, [0.085, 0.165, 0.17, 0.195])
    expect(page.locator("#right .region-card .marker-row")).to_contain_text("表頭：")  # 框好後要讀字，等它設定完
    page.locator("#testBtn").click()
    finish(page, "Washer 6")
    expect(page.locator("#labResult")).to_contain_text("Pin 8")


def test_endmark_lab_total_row_not_counted(page):
    start_lab(page, "feat-endmark")
    page.locator('#right .subtabs [data-tab="place"]').click()
    expect(action(page)).to_contain_text("框選表尾")
    page.locator("#right .endmark-pick").click()
    expect(page.locator("#overlay .guide-ghost")).to_be_visible()
    draw_box(page, [0.2, 0.34, 0.3, 0.37])  # 框到第 3 列的字，表格會在這裡就結束
    expect(page.locator("#right .marker-row", has_text="表尾標記：")).to_be_visible()
    page.locator("#testBtn").click()
    expect(tip(page)).to_contain_text("預期 5 列", timeout=30_000)
    expect(tip(page)).to_contain_text("框住表格結束後緊接著的「Total」")
    expect(tip(page)).to_have_class(re.compile(r"\bwrong\b"))
    page.locator("#right .items li button").last.click()
    page.locator('#right .subtabs [data-tab="place"]').click()
    page.locator("#right .marker-row button", has_text="移除").click()
    page.locator("#right .endmark-pick").click()
    draw_box(page, [0.2, 0.5, 0.29, 0.54])
    expect(page.locator("#right .marker-row", has_text="表尾標記：")).to_be_visible()
    page.locator("#testBtn").click()
    finish(page, "310、620、930、1,240、1,550")


def test_sum_fields_lab_checkbox_wrong_then_right(page):
    start_lab(page, "feat-checks")
    expect(page.locator("#templateName")).to_have_value("實地練習：數字檢查")
    expect(action(page)).to_contain_text("新增檢查")
    page.locator("#checksDetails > summary").click()
    expect(action(page)).to_contain_text("勾 Subtotal 和 Tax")
    expect(page.locator("#checkFields input[type=checkbox]")).to_have_count(3)  # 一組 checkbox，不是複選清單
    expect(page.locator("#checkFields")).to_have_class(re.compile(r"\bguide-pointed\b"))
    page.get_by_role("checkbox", name="相加 Subtotal").check()  # 只勾一個就加入：做錯
    page.locator("#checkTargetSelect").select_option(label="Total")
    page.locator("#checkAddBtn").click()
    expect(action(page)).to_contain_text("用 1 份範例測試")
    page.locator("#testBtn").click()
    expect(tip(page)).to_contain_text("現在的檢查是 Subtotal = Total", timeout=30_000)
    expect(tip(page)).to_contain_text("要相加的是 Subtotal 和 Tax")
    expect(tip(page)).to_have_class(re.compile(r"\bwrong\b"))
    page.locator("#right .checks li button", has_text="移除").click()  # 移除後重做
    page.locator("#checksDetails > summary").click() if not page.locator("#checkFields").is_visible() else None
    page.get_by_role("checkbox", name="相加 Subtotal").check()
    page.get_by_role("checkbox", name="相加 Tax").check()
    page.locator("#checkTargetSelect").select_option(label="Total")
    expect(page.locator("#checkPreview")).to_contain_text("「Subtotal」 + 「Tax」 = Total")
    page.locator("#checkAddBtn").click()
    page.locator("#testBtn").click()
    finish(page, "Total 寫 4,800，已被標記為加總不符")
    assert not [p for p in server.TEMPLATES.glob("*.json") if "lab" in p.name]


def test_output_lab_preview_wrong_then_right(page):
    start_lab(page, "feat-output")
    expect(page.locator("#templateName")).to_have_value("實地練習：輸出設定")
    expect(action(page)).to_contain_text("設定輸出欄位")
    page.locator("#outputBtn").click()
    expect(page.locator("#outputPreview")).to_be_visible()
    expect(page.locator("#outputPreview")).to_contain_text("按「測試」後會顯示範例的值")
    expect(action(page)).to_contain_text("取消勾選 Internal Note")
    page.get_by_role("checkbox", name="輸出 Internal Note").uncheck()
    expect(page.locator("#outputPreview th")).to_have_text(["Invoice No", "Customer", "Amount"])  # 預覽即時更新
    expect(action(page)).to_contain_text("Doc No")
    page.get_by_label("Invoice No 的輸出欄名").fill("Doc Number")  # 欄名寫錯
    page.get_by_label("Invoice No 的輸出欄名").press("Enter")
    expect(action(page)).to_contain_text("移到 Customer 前面")
    page.get_by_role("button", name="Amount 上移").click()
    expect(page.locator("#outputPreview th")).to_have_text(["Doc Number", "Amount", "Customer"])
    expect(action(page)).to_contain_text("用 1 份範例測試")
    page.locator("#testBtn").click()
    expect(tip(page)).to_contain_text("預期 Doc No、Amount、Customer", timeout=30_000)
    expect(tip(page)).to_contain_text("欄名不對")
    expect(tip(page)).to_have_class(re.compile(r"\bwrong\b"))
    expect(page.locator("#outputPreview td")).to_have_text(["INV-2026-0501", "1,250", "Acme Trading Ltd"])
    page.get_by_label("Invoice No 的輸出欄名").fill("Doc No")
    page.locator("#testBtn").click()
    finish(page, "Doc No、Amount、Customer，Internal Note 沒有輸出")
    expect(page.locator("#outputPreview th")).to_have_text(["Doc No", "Amount", "Customer"])


def test_multi_template_lab_in_run_view(page):
    start_lab(page, "run-multi-template")
    expect(page.locator("#tabRun")).to_have_attribute("aria-current", "page")
    expect(page.locator("#guideBar .guide-name")).to_have_text("實地練習")
    picks = page.locator("#left .template-picks label")
    expect(picks).to_have_text(["練習範本：發票", "練習範本：裝箱單"])  # 只有練習範本，不是 workspace 裡的
    expect(page.locator("#left .docs li")).to_have_count(2)
    expect(action(page)).to_contain_text("都勾起來")
    picks.nth(0).locator("input").check()
    picks.nth(1).locator("input").check()
    expect(action(page)).to_contain_text("開始解析")
    picks.nth(1).locator("input").uncheck()  # 少勾一個：裝箱單會被硬套發票範本
    page.locator("#runStartBtn").click()
    expect(tip(page)).to_contain_text("第 2 份（練習_裝箱單.pdf）用了「練習範本：發票」", timeout=60_000)
    expect(tip(page)).to_have_class(re.compile(r"\bwrong\b"))
    expect(page.locator("#left")).to_contain_text("練習解析不佔解析紀錄")
    picks.nth(1).locator("input").check()
    expect(page.locator("#runStartBtn")).to_be_enabled(timeout=60_000)
    page.locator("#runStartBtn").click()
    finish(page, "發票用了「發票」範本，裝箱單用了「裝箱單」範本")
    assert not [p for p in server.TEMPLATES.glob("*.json") if "lab" in p.name]
    page.locator("#labBackBtn").click()
    expect(page.locator("#guideBar")).to_be_hidden()
    expect(page.locator("#tabTrain")).to_have_attribute("aria-current", "page")  # 回到練習前的分頁
    page.locator("#helpBtn").click()
    expect(page.locator('#helpPopover [data-spotlight="run-multi-template"]')).to_contain_text("練習過 ✓")


def test_multi_template_lab_restores_the_parse_state(page, samples):
    from helpers import run_parse

    run_parse(page, samples, ["sample_1_standard.pdf"])
    before = page.locator("#left .docs li").inner_text()
    checked = page.locator("#left .template-picks input:checked").count()
    assert checked == 1
    page.locator("#helpBtn").click()
    page.locator('#helpPopover [data-spotlight="run-multi-template"]').click()
    page.locator("#spotLabBtn").click()
    expect(page.locator("#labConfirmBtn")).to_be_visible()  # 有已載入的文件，先詢問
    page.locator("#labConfirmBtn").click()
    expect(page.locator("#guideBar .guide-name")).to_have_text("實地練習", timeout=30_000)
    expect(page.locator("#left .docs li")).to_have_count(2)
    expect(page.locator("#left .template-picks input:checked")).to_have_count(0)
    page.locator("#labExitBtn").click()
    expect(page.locator("#guideBar")).to_be_hidden()
    expect(page.locator("#tabRun")).to_have_attribute("aria-current", "page")
    expect(page.locator("#left .docs li")).to_have_count(1)
    assert page.locator("#left .docs li").inner_text() == before  # 原本的解析結果還在
    expect(page.locator("#left .template-picks input:checked")).to_have_count(1)
    expect(page.locator("#drawer td[data-ref]").first).to_be_visible()
    expect(page.locator("#runStartBtn")).to_be_enabled()


def test_verify_result_shows_without_extra_click(page):
    """按「用 1 份範例測試」後，不用再點任何東西，✓ 或差在哪裡的提示就要自己出現（含 API 回得慢的情況）。"""
    import time

    def slow(route):
        time.sleep(1.5)
        route.continue_()
    page.route("**/api/test", slow)
    start_lab(page, "feat-pos-field")
    page.locator('[data-tool="pos"]').click()
    draw_box(page, [0.64, 0.05, 0.7, 0.076])  # 框太小
    page.locator("#testBtn").click()
    expect(tip(page)).to_contain_text("框得太小", timeout=30_000)  # 做錯：提示自己出現
    page.locator("#right .items li button").last.click()
    page.keyboard.press("Delete")
    page.locator('[data-tool="pos"]').click()
    draw_box(page, PO_BOX)
    page.locator("#testBtn").click()
    expect(page.locator("#labResult")).to_contain_text("PO-2026-0412", timeout=30_000)  # 做對：完成畫面自己出現


def test_format_check_lab_waits_for_a_complete_rule(page):
    """一個字一個字輸入規則：中途提示還在、步驟沒推進，規則完整才推進。"""
    start_lab(page, "feat-format-check")
    page.locator("#right .items li button").first.click()
    page.locator("#fieldAdvanced > summary").click()
    expect(action(page)).to_contain_text("格式檢查")
    box = page.locator("#fieldPatternInput")
    box.click()
    for typed in (r"^", r"\d", r"{8}"):  # 打到 ^\d{8} 還缺 $，8 碼通過，但 9 碼也會通過
        box.press_sequentially(typed)
        expect(action(page)).to_contain_text("格式檢查")
        expect(tip(page)).not_to_have_text("")
    expect(tip(page)).to_contain_text("^ 和 $")  # 說明還差什麼
    expect(action(page)).not_to_contain_text("用 1 份範例測試")
    box.press_sequentially("$")
    expect(action(page)).to_contain_text("用 1 份範例測試")


def test_regex_lab_apply_step_waits_for_a_matching_rule(page):
    start_lab(page, "feat-regex")
    open_spec_column(page, "Ref")
    page.locator('#right select[aria-label="這一欄怎麼取值"]').select_option("regex")
    page.locator('#missionStrip .mission-controls button', has_text="下一步").click()  # 跳過試算，直接練習填規則
    expect(action(page)).to_contain_text("套用到 Ref 欄")
    box = page.locator('#right input[aria-label="正規表達式"]')
    box.click()
    for typed in ("INV", r"-\d{4}", "-", r"\d{3"):  # 中途有些寫法編譯不過、有些抓不到完整單號
        box.press_sequentially(typed)
        expect(action(page)).to_contain_text("套用到 Ref 欄")
        expect(tip(page)).not_to_have_text("")
    box.press_sequentially("}")
    expect(action(page)).to_contain_text("套用到 Ref 欄")  # INV-\d{4}-\d{3} 只抓到 INV-2026-030
    expect(tip(page)).to_contain_text("INV-2026-030")
    box.press_sequentially(r"\d")
    expect(action(page)).to_contain_text("用 1 份範例測試")


def test_typing_text_step_waits_for_enter(page):
    """填開頭文字：打字中不算完成，按 Enter 才算。"""
    start_lab(page, "feat-cell-extract")
    open_spec_column(page, "Spec")
    page.locator('#right select[aria-label="這一欄怎麼取值"]').select_option("start")
    box = page.locator('#right input[aria-label="開頭文字"]')
    box.click()
    box.press_sequentially("E")
    expect(action(page)).to_contain_text("ECCN:")
    expect(tip(page)).to_contain_text("按 Enter")
    box.press_sequentially("CCN:")
    expect(action(page)).to_contain_text("ECCN:")
    box.press("Enter")
    expect(action(page)).to_contain_text("用 1 份範例測試")
