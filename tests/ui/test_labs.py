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
