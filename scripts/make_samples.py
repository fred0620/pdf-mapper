"""產生仿進口報單的合成 PDF，所有資料皆為虛構，供測試與教學使用。

欄位標題與框線是底圖（影像），數值是文字層，和真實報單的兩層結構相同。
需要開發用套件（uv sync）。字型用專案內附的 tests/fonts，也可用 --font 指定。
"""
from __future__ import annotations

import argparse
import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas

W, H = 595.0, 842.0
DPI = 200
SCALE = DPI / 72
MONO = "Courier"
FIRST_ROWS = 2
REST_ROWS = 6
ROW_FIRST = (0.445, 0.64)
ROW_REST = (0.13, 0.92)
COLS = [0.04, 0.09, 0.40, 0.55, 0.68, 0.82, 0.96]
HEADERS = ["項次", "貨物名稱", "稅則號別", "單價條件", "淨重數量", "完稅價格"]
PRODUCTS = ["木製辦公桌", "金屬座椅", "折疊收納櫃", "電動升降桌", "餐桌組", "鋁合金層架", "沙發椅", "書櫃"]


# 專案內附的字型子集（Noto Sans CJK TC，OFL 授權），只含範例與測試用到的字。
# 放在專案裡，CI 和每台電腦畫出來的範例都一樣，不依賴系統有沒有中文字型。
BUNDLED_FONT = Path(__file__).resolve().parent.parent / "tests" / "fonts" / "NotoSansTC-subset.otf"


def load_font(path: str | None, size: int):
    candidates = [path] if path else []
    candidates += [str(BUNDLED_FONT), "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                   "C:/Windows/Fonts/msjh.ttc", "/System/Library/Fonts/PingFang.ttc"]
    for item in candidates:
        try:
            return ImageFont.truetype(item, size, index=3 if item.endswith("NotoSansCJK-Regular.ttc") else 0)
        except OSError:
            continue
    raise SystemExit("找不到繁中字型，請用 --font 指定")


class Sheet:
    """底圖：框線與欄位標題。"""

    def __init__(self, font_path):
        self.image = Image.new("RGB", (int(W * SCALE), int(H * SCALE)), "white")
        self.draw = ImageDraw.Draw(self.image)
        self.font = load_font(font_path, 22)
        self.big = load_font(font_path, 62)
        self.labels: list[tuple[str, float, float]] = []

    def px(self, x, y):
        return x * self.image.width, y * self.image.height

    def line(self, x0, y0, x1, y1, width=2):
        self.draw.line([self.px(x0, y0), self.px(x1, y1)], fill="black", width=width)

    def label(self, text, x, y, font=None):
        self.draw.text(self.px(x, y), text, fill="black", font=font or self.font)
        self.labels.append((text, x, y))


def first_page_base(font_path):
    s = Sheet(font_path)
    s.label("進口報單", 0.04, 0.025, s.big)
    for y in (0.095, 0.14, 0.185, 0.23, 0.275, 0.33, 0.385, 0.66, 0.70):
        s.line(0.04, y, 0.96, y)
    s.line(0.04, 0.095, 0.04, 0.95, 3); s.line(0.96, 0.095, 0.96, 0.95, 3); s.line(0.04, 0.95, 0.96, 0.95, 3)
    for x, top, bottom in ((0.5, 0.095, 0.275), (0.66, 0.66, 0.95)):
        s.line(x, top, x, bottom)
    s.label("報單號碼(3)", 0.05, 0.106)
    s.label("頁次", 0.52, 0.106)
    s.label("進口日期(14)", 0.05, 0.151)
    s.label("報關日期(15)", 0.52, 0.151)
    s.label("統一編號(23)", 0.05, 0.196)
    s.label("主提單號碼(8)", 0.52, 0.196)
    s.label("離岸價格(17)", 0.05, 0.241)
    s.label("運費(18)", 0.52, 0.241)
    s.label("生產國別(36)", 0.05, 0.29)
    s.label("保險費(19)", 0.52, 0.29)
    table_grid(s, 0.385, ROW_FIRST[1])
    s.label("總件數/單位(47)", 0.05, 0.671)
    s.label("進口稅", 0.68, 0.71)
    s.label("營業稅", 0.68, 0.755)
    s.label("稅費合計", 0.68, 0.80)
    s.label("標記", 0.05, 0.71)
    return s


def table_grid(s, top, bottom):
    for x in COLS[1:-1]:
        s.line(x, top, x, bottom)
    header_y = top + 0.018
    for text, x in zip(HEADERS, COLS):
        s.label(text, x + 0.008, header_y)
    s.line(0.04, top + 0.052, 0.96, top + 0.052)
    s.line(0.04, bottom, 0.96, bottom)


def rest_page_base(font_path):
    s = Sheet(font_path)
    s.label("進口報單(續頁)", 0.04, 0.03, load_font(font_path, 40))
    s.label("報單號碼(3)", 0.62, 0.04)
    s.line(0.04, 0.078, 0.96, 0.078, 3)
    s.line(0.04, 0.078, 0.04, 0.93, 3); s.line(0.96, 0.078, 0.96, 0.93, 3); s.line(0.04, 0.93, 0.96, 0.93, 3)
    table_grid(s, 0.078, 0.93)
    return s


def make_items(count, rng):
    items = []
    for i in range(count):
        price = rng.randrange(1000, 90000) * 1.0
        items.append({
            "no": str(i + 1),
            "name": rng.choice(PRODUCTS),
            "code": f"94{rng.randrange(10, 99)}.{rng.randrange(10, 99)}.00.00-{rng.randrange(0, 9)}",
            "ref": "CI999999999999",
            "cond": "CIF TWD",
            "price": f"{price:,.2f}",
            "weight": f"{rng.randrange(5, 400)}.00",
            "qty": f"{rng.randrange(1, 9)}SET",
            "value": f"{int(price):,}",
            "raw_value": int(price),
        })
    return items


def make_doc(item_count, seed):
    rng = random.Random(seed)
    items = make_items(item_count, rng)
    total = sum(item["raw_value"] for item in items)
    duty, vat = rng.randrange(500, 3000), int(total * 0.05)
    freight = rng.randrange(2000, 9000)
    remaining = max(0, item_count - FIRST_ROWS)
    pages = 1 + (remaining + REST_ROWS - 1) // REST_ROWS
    return {
        "items": items, "pages": pages, "no": f"AA/12/{rng.randrange(100, 999)}/{rng.randrange(10000, 99999)}",
        "import_date": "112/04/22", "declare_date": "112/04/21", "tax_id": f"{rng.randrange(10**7, 10**8)}",
        "bl": f"BL{rng.randrange(10**8, 10**9)}", "fob": f"{total - freight:,.2f}", "freight": f"{freight:,.2f}",
        "insurance": "2,447.78", "origin": "CN", "packages": f"{rng.randrange(10, 400)} PKG",
        "duty": f"{duty:,}", "vat": f"{vat:,}", "tax_total": f"{duty + vat:,}",
    }


def value_items(doc):
    """第一頁固定欄位：(文字, x, y 中心, 靠右?)"""
    return [
        (doc["no"], 0.20, 0.117, False), (f"1 / {doc['pages']}", 0.60, 0.117, False),
        (doc["import_date"], 0.20, 0.162, False), (doc["declare_date"], 0.67, 0.162, False),
        (doc["tax_id"], 0.20, 0.207, False), (doc["bl"], 0.67, 0.207, False),
        (doc["fob"], 0.47, 0.252, True), (doc["freight"], 0.93, 0.252, True),
        (doc["origin"], 0.20, 0.301, False), (doc["insurance"], 0.93, 0.301, True),
        (doc["packages"], 0.20, 0.682, False), (doc["duty"], 0.93, 0.721, True),
        (doc["vat"], 0.93, 0.766, True), (doc["tax_total"], 0.93, 0.811, True),
    ]


def row_values(item, top, height):
    """每一列的項次在列中央，其他欄由上往下排，和真實報單一樣。"""
    pad = 0.13 * height
    step = (height - 2 * pad) / 3
    y = [top + pad + step * i for i in range(4)]
    mid = top + height / 2
    return [
        (item["no"], COLS[0] + 0.02, mid, False),
        (item["ref"], COLS[2] + 0.01, y[0], False), (item["code"], COLS[2] + 0.01, y[2], False),
        (item["cond"], COLS[3] + 0.01, y[0], False), (item["price"], COLS[3] + 0.01, y[1], False),
        (item["weight"], COLS[5] - 0.01, y[0], True), (item["qty"], COLS[5] - 0.01, y[1], True),
        (item["value"], COLS[6] - 0.01, y[1], True),
    ]


def page_values(doc, index):
    items = doc["items"]
    values = []
    if index == 0:
        values += value_items(doc)
        chunk, (top, bottom) = items[:FIRST_ROWS], (ROW_FIRST[0], ROW_FIRST[1])
        rows = FIRST_ROWS
    else:
        start = FIRST_ROWS + REST_ROWS * (index - 1)
        chunk, (top, bottom) = items[start:start + REST_ROWS], ROW_REST
        rows = REST_ROWS
        values.append((doc["no"], 0.76, 0.051, False))
    height = (bottom - top) / rows
    for i, item in enumerate(chunk):
        values += row_values(item, top + i * height, height)
    return values, chunk, top, height


def cjk_labels(sheet, canvas_obj, font_name):
    canvas_obj.setFont(font_name, 8)
    canvas_obj.setFillColorRGB(1, 1, 1)
    for text, x, y in sheet.labels:
        canvas_obj.drawString(x * W, H - (y + 0.012) * H, text)
    canvas_obj.setFillColorRGB(0, 0, 0)


def write_pdf(path, doc, font_path, shift=(0.0, 0.0), scale=1.0, angle=0.0, scanned=False,
              hidden_labels=False, noise=False):
    """shift 為頁面比例；scale/angle 模擬影印偏差；scanned 表示數值也燒進底圖。"""
    out = canvas.Canvas(str(path), pagesize=(W, H))
    pdfmetrics.registerFont(UnicodeCIDFont("MSung-Light"))
    for index in range(doc["pages"]):
        sheet = first_page_base(font_path) if index == 0 else rest_page_base(font_path)
        values, chunk, top, height = page_values(doc, index)
        if scanned:
            value_font = load_font(font_path, 22)
            for text, x, y, right in values:
                anchor = "rm" if right else "lm"
                sheet.draw.text(sheet.px(x, y), text, fill="black", font=value_font, anchor=anchor)
        for i, item in enumerate(chunk):  # 品名一律在影像中
            sheet.draw.text(sheet.px(COLS[1] + 0.008, top + i * height + 0.02), item["name"],
                            fill="black", font=sheet.font)
        image = sheet.image
        if angle or scale != 1.0 or shift != (0.0, 0.0):
            canvas_size = image.size
            scaled = image.resize((int(image.width * scale), int(image.height * scale)), Image.BILINEAR)
            base = Image.new("RGB", canvas_size, "white")
            base.paste(scaled, (int(shift[0] * image.width), int(shift[1] * image.height)))
            image = base.rotate(angle, resample=Image.BILINEAR, fillcolor="white")
        if noise:
            image = image.filter(ImageFilter.GaussianBlur(0.6))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=80)
        buffer.seek(0)
        out.drawImage(ImageReader(buffer), 0, 0, W, H)
        if not scanned:
            import math
            theta = math.radians(angle)
            for text, x, y, right in values:
                px, py = x * scale + shift[0], y * scale + shift[1]
                dx, dy = px - 0.5, py - 0.5
                # PIL 的 rotate 為逆時針
                rx = 0.5 + dx * math.cos(theta) + dy * math.sin(theta) * H / W
                ry = 0.5 - dx * math.sin(theta) * W / H + dy * math.cos(theta)
                base_y = H - ry * H - 3
                out.setFont(MONO if text.isascii() else "MSung-Light", 9)
                if right:
                    out.drawRightString(rx * W, base_y, text)
                else:
                    out.drawString(rx * W, base_y, text)
        if hidden_labels:
            cjk_labels(sheet, out, "MSung-Light")
        out.showPage()
    out.save()


def build_all(folder: Path, font_path=None) -> dict[str, dict]:
    folder.mkdir(parents=True, exist_ok=True)
    plans = {
        "sample_1_standard.pdf": dict(items=9, seed=1),
        "sample_2_shifted.pdf": dict(items=15, seed=2, shift=(0.008, 0.012), scale=0.985, angle=0.4),
        "sample_3_hidden_labels.pdf": dict(items=4, seed=3, hidden_labels=True),
        "sample_4_scanned.pdf": dict(items=8, seed=4, scanned=True, noise=True, shift=(0.004, -0.004)),
    }
    docs = {}
    for name, plan in plans.items():
        plan = dict(plan)
        doc = make_doc(plan.pop("items"), plan.pop("seed"))
        write_pdf(folder / name, doc, font_path, **plan)
        docs[name] = doc
    broken = make_doc(9, 5)  # 故意做壞：少一列且稅費合計對不上
    broken["tax_total"] = "1"
    del broken["items"][4]
    for i, item in enumerate(broken["items"]):
        item["no"] = str(i + 1 if i < 4 else i + 2)
    write_pdf(folder / "sample_5_errors.pdf", broken, font_path)
    docs["sample_5_errors.pdf"] = broken
    write_invoice(folder / "sample_6_invoice.pdf", font_path)
    write_floating(folder / "sample_7_table_a.pdf", 0.2, FLOAT_ROWS, font_path)
    write_floating(folder / "sample_8_table_b.pdf", 0.42, FLOAT_ROWS[:3], font_path)
    return docs


def write_invoice(path, font_path=None):
    """另一種版面的虛構單據，用來示範多範本自動選擇。"""
    sheet = Sheet(font_path)
    sheet.label("商業發票", 0.08, 0.05, sheet.big)
    for y in (0.16, 0.22, 0.28, 0.40, 0.46):
        sheet.line(0.08, y, 0.92, y)
    for text, x, y in (("發票號碼", 0.1, 0.175), ("開立日期", 0.1, 0.235), ("品項", 0.1, 0.415),
                       ("數量", 0.6, 0.415), ("金額", 0.78, 0.415), ("總金額", 0.6, 0.86)):
        sheet.label(text, x, y)
    buffer = io.BytesIO()
    sheet.image.save(buffer, "JPEG", quality=85)
    buffer.seek(0)
    out = canvas.Canvas(str(path), pagesize=(W, H))
    out.drawImage(ImageReader(buffer), 0, 0, W, H)
    out.setFont(MONO, 10)
    rows = [("1", "A-100", "2", "1,200"), ("2", "B-200", "5", "3,500")]
    values = [("INV-2023-0042", 0.3, 0.188), ("2023/04/14", 0.3, 0.248), ("4,700", 0.78, 0.873)]
    for i, (no, name, qty, amount) in enumerate(rows):
        y = 0.49 + i * 0.04
        values += [(no, 0.1, y), (name, 0.2, y), (qty, 0.6, y), (amount, 0.78, y)]
    for text, x, y in values:
        out.drawString(x * W, H - y * H - 3, text)
    out.showPage()
    out.save()


FLOAT_COLS = [0.08, 0.18, 0.46, 0.6, 0.92]
FLOAT_ROWS = [
    # (序號, 內容行, 代碼, 金額)
    ("1", ["1243", "1234", "dfegfrgs", "sfg"], "A", "1"),
    ("2", ["123"], "12345667765-long-code", "20"),
    ("3", ["78"], "B", "300"),
    ("4", ["a", "b"], "C", "4"),
    ("5", ["9"], "D", "5"),
]


def write_floating(path, top, rows, font_path=None, text_header=False):
    """表頭位置和列數都不固定、內容會跨欄的表格，表尾緊跟在最後一列之後。"""
    sheet = Sheet(font_path)
    sheet.label("明細報表", 0.08, 0.04, sheet.big)
    labels = (("序號", FLOAT_COLS[0]), ("內容", FLOAT_COLS[1]), ("代碼", FLOAT_COLS[2]), ("金額", FLOAT_COLS[3]))
    if not text_header:
        for text, x in labels:
            sheet.label(text, x + 0.008, top)
    step = 0.022
    y = top + 0.05
    placed = []
    for no, lines, code, amount in rows:
        placed += [(no, FLOAT_COLS[0] + 0.01, y, False), (code, FLOAT_COLS[2] + 0.01, y, False),
                   (amount, FLOAT_COLS[4] - 0.02, y, True)]
        for offset, line in enumerate(lines):
            placed.append((line, FLOAT_COLS[1] + 0.01, y + offset * step, False))
        y += step * max(len(lines), 1)
    sheet.label("合計", 0.46, y + 0.02)
    buffer = io.BytesIO()
    sheet.image.save(buffer, "JPEG", quality=85)
    buffer.seek(0)
    pdfmetrics.registerFont(UnicodeCIDFont("MSung-Light"))
    out = canvas.Canvas(str(path), pagesize=(W, H))
    out.drawImage(ImageReader(buffer), 0, 0, W, H)
    out.setFont(MONO, 9)
    for text, x, y_pos, right in placed:
        (out.drawRightString if right else out.drawString)(x * W, H - y_pos * H - 3, text)
    out.showPage()
    out.save()


def build_floating_template() -> dict:
    """基準為 top=0.2 的版面。代碼欄的長內容會跨到金額欄的範圍。"""
    columns = [{"id": "no", "name": "序號", "band": 0}, {"id": "body", "name": "內容", "band": 1, "join": "newline"},
               {"id": "code", "name": "代碼", "band": 2}, {"id": "amount", "name": "金額", "band": 3}]
    return {
        "schema_version": 1, "template_id": "floating_demo", "name": "浮動表格（示範）",
        "fields": [], "validations": [],
        "anchors": [{"id": "title", "text": "明細報表", "box": [0.08, 0.04, 0.34, 0.1], "page_rule": "first", "ref_page": 0}],
        "tables": [{
            "id": "items", "name": "明細", "columns": columns, "key_column": "no", "key_position": "auto", "required": True,
            "regions": [{"page_rule": "first", "ref_page": 0, "box": [0.08, 0.236, 0.92, 0.9], "dividers": FLOAT_COLS,
                         "header": {"text": "序號", "box": [0.086, 0.198, 0.18, 0.222]}}],
            "end_marker": {"text": "合計", "box": [0.458, 0.466, 0.53, 0.49], "ref_page": 0},
        }],
    }


SPLIT_COLS = [0.08, 0.2, 0.6, 0.92]


def write_split(path, pages, font_path=None):
    """逐頁放文字的簡單表格，用來測跨頁。pages 是每頁的 [(欄, y, 文字)]，另加頁尾備註。"""
    pdfmetrics.registerFont(UnicodeCIDFont("MSung-Light"))
    out = canvas.Canvas(str(path), pagesize=(W, H))
    for items in pages:
        sheet = Sheet(font_path)
        sheet.label("跨頁報表", 0.08, 0.04, sheet.big)
        sheet.label("頁首", 0.8, 0.05)
        sheet.label("頁尾", 0.08, 0.93)
        sheet.label("備註", 0.8, 0.93)
        buffer = io.BytesIO()
        sheet.image.save(buffer, "JPEG", quality=85)
        buffer.seek(0)
        out.drawImage(ImageReader(buffer), 0, 0, W, H)
        out.setFont(MONO, 10)
        for column, y, text in items:
            out.drawString((SPLIT_COLS[column] + 0.01) * W, H - y * H - 3, text)
        out.showPage()
    out.save()


def build_split_template(key_position="top", required=False) -> dict:
    columns = [{"id": "no", "name": "項次", "band": 0}, {"id": "body", "name": "內容", "band": 1, "join": "newline"},
               {"id": "code", "name": "代碼", "band": 2}]
    if required:
        columns[2]["row_required"] = True
    anchors = []
    for page, rule in ((0, "first"), (1, "rest")):
        anchors += [
            {"id": f"t{page}", "text": "跨頁報表", "box": [0.08, 0.04, 0.34, 0.1], "page_rule": rule, "ref_page": page},
            {"id": f"f{page}", "text": "頁尾", "box": [0.078, 0.928, 0.14, 0.952], "page_rule": rule, "ref_page": page},
            {"id": f"r{page}", "text": "備註", "box": [0.798, 0.928, 0.86, 0.952], "page_rule": rule, "ref_page": page},
        ]
    return {
        "schema_version": 1, "template_id": f"split_{key_position}", "name": "跨頁測試", "validations": [],
        "fields": [], "anchors": anchors,
        "tables": [{
            "id": "items", "name": "明細", "columns": columns, "key_column": "no", "key_position": key_position,
            "required": True,
            "regions": [{"page_rule": "first", "ref_page": 0, "box": [0.08, 0.14, 0.92, 0.9], "dividers": SPLIT_COLS},
                        {"page_rule": "rest", "ref_page": 1, "box": [0.08, 0.14, 0.92, 0.9], "dividers": SPLIT_COLS}],
        }],
    }


def build_invoice_template() -> dict:
    """欄位與表格代號刻意和報單範本相同，用來確認輸出不會混欄。"""
    def field(fid, name, label_box, box, **kw):
        return {"id": fid, "name": name, "kind": "key_value", "page_rule": "first", "ref_page": 0,
                "label": {"text": name, "box": label_box}, "value_box": box, "required": True} | kw
    dividers = [0.08, 0.18, 0.58, 0.76, 0.92]
    return {
        "schema_version": 1, "template_id": "invoice_demo", "name": "商業發票（示範）",
        "fields": [
            field("declaration_no", "發票號碼", [0.1, 0.173, 0.2, 0.196], [0.28, 0.17, 0.9, 0.21]),
            field("tax_id", "開立日期", [0.1, 0.233, 0.2, 0.256], [0.28, 0.23, 0.9, 0.27], type="date"),
            field("tax_total", "總金額", [0.6, 0.858, 0.68, 0.881], [0.76, 0.855, 0.92, 0.89], type="number"),
        ],
        "anchors": [{"id": "title", "text": "商業發票", "box": [0.08, 0.05, 0.34, 0.11],
                     "page_rule": "first", "ref_page": 0}],
        "tables": [{
            "id": "items", "name": "品項明細", "key_column": "no", "key_position": "middle", "required": True,
            "columns": [{"id": "no", "name": "序號", "band": 0}, {"id": "name", "name": "品項", "band": 1},
                        {"id": "qty", "name": "數量", "band": 2}, {"id": "amount", "name": "金額", "band": 3}],
            "regions": [{"page_rule": "first", "ref_page": 0, "box": [0.08, 0.47, 0.92, 0.8], "dividers": dividers}],
        }],
        "validations": [{"type": "sum_column", "table": "items", "column": "amount", "equals": "tax_total", "tolerance": 1}],
    }


def build_template() -> dict:
    """示範範本，對應上面的版面。"""
    def field(fid, name, label, label_box, box, **kw):
        spec = {"id": fid, "name": name, "kind": "key_value", "page_rule": "first", "ref_page": 0,
                "label": {"text": label, "box": label_box}, "value_box": box, "type": "text", "required": True}
        return spec | kw
    columns = [
        {"id": "item", "name": "項次", "band": 0, "type": "number"},
        {"id": "name", "name": "貨物名稱", "band": 1},
        {"id": "ref", "name": "參考號", "band": 2, "pick_line": 1},
        {"id": "code", "name": "稅則號別", "band": 2, "pick_line": 2, "pattern": r"^\d{4}\.\d{2}\.\d{2}\.\d{2}-\d$"},
        {"id": "condition", "name": "條件", "band": 3, "pick_line": 1},
        {"id": "price", "name": "金額", "band": 3, "pick_line": 2, "type": "number"},
        {"id": "weight", "name": "淨重", "band": 4, "pick_line": 1, "type": "number"},
        {"id": "qty", "name": "數量", "band": 4, "pick_line": 2},
        {"id": "value", "name": "完稅價格", "band": 5, "type": "number"},
    ]
    return {
        "schema_version": 1, "template_id": "customs_demo", "name": "進口報單（示範）",
        "fields": [
            field("declaration_no", "報單號碼", "報單號碼", [0.05, 0.106, 0.145, 0.125], [0.19, 0.103, 0.49, 0.132]),
            field("page_info", "頁次", "頁次", [0.52, 0.106, 0.565, 0.125], [0.59, 0.103, 0.94, 0.132]),
            field("import_date", "進口日期", "進口日期", [0.05, 0.151, 0.15, 0.17], [0.19, 0.148, 0.49, 0.177], type="date"),
            field("tax_id", "統一編號", "統一編號", [0.05, 0.196, 0.15, 0.215], [0.19, 0.193, 0.49, 0.222], pattern=r"^\d{8}$"),
            field("fob_amount", "離岸價格", "離岸價格", [0.05, 0.241, 0.15, 0.26], [0.19, 0.238, 0.49, 0.267], type="number"),
            field("freight_amount", "運費", "運費", [0.52, 0.241, 0.585, 0.26], [0.66, 0.238, 0.95, 0.267], type="number"),
            field("duty_amount", "進口稅", "進口稅", [0.68, 0.71, 0.74, 0.73], [0.78, 0.708, 0.95, 0.735], type="number"),
            field("vat_amount", "營業稅", "營業稅", [0.68, 0.755, 0.74, 0.775], [0.78, 0.753, 0.95, 0.78], type="number"),
            field("tax_total", "稅費合計", "稅費合計", [0.68, 0.80, 0.76, 0.82], [0.78, 0.798, 0.95, 0.825], type="number"),
        ],
        "anchors": [
            {"id": "title", "text": "進口報單", "box": [0.04, 0.025, 0.30, 0.085], "page_rule": "first", "ref_page": 0},
            {"id": "total_pkg", "text": "總件數", "box": [0.05, 0.671, 0.13, 0.69], "page_rule": "first", "ref_page": 0},
            {"id": "c_title", "text": "進口報單(續頁)", "box": [0.04, 0.03, 0.36, 0.072], "page_rule": "rest", "ref_page": 1},
            {"id": "c_no", "text": "報單號碼", "box": [0.62, 0.04, 0.72, 0.06], "page_rule": "rest", "ref_page": 1},
            {"id": "c_h1", "text": "項次", "box": [0.048, 0.096, 0.09, 0.114], "page_rule": "rest", "ref_page": 1},
            {"id": "c_h2", "text": "完稅價格", "box": [0.828, 0.096, 0.92, 0.114], "page_rule": "rest", "ref_page": 1},
        ],
        "tables": [{
            "id": "items", "name": "貨物明細", "columns": columns,
            "key_column": "item", "key_position": "auto", "required": True,
            "regions": [
                {"page_rule": "first", "ref_page": 0, "box": [0.04, ROW_FIRST[0], 0.96, ROW_FIRST[1]], "dividers": COLS},
                {"page_rule": "rest", "ref_page": 1, "box": [0.04, ROW_REST[0], 0.96, ROW_REST[1]], "dividers": COLS},
            ],
        }],
        "validations": [
            {"type": "sum_fields", "fields": ["duty_amount", "vat_amount"], "equals": "tax_total", "tolerance": 1},
            {"type": "page_count", "field": "page_info"},
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="samples")
    parser.add_argument("--font")
    args = parser.parse_args()
    build_all(Path(args.out), args.font)
    print("完成")
