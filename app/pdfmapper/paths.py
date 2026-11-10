"""所有檔案位置集中在這裡。

發布後的資料夾分成三塊，更新時只換 app/ 和 run.bat：

    pdf-mapper/
      run.bat      使用者入口
      app/         程式（每次更新整包換掉，不要放自己的檔案）
      workspace/   使用者資料：範本、匯出結果、客製腳本、日誌（更新不會動）
      runtime/     uv、Python 與套件（自動建立，可隨時刪掉重建）

啟動腳本會設定 PDFMAPPER_HOME 指向最外層資料夾；沒有設定時（例如開發時直接跑
pytest），就用 app/ 的上一層。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("PDFMAPPER_HOME") or APP.parent).resolve()

WORKSPACE = HOME / "workspace"
TEMPLATES = WORKSPACE / "templates"
OUTPUT = WORKSPACE / "output"
CUSTOM = WORKSPACE / "custom"
LOGS = WORKSPACE / "logs"
UPLOADS = WORKSPACE / "uploads"

EXAMPLES = APP / "examples"
SAMPLES = APP / "samples"
MANUAL = APP / "使用手冊.html"
GUIDES = {"使用手冊.html", "換版說明.html"}  # 工具裡可以開啟的說明文件


def prepare() -> list[str]:
    """建立 workspace，第一次使用時放入示範範本，並搬移舊版資料。回傳要顯示給使用者的訊息。"""
    messages = _migrate_legacy()
    first_time = not TEMPLATES.exists()
    for folder in (TEMPLATES, OUTPUT, CUSTOM, LOGS):
        folder.mkdir(parents=True, exist_ok=True)
    if first_time:
        # 只在第一次建立時放入；使用者自己刪掉示範範本後不會再出現
        for path in sorted((EXAMPLES / "templates").glob("*.json")):
            shutil.copy2(path, TEMPLATES / path.name)
    return messages


def _migrate_legacy() -> list[str]:
    """0.1 版把範本、輸出和客製腳本放在最外層。只複製不刪除，確認後由使用者自行刪掉舊資料夾。"""
    messages: list[str] = []
    moves = (("templates", TEMPLATES, "*.json"), ("custom", CUSTOM, "*.py"))
    for name, target, pattern in moves:
        old = HOME / name
        if not old.is_dir() or old.resolve() == target.resolve():
            continue
        copied = 0
        for path in old.glob(pattern):
            destination = target / path.name
            if destination.exists():
                continue
            target.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            copied += 1
        if copied:
            messages.append(f"已把舊版 {name} 的 {copied} 個檔案複製到 workspace/{name}")
    old_output = HOME / "output"
    if old_output.is_dir() and not OUTPUT.exists():
        WORKSPACE.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_output), str(OUTPUT))
        messages.append("已把舊版 output 搬到 workspace/output")
    return messages
