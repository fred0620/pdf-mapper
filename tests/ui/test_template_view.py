"""建立範本畫面：開舊範本自動對位、未儲存的草稿。"""
from playwright.sync_api import expect


def test_open_template_with_shifted_pdf_aligns(page, samples):
    folder, _ = samples
    page.set_input_files("#filePicker", str(folder / "sample_2_shifted.pdf"))
    page.wait_for_selector(".docs li")
    page.select_option("select[aria-label=開啟已存的範本]", "customs")
    expect(page.locator("#toast")).to_contain_text("已依定位點調整", timeout=60_000)
    assert page.locator("#overlay .box").count() > 5


def test_unsaved_draft_is_offered_not_restored(page):
    name = page.locator("input[aria-label=範本名稱]")
    name.fill("沒存的範本")
    page.wait_for_timeout(200)
    page.reload()
    page.wait_for_selector("#version:not(:empty)")
    assert name.input_value() == ""
    assert "沒存的範本" in page.locator(".recovery").inner_text()
    page.locator(".recovery").get_by_role("button", name="接著做").click()
    assert name.input_value() == "沒存的範本"


def test_check_form_explains_previews_and_blocks_incomplete(page, samples):
    """數字檢查表單（不用導覽也看得到）：上方說明、底部白話預覽、缺欄時不能加入並說明原因。"""
    folder, _ = samples
    page.set_input_files("#filePicker", str(folder / "sample_6_invoice.pdf"))
    page.wait_for_selector(".docs li")
    page.select_option("select[aria-label=開啟已存的範本]", "invoice")
    expect(page.locator("#right .items li")).to_have_count(4)
    details = page.locator("#checksDetails")
    details.locator("summary").click()
    page.locator("#checkTypeSelect").select_option("sum_column")  # 點開後馬上選，表單不能自己收起來
    expect(details).to_have_attribute("open", "")
    expect(details.locator(".check-intro")).to_contain_text("對不上就標記給人看")
    preview, add = page.locator("#checkPreview"), page.locator("#checkAddBtn")
    expect(preview).to_have_text("還缺：表格欄、要等於")
    expect(add).to_be_disabled()
    expect(add).to_have_attribute("title", "還缺：表格欄、要等於，選好才能加入")
    page.locator("#checkColSelect").select_option(label="品項明細：金額")
    expect(preview).to_have_text("還缺：要等於")
    page.locator("#checkTargetSelect").select_option(label="總金額")
    expect(preview).to_have_text("品項明細「金額」加總 = 總金額（差 1 以內算通過）")
    expect(add).to_be_enabled()
    before = page.locator("#right .checks li").count()
    add.click()
    expect(page.locator("#right .checks li")).to_have_count(before + 1)
    expect(page.locator("#right .checks li").last).to_contain_text("品項明細「金額」加總 = 總金額")
