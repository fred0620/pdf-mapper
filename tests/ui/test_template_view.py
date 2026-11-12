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
