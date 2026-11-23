"""說明卡的「看手冊」連到使用手冊的明確錨點（docs/使用手冊.md 的 {#id}），每一個都要存在。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "app" / "pdfmapper" / "web"


def test_every_card_manual_anchor_exists():
    anchors = set(re.findall(r'\bmanual:\s*"([\w-]+)"', (WEB / "spotlights.js").read_text(encoding="utf-8")))
    assert {"regex", "format-check", "value-modes", "table-place", "clean-data"} <= anchors
    html = (ROOT / "app" / "使用手冊.html").read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', html))
    assert anchors <= ids, f"手冊 HTML 沒有這些錨點，請重建：{sorted(anchors - ids)}"
    source = (ROOT / "docs" / "使用手冊.md").read_text(encoding="utf-8")
    for anchor in anchors:  # 錨點寫在 Markdown 裡，不依賴中文標題自動產生的 id
        assert re.search(rf"\{{:?\s*#{anchor}\s*\}}", source), anchor
