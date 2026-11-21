"""單一檔案的處理上限，避免一份異常的 PDF 或範本拖住整批解析。

- 頁數上限：開檔時就檢查，超過直接失敗，不會先吃掉記憶體。
- 時間上限：在頁、欄位、表格之間檢查，超過就中止這份檔案。
- 正規表達式上限：範本裡的寫法一律用 regex 套件執行並設逾時（標準的 re 跑到一半無法打斷）。
  範本儲存時另外擋掉常見的危險寫法（見 template.py），先提醒使用者改寫。
- 渲染上限：單頁點陣圖的像素數有上限，整份文件最多同時保留幾張渲染圖。
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar

import regex

MAX_PAGES = 1000
FILE_SECONDS = 15 * 60       # 掃描檔每頁 OCR 約數秒，留足夠空間給長文件
MAX_RENDER_PIXELS = 40_000_000  # 約 A0 大小 150 dpi；A4 300 dpi 約 870 萬
MAX_CACHED_RENDERS = 6       # 整份文件同時保留的渲染圖數量
REGEX_SECONDS = 1.0          # 單次比對的上限；正常寫法在一格文字上只要幾毫秒

_deadline: ContextVar[tuple[float, float] | None] = ContextVar("pdfmapper_deadline", default=None)  # (期限, 秒數)


class LimitExceeded(Exception):
    """超過處理上限。訊息會直接顯示給使用者。"""


class PatternTimeout(LimitExceeded):
    """範本的正規表達式比對太久。這是範本的問題，每份檔案都會遇到，所以直接停止這份檔案。"""


@contextmanager
def file_deadline(seconds: float | None = None):
    """設定這份檔案的處理期限。外層已經設過時沿用外層，讓多範本比較共用同一個期限。"""
    if _deadline.get() is not None:
        yield
        return
    seconds = FILE_SECONDS if seconds is None else seconds
    token = _deadline.set((time.monotonic() + seconds, seconds))
    try:
        yield
    finally:
        _deadline.reset(token)


def check_deadline() -> None:
    current = _deadline.get()
    if current is not None and time.monotonic() > current[0]:
        raise LimitExceeded(f"處理超過 {_describe_seconds(current[1])}，已停止這份檔案")


def _describe_seconds(seconds: float) -> str:
    return f"{seconds / 60:g} 分鐘" if seconds >= 60 else f"{max(seconds, 0):g} 秒"


def search(pattern: str, text: str, flags: int = 0):
    """執行範本裡的正規表達式。regex 套件的預設語法和 re 相同，但可以設逾時。"""
    try:
        return regex.search(pattern, text, flags, timeout=REGEX_SECONDS)
    except TimeoutError:
        raise PatternTimeout(f"範本的正規表達式「{pattern}」比對超過 {REGEX_SECONDS:g} 秒，已停止這份檔案。"
                             "請到範本把這個寫法改簡單，例如不要在重複的內容裡再放重複") from None


def check_pages(count: int) -> None:
    if count > MAX_PAGES:
        raise LimitExceeded(f"這份 PDF 有 {count} 頁，超過上限 {MAX_PAGES} 頁，請分割後再處理")
