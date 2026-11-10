"""PDF 解析器：範本標注、範本解析、Excel 輸出。"""
import re
from pathlib import Path


def _read_version() -> str:
    """版本只寫在 pyproject.toml 一個地方，啟動腳本、CI 和程式都讀同一份。"""
    try:
        text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


__version__ = _read_version()
