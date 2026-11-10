"""產生使用手冊「更新工具」一節的示意圖（SVG），輸出到 docs/images/。

風格：黑白灰、細線、只用綠色標出最重要的地方。改了文字或步驟後重新執行：
    uv run --project app python scripts/make_manual_figures.py
"""
from __future__ import annotations

from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"

FONT = "'Noto Sans TC','Noto Sans CJK TC','Microsoft JhengHei','PingFang TC',Helvetica,sans-serif"
MONO = "Consolas,Menlo,'Noto Sans Mono CJK TC',monospace"
INK, SOFT, FAINT, RULE, FILL = "#111111", "#666666", "#999999", "#d9d9d9", "#f4f4f4"
GREEN = "#2C5F34"


class Figure:
    def __init__(self, width: int, height: int):
        self.width, self.height = width, height
        self.parts: list[str] = []

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def text(self, x, y, value, size=14, weight=400, fill=INK, anchor="start", font=FONT, strike=False):
        decoration = ' text-decoration="line-through"' if strike else ""
        self.add(f'<text x="{x}" y="{y}" font-family="{font}" font-size="{size}" font-weight="{weight}" '
                 f'fill="{fill}" text-anchor="{anchor}"{decoration}>{escape(value)}</text>')

    def lines(self, x, y, values, size=13, fill=SOFT, gap=19, anchor="start"):
        for index, value in enumerate(values):
            self.text(x, y + index * gap, value, size=size, fill=fill, anchor=anchor)

    def rect(self, x, y, w, h, stroke=RULE, fill="none", radius=6, width=1, dash=False):
        dashes = ' stroke-dasharray="4 3"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" '
                 f'stroke="{stroke}" stroke-width="{width}"{dashes}/>')

    def line(self, x1, y1, x2, y2, stroke=RULE, width=1):
        self.add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{stroke}" stroke-width="{width}"/>')

    def arrow(self, x1, y, x2, stroke=FAINT):
        self.line(x1, y, x2 - 2, y, stroke, 1.5)
        self.add(f'<path d="M{x2 - 8},{y - 5} L{x2},{y} L{x2 - 8},{y + 5}" fill="none" stroke="{stroke}" stroke-width="1.5"/>')

    def folder(self, x, y, color=SOFT):
        """左上角在 (x, y)，大小 18 × 14。"""
        self.add(f'<path d="M{x},{y + 2} h6 l2,2 h10 v10 h-18 z" fill="#ffffff" stroke="{color}" stroke-width="1.2"/>')

    def file(self, x, y, color=SOFT, label=""):
        """左上角在 (x, y)，大小 14 × 18。"""
        self.add(f'<path d="M{x},{y} h9 l5,5 v13 h-14 z M{x + 9},{y} v5 h5" fill="#ffffff" stroke="{color}" stroke-width="1.2"/>')
        if label:
            self.text(x + 7, y + 15, label, size=6, weight=700, fill=color, anchor="middle")

    def entry(self, x, y, kind, name, note="", color=INK, note_color=SOFT, weight=400, strike=False):
        """資料夾清單的一行，y 是文字基線。"""
        icon = SOFT if color == INK else color
        if kind == "folder":
            self.folder(x, y - 12, icon)
        else:
            self.file(x + 2, y - 14, icon, "ZIP" if kind == "zip" else "")
        self.text(x + 26, y, name, size=14, weight=weight, fill=color, strike=strike)
        if note:
            self.text(x + 26 + len(name) * 8 + 12, y, note, size=12, fill=note_color)

    def badge(self, x, y, number):
        self.add(f'<circle cx="{x}" cy="{y}" r="11" fill="{INK}"/>')
        self.text(x, y + 4.5, str(number), size=13, weight=700, fill="#ffffff", anchor="middle")

    def save(self, name: str) -> None:
        body = "\n  ".join(self.parts)
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.width} {self.height}" '
               f'width="{self.width}" height="{self.height}">\n'
               f'  <rect width="100%" height="100%" fill="#ffffff"/>\n  {body}\n</svg>\n')
        (OUT / name).write_text(svg, encoding="utf-8")


def folder_layout() -> None:
    f = Figure(760, 270)
    columns = (32, 250, 470)
    f.text(columns[0], 30, "資料夾", 12, 700, SOFT)
    f.text(columns[1], 30, "內容", 12, 700, SOFT)
    f.text(columns[2], 30, "更新時", 12, 700, SOFT)
    f.line(24, 42, 736, 42, INK, 1.2)
    rows = [
        ("file", "run.bat", "入口，雙擊開啟工具", "換新", INK, SOFT),
        ("folder", "app", "程式本身", "整包換新，不要放自己的檔案", INK, SOFT),
        ("folder", "workspace", "你的範本、匯出結果、紀錄", "不會動到", GREEN, GREEN),
        ("folder", "runtime", "Python 與套件", "不用管，壞掉可以刪掉重建", INK, SOFT),
    ]
    for index, (kind, name, content, update, color, update_color) in enumerate(rows):
        y = 78 + index * 44
        f.entry(columns[0], y, kind, name, color=color, weight=700 if color == GREEN else 400)
        f.text(columns[1], y, content, 14, fill=INK)
        f.text(columns[2], y, update, 14, 700 if update_color == GREEN else 400, update_color)
        f.line(24, y + 20, 736, y + 20, INK if index == len(rows) - 1 else RULE, 1.2 if index == len(rows) - 1 else 1)
    f.text(columns[0], 258, "workspace 和 runtime 是第一次雙擊 run.bat 時自動建立的，下載的 ZIP 裡沒有它們。", 12, fill=SOFT)
    f.save("update-01-folder.svg")


def update_steps() -> None:
    f = Figure(760, 330)
    panels = (20, 272, 524)
    width = 216
    titles = ("下載新版", "放進工具資料夾", "雙擊 run.bat")
    for index, (x, title) in enumerate(zip(panels, titles), start=1):
        f.badge(x + 11, 24, index)
        f.text(x + 30, 29, title, 15, 700)
        f.rect(x, 48, width, 190, fill=FILL, radius=8, stroke=RULE)
        if index < 3:
            f.arrow(x + width + 8, 143, x + width + 30)

    # 1. GitLab Releases 頁
    x = panels[0]
    f.rect(x + 12, 60, width - 24, 166, fill="#ffffff", stroke=RULE)
    f.text(x + 24, 84, "Deploy > Releases", 12, fill=SOFT)
    f.line(x + 12, 96, x + width - 12, 96)
    f.text(x + 24, 122, "PDF 解析器 0.2.1", 14, 700)
    f.text(x + 24, 142, "最新版本", 11, fill=FAINT)
    f.rect(x + 24, 160, width - 48, 34, stroke=GREEN, width=1.5)
    f.file(x + 34, 168, GREEN, "ZIP")
    f.text(x + 56, 182, "pdf-mapper-0.2.1.zip", 12, 700, GREEN)
    f.lines(x + width / 2, 262, ["在公司 GitLab 專案頁", "下載 ZIP，不用解壓"], anchor="middle")

    # 2. 工具資料夾
    x = panels[1]
    f.rect(x + 12, 60, width - 24, 166, fill="#ffffff", stroke=RULE)
    f.text(x + 24, 82, "pdf-mapper", 12, 700, SOFT)
    f.line(x + 12, 92, x + width - 12, 92)
    for row, (kind, name) in enumerate((("folder", "app"), ("folder", "runtime"), ("folder", "workspace"),
                                        ("file", "run.bat"))):
        f.entry(x + 24, 116 + row * 24, kind, name)
    f.entry(x + 24, 212, "zip", "pdf-mapper-0.2.1.zip", color=GREEN, weight=700)
    f.lines(x + width / 2, 262, ["和 run.bat 放在同一層", "其他東西都不用動"], anchor="middle")

    # 3. 黑色視窗
    x = panels[2]
    f.rect(x + 12, 60, width - 24, 166, fill="#ffffff", stroke=SOFT)
    f.line(x + 12, 80, x + width - 12, 80, RULE)
    for dot in range(3):
        f.add(f'<circle cx="{x + 24 + dot * 10}" cy="70" r="3" fill="{RULE}"/>')
    console = ["找到新版本 0.2.1", "（目前 0.2.0）", "要現在更新嗎？[Y/n]"]
    for row, value in enumerate(console):
        f.text(x + 22, 104 + row * 20, value, 12, fill=INK, font=MONO)
    f.text(x + 22, 164, "按 Enter", 12, 700, GREEN, font=MONO)
    f.text(x + 22, 194, "已更新到 0.2.1。", 12, fill=INK, font=MONO)
    f.text(x + 22, 212, "上一版保留在 app.old", 11, fill=SOFT, font=MONO)
    f.lines(x + width / 2, 262, ["問要不要更新時按 Enter", "裝好後 ZIP 會自動刪掉"], anchor="middle")

    f.text(380, 318, "範本、匯出結果都在 workspace，更新完全不會碰到。", 13, 700, GREEN, anchor="middle")
    f.save("update-02-steps.svg")


def update_result() -> None:
    f = Figure(760, 260)
    f.text(40, 30, "更新前", 15, 700)
    f.text(420, 30, "更新後", 15, 700)
    f.rect(24, 44, 320, 196, fill=FILL, radius=8)
    f.rect(404, 44, 332, 196, fill=FILL, radius=8)
    before = [("folder", "app", "0.2.0", INK, SOFT, 400), ("folder", "runtime", "", INK, SOFT, 400),
              ("folder", "workspace", "", INK, SOFT, 400), ("file", "run.bat", "", INK, SOFT, 400),
              ("zip", "pdf-mapper-0.2.1.zip", "", INK, SOFT, 400)]
    after = [("folder", "app", "0.2.1 新版", GREEN, GREEN, 700),
             ("folder", "app.old", "0.2.0 上一版，退回時使用", INK, SOFT, 400),
             ("folder", "runtime", "不變", INK, SOFT, 400),
             ("folder", "workspace", "不變，範本都還在", GREEN, GREEN, 700),
             ("file", "run.bat", "換新", INK, SOFT, 400)]
    for row, (kind, name, note, color, note_color, weight) in enumerate(before):
        f.entry(44, 78 + row * 34, kind, name, note, color, note_color, weight)
    for row, (kind, name, note, color, note_color, weight) in enumerate(after):
        f.entry(424, 78 + row * 34, kind, name, note, color, note_color, weight)
    f.arrow(352, 142, 396)
    f.text(374, 258, "ZIP 在安裝完成後自動刪除", 12, fill=SOFT, anchor="middle")
    f.save("update-03-result.svg")


def manual_update() -> None:
    f = Figure(760, 320)
    width, gap = 168, 20
    steps = [
        ("關閉工具", ["關閉瀏覽器頁面", "和黑色視窗"]),
        ("舊版改名", ["把 app 改名為 app.old", "（已經有 app.old", "就先刪掉）"]),
        ("複製新版", ["解壓新版 ZIP，把裡面的", "app 和 run.bat 複製進來", "run.bat 選「取代」"]),
        ("雙擊 run.bat", ["工具會用新版開啟", "範本都還在"]),
    ]
    for index, (title, caption) in enumerate(steps):
        x = 16 + index * (width + gap)
        f.badge(x + 11, 24, index + 1)
        f.text(x + 30, 29, title, 15, 700)
        f.rect(x, 48, width, 150, fill=FILL, radius=8)
        f.lines(x + width / 2, 226, caption, anchor="middle")
        if index < 3:
            f.arrow(x + width + 2, 123, x + width + gap - 2)

    # 1. 兩個視窗都關掉
    x = 16
    for offset, label in ((0, "瀏覽器"), (34, "黑色視窗")):
        f.rect(x + 22 + offset, 72 + offset, 104, 62, fill="#ffffff", stroke=SOFT)
        f.text(x + 30 + offset, 92 + offset, label, 11, fill=SOFT)
        f.text(x + 116 + offset, 91 + offset, "×", 16, 700, INK, anchor="middle")

    # 2. app → app.old
    x = 16 + (width + gap)
    f.folder(x + 30, 100)
    f.text(x + 56, 112, "app", 14)
    f.arrow(x + 30, 136, x + 70)
    f.folder(x + 78, 128)
    f.text(x + 104, 140, "app.old", 14, 700)

    # 3. ZIP 裡的 app 和 run.bat
    x = 16 + 2 * (width + gap)
    f.rect(x + 14, 62, 144, 74, fill="#ffffff", stroke=RULE, dash=True)
    f.text(x + 24, 80, "pdf-mapper-0.2.1", 11, fill=SOFT)
    f.entry(x + 24, 104, "folder", "app", color=GREEN, weight=700)
    f.entry(x + 24, 128, "file", "run.bat", color=GREEN, weight=700)
    f.add(f'<path d="M{x + 86},142 v20" stroke="{FAINT}" stroke-width="1.5"/>')
    f.add(f'<path d="M{x + 81},155 L{x + 86},163 L{x + 91},155" fill="none" stroke="{FAINT}" stroke-width="1.5"/>')
    f.folder(x + 46, 170)
    f.text(x + 70, 182, "工具資料夾", 12, fill=INK)

    # 4. 雙擊
    x = 16 + 3 * (width + gap)
    f.file(x + 70, 86, INK)
    f.add(f'<path d="M{x + 90},100 l0,22 l6,-6 l4,9 l4,-2 l-4,-9 l8,0 z" fill="#ffffff" stroke="{INK}" stroke-width="1.2"/>')
    f.text(x + 84, 156, "run.bat", 13, 700, anchor="middle")
    f.text(x + 84, 176, "雙擊", 12, fill=SOFT, anchor="middle")

    f.text(380, 300, "不要動 workspace 和 runtime。範本和匯出結果都在 workspace。", 13, 700, GREEN, anchor="middle")
    f.save("update-04-manual.svg")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    folder_layout()
    update_steps()
    update_result()
    manual_update()
    print("完成")


if __name__ == "__main__":
    main()
