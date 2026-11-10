"""單一檔案的處理上限，避免一份異常的 PDF 或範本拖住整批解析。

- 頁數上限：開檔時就檢查，超過直接失敗，不會先吃掉記憶體。
- 時間上限：在頁、欄位、表格之間檢查，超過就中止這份檔案。
  單一個正規表達式卡住時無法從中間打斷，所以範本儲存時另外擋掉危險寫法（見 template.py）。
- 渲染上限：單頁點陣圖的像素數有上限，整份文件最多同時保留幾張渲染圖。
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar

MAX_PAGES = 1000
FILE_SECONDS = 15 * 60       # 掃描檔每頁 OCR 約數秒，留足夠空間給長文件
MAX_RENDER_PIXELS = 40_000_000  # 約 A0 大小 150 dpi；A4 300 dpi 約 870 萬
MAX_CACHED_RENDERS = 6       # 整份文件同時保留的渲染圖數量

_deadline: ContextVar[float | None] = ContextVar("pdfmapper_deadline", default=None)


class LimitExceeded(Exception):
    """超過處理上限。訊息會直接顯示給使用者。"""


@contextmanager
def file_deadline(seconds: float | None = None):
    """設定這份檔案的處理期限。外層已經設過時沿用外層，讓多範本比較共用同一個期限。"""
    if _deadline.get() is not None:
        yield
        return
    token = _deadline.set(time.monotonic() + (FILE_SECONDS if seconds is None else seconds))
    try:
        yield
    finally:
        _deadline.reset(token)


def check_deadline() -> None:
    deadline = _deadline.get()
    if deadline is not None and time.monotonic() > deadline:
        raise LimitExceeded(f"處理超過 {FILE_SECONDS // 60} 分鐘，已停止這份檔案")


def check_pages(count: int) -> None:
    if count > MAX_PAGES:
        raise LimitExceeded(f"這份 PDF 有 {count} 頁，超過上限 {MAX_PAGES} 頁，請分割後再處理")
