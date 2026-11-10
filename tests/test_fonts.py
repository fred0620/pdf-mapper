"""內附的字型子集要涵蓋範例和測試畫出來的每個字，缺字會畫成方框。"""
from pathlib import Path

import make_samples

ROOT = Path(__file__).resolve().parent.parent


def test_bundled_font_covers_sample_text():
    source = (ROOT / "scripts" / "make_samples.py").read_text(encoding="utf-8")
    source += "".join(path.read_text(encoding="utf-8") for path in (ROOT / "tests").glob("*.py")
                      if path.name != "test_fonts.py" and "make_samples" in path.read_text(encoding="utf-8"))
    font = make_samples.load_font(str(make_samples.BUNDLED_FONT), 24)
    tofu = bytes(font.getmask(""))  # 私用區的字一定沒收錄，畫出來就是缺字符號
    missing = "".join(sorted(char for char in {c for c in source if ord(c) > 0x7e}
                             if char.isprintable() and bytes(font.getmask(char)) == tofu))
    assert not missing, f"字型缺這些字，請照 tests/fonts/README.md 重新裁切：{missing}"


def test_missing_glyph_is_detected():
    font = make_samples.load_font(str(make_samples.BUNDLED_FONT), 24)
    assert bytes(font.getmask("鬱")) == bytes(font.getmask(""))  # 子集沒有的字
    assert bytes(font.getmask("項")) != bytes(font.getmask(""))
