"""自動產生使用手冊的截圖：開示範與練習資料，依 `<!-- shot: 代號 -->` 拍相關面板，存到 docs/images/shot-<代號>.png。

    uv run --project app --group ui python scripts/manual_shots.py            # 全部重拍
    uv run --project app --group ui python scripts/manual_shots.py anchors    # 只拍指定代號

用電腦上的 Chrome（和 tests/ui 一樣用 Playwright 啟動本機服務，範本、上傳與輸出放暫存資料夾，不碰 workspace）。
視窗固定 1440 x 900（device_scale_factor 1），和一般筆電寬度相同，導覽列與工具列都排得下。
拍之前先把新手導覽設成「已關閉」，並確認導覽列、指令條、浮標都看不到（只有說明選單那張要拍說明選單）。
圖檔縮到 1000px 寬，轉成少色的調色盤 PNG 並壓縮，因為截圖會內嵌進手冊 HTML，總體積要小。
產生後執行 scripts/build_manual.py 才會進手冊。
"""
from __future__ import annotations

import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "app")]

from PIL import Image  # noqa: E402
from playwright.sync_api import expect  # noqa: E402

IMAGES = ROOT / "docs" / "images"
WIDTH = 1000
COLORS = 48
VIEWPORT = {"width": 1440, "height": 900}
DISMISSED = '{"dismissed":true,"trainDone":true,"runDone":true,"whatsnewSeen":"99.0.0","whatsnewCardShown":"99.0.0"}'  # 和 spotlights.js 的 pdfmapper.onboarding.v1 同格式
GUIDE_PARTS = ("#guideBar", "#missionStrip", "#missionPointer", "#whatsNewCard", "#toast")


def png_name(code: str) -> Path:
    return IMAGES / f"shot-{code}.png"


def finish_image(source: Path, target: Path) -> None:
    """縮到 WIDTH 寬，轉成少色調色盤 PNG 並壓縮。"""
    image = Image.open(source).convert("RGB")
    if image.width > WIDTH:
        image = image.resize((WIDTH, round(image.height * WIDTH / image.width)), Image.LANCZOS)
    image.quantize(colors=COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(target, optimize=True)


class Shooter:
    def __init__(self, browser, url: str) -> None:
        self.browser, self.url = browser, url
        self.scratch = Path(tempfile.mkdtemp(prefix="manual-shots-"))

    def open(self, accept_downloads: bool = False):
        context = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=1, accept_downloads=accept_downloads)
        context.add_init_script(f"localStorage.setItem('pdfmapper.onboarding.v1', '{DISMISSED}')")
        page = context.new_page()
        page.goto(self.url)
        page.wait_for_selector("#version:not(:empty)")
        return page

    def save(self, page, code: str, clip: dict) -> None:
        if code != "help-menu":
            for selector in GUIDE_PARTS:
                expect(page.locator(selector)).to_be_hidden()  # 導覽的指令條與浮標不該出現在截圖裡
        raw = self.scratch / f"{code}.png"
        page.screenshot(path=str(raw), clip=clip)
        finish_image(raw, png_name(code))

    def save_element(self, page, code: str, selector: str, pad: int = 0) -> None:
        box = page.locator(selector).bounding_box()
        self.save(page, code, {"x": max(box["x"] - pad, 0), "y": max(box["y"] - pad, 0),
                               "width": box["width"] + 2 * pad, "height": box["height"] + 2 * pad})

    def save_workarea(self, page, code: str) -> None:
        """中間的 PDF 加右欄設定，不含左側檔案欄。"""
        center, right = page.locator(".center").bounding_box(), page.locator("#right").bounding_box()
        top = min(center["y"], right["y"])
        self.save(page, code, {"x": center["x"], "y": top, "width": right["x"] + right["width"] - center["x"],
                               "height": VIEWPORT["height"] - top})


# 以下每個函式對應手冊裡的一個 shot 代號

def start_lab(page, spotlight: str) -> None:
    page.locator("#helpBtn").click()
    page.locator(f'#helpPopover [data-spotlight="{spotlight}"]').click()
    page.locator("#spotLabBtn").click()
    page.wait_for_selector("#guideBar .guide-name", timeout=30_000)


def close_guide(page) -> None:
    """練習的導覽列、指令條與虛線靶框不屬於要截的畫面，用樣式藏起來（結束練習會把範本換回去，所以不關）。"""
    page.add_style_tag(content="#guideBar, #missionStrip, #missionPointer, .guide-ghost, .guide-ghost-line, "
                               ".guide-target { display: none !important; outline: none !important; box-shadow: none !important; }")


def hide_actions(page) -> None:
    """右欄底部固定的「測試／儲存」按鈕區會蓋到面板內容，拍面板時先藏起來。"""
    page.add_style_tag(content="#actions { display: none !important; }")


def select_table(page) -> None:
    """練習開啟時多半已經選著表格；沒選才從清單點。"""
    page.wait_for_selector("#right .subtabs, #right .items li button")
    if not page.locator("#right .subtabs").count():
        page.locator("#right .items li button").last.click()


def draw(page, box) -> None:
    from_x, from_y = _point(page, box[0], box[1])
    to_x, to_y = _point(page, box[2], box[3])
    page.mouse.move(from_x, from_y)
    page.mouse.down()
    page.mouse.move((from_x + to_x) / 2, (from_y + to_y) / 2, steps=4)
    page.mouse.move(to_x, to_y, steps=4)
    page.mouse.up()


def _point(page, x: float, y: float) -> tuple[float, float]:
    rect = page.locator("#overlay").bounding_box()
    return rect["x"] + x * rect["width"], rect["y"] + y * rect["height"]


def shot_flow_overview(s: Shooter) -> None:
    page = s.open()
    page.wait_for_selector("#demoStartBtn")
    s.save(page, "flow-overview", {"x": 0, "y": 0, **VIEWPORT})


def shot_help_menu(s: Shooter) -> None:
    page = s.open()
    page.locator("#helpBtn").click()
    page.wait_for_selector("#helpPopover", state="visible")
    popover = page.locator("#helpPopover").bounding_box()
    s.save(page, "help-menu", {"x": 0, "y": 0, "width": VIEWPORT["width"], "height": popover["y"] + popover["height"] + 10})


def shot_value_mode(s: Shooter) -> None:
    page = s.open()
    start_lab(page, "feat-cell-extract")
    close_guide(page)
    select_table(page)
    page.locator('button.column-more[aria-label="Spec 的設定"]').click()
    page.locator('#right select[aria-label="這一欄怎麼取值"]').select_option("start")
    page.locator('#right input[aria-label="開頭文字"]').fill("ECCN:")
    page.locator('#right select[aria-label="值到哪裡結束"]').select_option("line")
    page.locator("#right .column-preview-btn").click()
    page.wait_for_selector("#right .preview-list li")
    values = page.locator("#right .preview-list li strong").all_inner_texts()
    assert values[:2] == ["5A992", "4A003"], f"試抓結果不是預期的 ECCN：{values}"
    hide_actions(page)
    page.locator("#right .preview-list").evaluate("el => el.scrollIntoView({block: 'end'})")
    s.save_element(page, "value-mode", "#right")


def shot_table_columns(s: Shooter) -> None:
    page = s.open()
    page.locator("#showcaseBtn").click()
    page.wait_for_selector("#coachCard:not([hidden])", timeout=30_000)
    page.keyboard.press("Escape")
    page.locator("#right .items li button", has_text="品項明細").click()
    page.wait_for_selector('#right select#keyColumn')
    s.save_workarea(page, "table-columns")


def shot_cross_page_region(s: Shooter) -> None:
    page = s.open()
    start_lab(page, "feat-cross-page")
    close_guide(page)
    select_table(page)
    page.locator('#right .subtabs [data-tab="place"]').click()
    page.locator('#toolbar button[aria-label="下一頁"]').click()
    page.locator("#addRegionBtn").click()
    draw(page, [0.08, 0.22, 0.92, 0.5])
    page.wait_for_selector("#right .region-card >> nth=1")
    s.save_workarea(page, "cross-page-region")


def shot_header_endmark(s: Shooter) -> None:
    page = s.open()
    start_lab(page, "feat-endmark")
    close_guide(page)
    select_table(page)
    page.locator('#right .subtabs [data-tab="place"]').click()
    page.locator("#right .header-pick").click()
    draw(page, [0.085, 0.165, 0.17, 0.195])
    page.wait_for_selector("#right .region-card .marker-row:has-text('表頭：')")
    page.locator("#right .endmark-pick").click()
    draw(page, [0.2, 0.5, 0.29, 0.54])
    page.wait_for_selector("#right .marker-row:has-text('表尾標記：')")
    s.save_workarea(page, "header-endmark")


def shot_anchors(s: Shooter) -> None:
    page = s.open()
    page.locator("#showcaseBtn").click()
    page.wait_for_selector("#coachCard:not([hidden])", timeout=30_000)
    page.keyboard.press("Escape")
    page.evaluate("selectItem('anchor', T().anchors[0].id)")
    s.save_workarea(page, "anchors")


def shot_checks(s: Shooter) -> None:
    """用「數字檢查」練習：勾 Subtotal 和 Tax、要等於 Total，拍到表單下方的白話說明（和手冊該節一致）。"""
    page = s.open()
    start_lab(page, "feat-checks")
    close_guide(page)
    page.locator("#checksDetails > summary").click()
    page.get_by_role("checkbox", name="相加 Subtotal").check()
    page.get_by_role("checkbox", name="相加 Tax").check()
    page.locator("#checkTargetSelect").select_option(label="Total")
    expect(page.locator("#checkPreview")).to_contain_text("「Subtotal」 + 「Tax」 = Total")
    hide_actions(page)
    page.locator("#checkAddBtn").evaluate("el => el.scrollIntoView({block: 'end'})")
    s.save_element(page, "checks", "#right")


def run_demo(s: Shooter, accept_downloads: bool = False):
    page = s.open(accept_downloads)
    page.click("#tabRun")
    page.click("#demoStartBtn")
    expect(page.locator(".docs .meta.warn, .docs .meta.good")).to_have_count(2, timeout=120_000)
    page.locator("#drawer td[data-ref]").first.wait_for()
    if page.locator("#guideCloseBtn").is_visible():  # 示範解析會開導覽，關掉它
        page.locator("#guideCloseBtn").click()
    expect(page.locator("#toast")).to_be_hidden(timeout=10_000)  # 完成的提示條消失後再拍，不然會蓋到表格
    return page


def shot_result_colors(s: Shooter) -> None:
    page = run_demo(s)
    s.save_workarea(page, "result-colors")


def shot_excel_review(s: Shooter) -> None:
    """Excel 沒辦法截圖，所以把匯出檔的「待檢查」工作表讀回來，畫成像 Excel 的表格再拍。"""
    from html import escape

    from openpyxl import load_workbook

    page = run_demo(s, accept_downloads=True)
    with page.expect_download() as download:
        page.locator("#exportExcelBtn").click()
    target = s.scratch / "review.xlsx"
    download.value.save_as(target)
    sheet = load_workbook(target)["待檢查"]
    columns = list(range(1, 10))  # 原圖欄是圖片，不畫
    letters = "ABCDEFGHI"
    head = "".join(f'<th class="col">{letters[i - 1]}</th>' for i in columns)
    rows = []
    for number, row in enumerate(sheet.iter_rows(min_row=1, max_row=min(sheet.max_row, 7)), start=1):
        cells = []
        for i in columns:
            cell = row[i - 1]
            fill = cell.fill.fgColor.rgb if cell.fill and cell.fill.fill_type == "solid" and isinstance(cell.fill.fgColor.rgb, str) else None
            style = f' style="background:#{fill[-6:]}"' if fill else ""
            bold = " b" if number == 1 else ""
            cells.append(f'<td class="c{bold}"{style}>{escape(str(cell.value if cell.value is not None else ""))}</td>')
        rows.append(f'<tr><th class="row">{number}</th>{"".join(cells)}</tr>')
    page.set_content(
        "<style>body{margin:0;font:13px/1.3 'Microsoft JhengHei','Noto Sans TC',sans-serif;background:#fff}"
        "table{border-collapse:collapse;width:100%;table-layout:auto}"
        "th{background:#f0f0f0;color:#444;font-weight:400;border:1px solid #d0d0d0;padding:2px 6px}"
        "th.row{width:22px;text-align:center}"
        "td.c{border:1px solid #d9d9d9;padding:3px 6px;white-space:nowrap;max-width:240px;overflow:hidden;text-overflow:ellipsis}"
        "td.b{font-weight:700;background:#e8e8e8}</style>"
        f'<table id="sheet"><tr><th class="row"></th>{head}</tr>{"".join(rows)}</table>')
    page.set_viewport_size({"width": 1100, "height": 300})
    s.save_element(page, "excel-review", "#sheet")


SHOTS = {
    "flow-overview": shot_flow_overview, "help-menu": shot_help_menu, "value-mode": shot_value_mode,
    "table-columns": shot_table_columns, "cross-page-region": shot_cross_page_region,
    "header-endmark": shot_header_endmark, "anchors": shot_anchors, "checks": shot_checks,
    "result-colors": shot_result_colors, "excel-review": shot_excel_review,
}


def main(codes: list[str] | None = None) -> int:
    import pdfmapper.server as server
    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server

    codes = codes or list(SHOTS)
    unknown = [code for code in codes if code not in SHOTS]
    if unknown:
        print(f"不認得的代號：{', '.join(unknown)}；可用：{', '.join(SHOTS)}")
        return 2
    home = Path(tempfile.mkdtemp(prefix="manual-shots-home-"))
    saved = {name: getattr(server, name) for name in ("TEMPLATES", "UPLOADS", "OUTPUT")}
    for name in saved:
        folder = home / name.lower()
        folder.mkdir()
        setattr(server, name, folder)
    httpd = make_server("127.0.0.1", 0, server.app, threaded=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    IMAGES.mkdir(parents=True, exist_ok=True)
    failed = []
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(channel="chrome")
            except Exception as error:  # noqa: BLE001
                print(f"找不到 Chrome：{error}")
                return 1
            shooter = Shooter(browser, f"http://127.0.0.1:{httpd.server_port}")
            for code in codes:
                try:
                    SHOTS[code](shooter)
                    print(f"{code}: {png_name(code).stat().st_size // 1024} KB")
                except Exception as error:  # noqa: BLE001 一張失敗不影響其他張
                    failed.append(code)
                    print(f"{code}: 失敗 {type(error).__name__}: {str(error).splitlines()[0]}")
            browser.close()
    finally:
        httpd.shutdown()
        for name, value in saved.items():
            setattr(server, name, value)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
