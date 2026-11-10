"""本機日誌：只記錄操作與錯誤，方便排查問題。

原則：
- 不記錄 PDF 內容、抓到的值和檔名，檔案一律用 doc_id 代表。
- 只寫到本機 workspace/logs，依大小輪替，不會無限增長。
- 主控台只顯示啟動與關閉訊息，不逐筆列出請求。
"""
from __future__ import annotations

import logging
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = "pdfmapper"
MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 5
RETENTION_DAYS = 30
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

log = logging.getLogger(LOGGER_NAME)


def clean(text: object, limit: int = 120) -> str:
    """寫進日誌的外部字串去掉換行與控制字元，避免偽造日誌行。"""
    return _CONTROL.sub(" ", str(text))[:limit]


def _purge_old(folder: Path) -> None:
    cutoff = time.time() - RETENTION_DAYS * 86400
    for path in folder.glob("pdfmapper.log*"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def setup(folder: Path, level: int = logging.INFO) -> None:
    """設定一次即可，重複呼叫不會重複寫入。"""
    if any(getattr(h, "_pdfmapper", False) for h in log.handlers):
        return
    folder.mkdir(parents=True, exist_ok=True)
    _purge_old(folder)
    handler = RotatingFileHandler(folder / "pdfmapper.log", maxBytes=MAX_BYTES,
                                  backupCount=BACKUP_COUNT, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    handler._pdfmapper = True  # type: ignore[attr-defined]
    log.addHandler(handler)
    log.setLevel(level)
    log.propagate = False
    # Werkzeug 預設把每個請求印到主控台，內容沒有幫助又會蓋掉啟動訊息
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
