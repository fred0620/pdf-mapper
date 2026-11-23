"""手冊的建置：截圖、內嵌圖片、CSP 與提問範本和手冊一致。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD = (ROOT / "docs" / "使用手冊.md").read_text(encoding="utf-8")
HTML = (ROOT / "app" / "使用手冊.html").read_text(encoding="utf-8")
SHOTS = re.findall(r"<!--\s*shot:\s*([\w-]+)\s*-->", MD)


def test_every_shot_marker_has_a_generated_image_embedded_in_html():
    assert len(SHOTS) == 10
    for code in SHOTS:
        path = ROOT / "docs" / "images" / f"shot-{code}.png"
        assert path.is_file() and 2_000 < path.stat().st_size < 80_000, code
    assert "<!-- shot" not in HTML
    assert HTML.count('src="data:image/png;base64,') >= len(SHOTS)
    assert 'alt="加總對不上時提醒我"' in HTML  # alt 用該節標題


def test_html_works_under_tool_csp_and_stays_small():
    scripts = re.findall(r"<script\b([^>]*)>", HTML)
    assert scripts == [' src="manual.js"'], "CSP 不允許 inline script，要放在 manual.js"
    assert (ROOT / "app" / "manual.js").is_file()
    assert len(HTML.encode()) < 1_200_000
    assert "var(--text-strong)" in HTML and "--accent: #3b82f6" in HTML  # token 從工具 style.css 複製


def test_manual_js_is_served_and_whitelisted():
    from pdfmapper import server

    response = server.app.test_client().get("/docs/manual.js")
    assert response.status_code == 200 and "javascript" in response.mimetype


def test_ai_prompt_templates_match_manual_chapter_5():
    js = (ROOT / "app" / "pdfmapper" / "web" / "spotlights.js").read_text(encoding="utf-8")
    block = js[js.index("const AI_PROMPT_EXTRACT"):js.index("const AI_TOOL_RULES")]
    for line in re.findall(r'^\s+"(.+)",?$', block, re.M):
        if line.startswith("- "):
            continue  # 規則清單在手冊是條列，字句略有不同
        assert line in MD, f"手冊第 5 章沒有這句提問範本：{line}"
