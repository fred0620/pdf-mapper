"""把 docs/使用手冊.md 轉成單一 HTML（圖片內嵌），放在專案根目錄，雙擊就能看。

需要 markdown 套件，見 requirements-dev.txt。
"""
import base64
import re
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

STYLE = """
:root { --ink:#000; --soft:#565b57; --rule:#c6cac5; --green:#2C5F34; }
body { margin:0; background:#fff; color:var(--ink);
  font:16px/1.75 "Noto Sans TC","PingFang TC","Microsoft JhengHei",Helvetica,sans-serif; }
main { max-width:800px; margin:0 auto; padding:40px 20px 80px; }
.toc { border-top:1.5px solid var(--ink); border-bottom:1px solid var(--ink); padding:10px 0; margin:24px 0; }
.toc ul { list-style:none; margin:0; padding:0; columns:2; }
.toc ul ul { display:none; }
.toc a { color:var(--ink); text-decoration:none; }
.toc a:hover { color:var(--green); text-decoration:underline; }
h1 { font-size:30px; line-height:1.3; margin:0 0 12px; }
h2 { font-size:22px; margin:48px 0 10px; padding-top:8px; border-top:2px solid var(--ink); }
h3 { font-size:17px; margin:30px 0 6px; }
p { margin:10px 0; }
strong { font-weight:700; }
a { color:var(--green); }
img { display:block; max-width:100%; height:auto; margin:14px 0 20px; border:1px solid var(--rule); }
table { width:100%; border-collapse:collapse; margin:14px 0 22px; font-size:15px; }
th { text-align:left; padding:6px 10px 6px 0; border-top:1.5px solid var(--ink); border-bottom:1px solid var(--ink); }
td { text-align:left; padding:6px 10px 6px 0; border-bottom:1px solid #e6e8e5; vertical-align:top; }
tbody tr:last-child td { border-bottom:1.5px solid var(--ink); }
blockquote { margin:16px 0; padding:2px 0 2px 14px; border-left:3px solid var(--green); }
code { background:#f0f1ef; padding:1px 4px; font-size:.9em; font-family:Consolas,Menlo,monospace; }
pre { background:#f0f1ef; padding:12px 14px; overflow-x:auto; }
pre code { background:none; padding:0; }
@media print { h2 { break-after:avoid; } img { break-inside:avoid; } }
"""


def inline_image(match: re.Match) -> str:
    data = base64.b64encode((DOCS / match.group(1)).read_bytes()).decode()
    return f'src="data:image/png;base64,{data}"'


def main() -> None:
    converter = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"],
                                  extension_configs={"toc": {"toc_depth": "2-2"}})
    body = converter.convert((DOCS / "使用手冊.md").read_text(encoding="utf-8"))
    body = re.sub(r'src="(images/[^"]+)"', inline_image, body)
    # 目錄放在開場白之後
    body = body.replace("<h2", f"{converter.toc}<h2", 1)
    page = (
        '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>PDF 解析器使用手冊</title><style>{STYLE}</style></head>"
        f"<body><main>{body}</main></body></html>"
    )
    (ROOT / "使用手冊.html").write_text(page, encoding="utf-8")
    print("完成")


if __name__ == "__main__":
    main()
