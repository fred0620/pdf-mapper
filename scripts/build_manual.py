"""把使用手冊與換版說明轉成單一 HTML（圖片內嵌），放在 app/，雙擊就能看，也會隨發布包一起出去。

用 uv run --project app python scripts/build_manual.py 執行。
"""
import base64
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

LAYOUT_CSS = """
* { box-sizing: border-box; }
@media (prefers-reduced-motion: no-preference) { html { scroll-behavior: smooth; } }
body { margin: 0; background: var(--canvas); color: var(--text-strong); font: 14px/1.7 var(--font); }
.topbar { position: fixed; inset: 0 0 auto 0; height: 52px; z-index: 10; display: flex; align-items: center; gap: 16px;
  padding: 0 20px; background: var(--surface); box-shadow: 0 1px 0 var(--ink-3); }
.topbar .brand { font-size: 14px; font-weight: 600; white-space: nowrap; }
.search { position: relative; flex: 1; max-width: 420px; }
.search input { width: 100%; height: var(--control); padding: 0 12px; border: 0; border-radius: var(--radius-md); background: var(--ink-1);
  color: var(--text-strong); font: inherit; box-shadow: inset 0 0 0 1px var(--ink-3); }
.search input:focus { outline: none; box-shadow: inset 0 0 0 1px var(--accent), 0 0 0 3px var(--accent-soft); }
.results { position: absolute; top: calc(var(--control) + 6px); left: 0; right: 0; max-height: 60vh; overflow-y: auto; margin: 0; padding: 6px;
  list-style: none; background: var(--surface); border-radius: var(--radius-lg); box-shadow: var(--shadow-float); }
.results a { display: block; padding: 8px 10px; border-radius: var(--radius-md); color: var(--text-strong); text-decoration: none; }
.results a:hover, .results a:focus { background: var(--ink-2); outline: none; }
.results small { display: block; color: var(--text); font-size: 12.5px; line-height: 1.5; overflow-wrap: anywhere; }
.results mark { background: var(--accent-soft); color: inherit; border-radius: 2px; }
.results .none { padding: 8px 10px; color: var(--text); }
nav.sidebar { position: fixed; top: 52px; bottom: 0; left: 0; width: 272px; overflow-y: auto; padding: 16px 12px 40px; background: var(--surface);
  box-shadow: 1px 0 0 var(--ink-3); }
nav.sidebar ul { list-style: none; margin: 0; padding: 0; }
nav.sidebar ul ul { margin: 2px 0 8px 10px; }
nav.sidebar a { display: block; padding: 3px 8px; border-radius: var(--radius-sm); color: var(--text); text-decoration: none; font-size: 13px; line-height: 1.5; }
nav.sidebar > ul > li > a { color: var(--text-strong); font-weight: 600; margin-top: 6px; }
nav.sidebar a:hover { background: var(--ink-2); }
nav.sidebar a[aria-current="true"] { background: var(--accent-soft); color: var(--accent-text); }
main { margin: 52px 0 0 272px; padding: 36px 40px 96px; }
article { max-width: 800px; margin: 0 auto; }
h1 { font-size: 28px; line-height: 1.3; margin: 0 0 12px; }
h2 { font-size: 22px; line-height: 1.4; margin: 56px 0 12px; padding-top: 14px; box-shadow: 0 -1.5px 0 var(--text-strong); }
h3 { font-size: 17.5px; margin: 34px 0 8px; }
h4 { font-size: 15px; margin: 26px 0 6px; }
h2, h3, h4 { scroll-margin-top: 68px; }
p, ul, ol { margin: 10px 0; }
li { margin: 3px 0; }
a { color: var(--accent-text); }
img { display: block; max-width: 100%; height: auto; margin: 14px 0 20px; border-radius: var(--radius-md); box-shadow: var(--shadow-window); background: var(--surface); }
table { width: 100%; border-collapse: collapse; margin: 14px 0 22px; font-size: 13.5px; line-height: 1.6; }
th { text-align: left; padding: 6px 12px 6px 0; border-top: 1.5px solid var(--text-strong); border-bottom: 1px solid var(--text-strong); }
td { text-align: left; padding: 6px 12px 6px 0; border-bottom: 1px solid var(--ink-3); vertical-align: top; }
tbody tr:last-child td { border-bottom: 1.5px solid var(--text-strong); }
blockquote { margin: 16px 0; padding: 2px 0 2px 14px; border-left: 3px solid var(--accent); }
code { background: var(--ink-2); padding: 1px 5px; border-radius: var(--radius-sm); font: 13px var(--mono); }
pre { background: var(--well); padding: 12px 14px; border-radius: var(--radius-md); overflow-x: auto; line-height: 1.55; }
pre code { background: none; padding: 0; }
@media (max-width: 900px) { nav.sidebar { display: none; } main { margin-left: 0; padding: 24px 16px 80px; } }
@media print {
  .topbar, nav.sidebar { display: none; }
  main { margin: 0; padding: 0; }
  body { background: #fff; }
  h2 { break-after: avoid; } img { break-inside: avoid; box-shadow: none; border: 1px solid #ccc; }
}
"""


def tokens() -> str:
    """工具的 Stageshow 設計 token 直接從 style.css 的 :root 複製，手冊不寫死色碼。"""
    css = (ROOT / "app" / "pdfmapper" / "web" / "style.css").read_text(encoding="utf-8")
    match = re.search(r":root\s*\{.*?\n\}", css, re.S)
    assert match, "style.css 找不到 :root"
    return match.group(0)


def shot_to_image(markdown_text: str) -> str:
    """`<!-- shot: 代號 -->` 有圖檔（docs/images/shot-代號.png，scripts/manual_shots.py 產生）就換成圖片，alt 用該節標題；沒有就略過。"""
    heading, lines = "", []
    for line in markdown_text.splitlines():
        title = re.match(r"#{2,4}\s+(.*?)\s*(\{[^}]*\})?\s*$", line)
        if title:
            heading = re.sub(r"^\d+(\.\d+)*\.?\s*", "", title.group(1))
        shot = re.match(r"<!--\s*shot:\s*([\w-]+)\s*-->\s*$", line)
        if shot:
            if (DOCS / "images" / f"shot-{shot.group(1)}.png").is_file():
                lines.append(f"![{heading}](images/shot-{shot.group(1)}.png)")
            continue
        lines.append(line)
    return "\n".join(lines)


def inline_image(match: re.Match) -> str:
    path = DOCS / match.group(1)
    mime = "image/svg+xml" if path.suffix == ".svg" else "image/png"
    data = base64.b64encode(path.read_bytes()).decode()
    return f'src="data:{mime};base64,{data}"'


PAGES = {"使用手冊": "PDF 解析器使用手冊", "換版說明": "PDF 解析器換版說明"}


def sidebar(tokens_list: list[dict]) -> str:
    """章（h2）與節（h3）兩層的目錄。"""
    items = []
    for chapter in tokens_list:
        sections = "".join(f'<li><a href="#{c["id"]}">{c["name"]}</a></li>' for c in chapter["children"])
        items.append(f'<li><a href="#{chapter["id"]}">{chapter["name"]}</a>{f"<ul>{sections}</ul>" if sections else ""}</li>')
    return f'<nav class="sidebar" aria-label="目錄"><ul>{"".join(items)}</ul></nav>'


def build(name: str, title: str) -> None:
    # attr_list：章節用 {#id} 寫明確的錨點，工具裡的說明卡連到這些 id，不依賴中文標題自動產生的 id
    converter = markdown.Markdown(extensions=["tables", "fenced_code", "attr_list", "toc", "sane_lists"],
                                  extension_configs={"toc": {"toc_depth": "2-3"}})
    source = shot_to_image((DOCS / f"{name}.md").read_text(encoding="utf-8"))
    body = converter.convert(source)
    body = re.sub(r'src="(images/[^"]+)"', inline_image, body)
    # 文件之間的連結改指向 HTML，在工具裡和直接雙擊開啟都能用
    for other in PAGES:
        body = body.replace(f'href="{other}.md"', f'href="{other}.html"')
    # 搜尋與目錄標示的 script 放在外部檔 manual.js：工具對 HTML 套用 CSP（script-src 'self'），不能 inline
    page = (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{title}</title><style>{tokens()}{LAYOUT_CSS}</style></head><body>"
        f'<header class="topbar"><span class="brand">{title}</span>'
        '<div class="search"><input id="manualSearch" type="search" placeholder="搜尋手冊（按 / 開始）" aria-label="搜尋手冊" autocomplete="off">'
        '<ul id="manualResults" class="results" hidden></ul></div></header>'
        f'{sidebar(converter.toc_tokens)}<main><article id="manualBody">{body}</article></main>'
        '<script src="manual.js"></script></body></html>'
    )
    (ROOT / "app" / f"{name}.html").write_text(page, encoding="utf-8")


def main() -> None:
    for name, title in PAGES.items():
        build(name, title)
    print("完成")


if __name__ == "__main__":
    main()
