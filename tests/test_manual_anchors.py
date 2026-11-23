"""說明卡與實地練習的「看手冊」連到使用手冊的明確錨點（docs/使用手冊.md 的 {#id}），每一個都要存在。"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "app" / "pdfmapper" / "web"
LABS = ROOT / "app" / "pdfmapper" / "demo" / "labs.json"

# 改版前就連出去的錨點（書籤、舊版說明卡），改寫手冊時不能消失
KEPT = {"pos-field", "table", "checks", "output", "run", "two-windows", "multi-template", "clean-data",
        "flags", "advanced", "regex", "format-check", "value-modes", "table-place", "column-preview"}


def _card_anchors() -> set[str]:
    anchors = set(re.findall(r'\bmanual:\s*"([\w-]+)"', (WEB / "spotlights.js").read_text(encoding="utf-8")))
    labs = json.loads(LABS.read_text(encoding="utf-8"))
    return anchors | {lab["manual"] for lab in labs.values() if lab.get("manual")}


def test_every_card_manual_anchor_exists():
    anchors = _card_anchors()
    assert {"regex", "format-check", "cell-extract", "cross-page", "header", "endmark", "clean-data", "inline-edit"} <= anchors
    html = (ROOT / "app" / "使用手冊.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    assert anchors | KEPT <= ids, f"手冊 HTML 沒有這些錨點，請重建：{sorted((anchors | KEPT) - ids)}"
    source = (ROOT / "docs" / "使用手冊.md").read_text(encoding="utf-8")
    for anchor in anchors | KEPT | {"ai"}:  # 錨點寫在 Markdown 裡，不依賴中文標題自動產生的 id
        assert re.search(rf"\{{:?\s*#{anchor}\s*\}}", source), anchor


def test_manual_internal_links_resolve():
    html = (ROOT / "app" / "使用手冊.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    links = set(re.findall(r'href="#([^"]+)"', html))
    assert links <= ids, sorted(links - ids)
