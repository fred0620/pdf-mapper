"""程式指紋（build id）：偵測執行中的伺服器與硬碟上的程式是否一致。只用標準函式庫。"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

_cache_lock = threading.Lock()
_cache: dict[str, object] = {"key": None, "value": None}


def _iter_files(base: Path) -> list[Path]:
    """收集 app/pdfmapper/ 下的 *.py、web/**、demo/**/*.json（排除 __pycache__），依相對路徑排序。"""
    found: dict[str, Path] = {}
    candidates: list[Path] = []
    candidates.extend(base.rglob("*.py"))
    web_dir = base / "web"
    if web_dir.is_dir():
        candidates.extend(web_dir.rglob("*"))
    demo_dir = base / "demo"
    if demo_dir.is_dir():
        candidates.extend(demo_dir.rglob("*.json"))
    for path in candidates:
        if not path.is_file():
            continue
        rel = path.relative_to(base)
        if "__pycache__" in rel.parts or path.suffix == ".pyc":
            continue
        found[rel.as_posix()] = path
    return [found[key] for key in sorted(found)]


def compute_build_id(base: Path | None = None) -> str:
    """對核心程式、前端檔案與示範設定計算 SHA256，取前 12 碼。"""
    root = (base or PACKAGE_DIR).resolve()
    digest = hashlib.sha256()
    for path in _iter_files(root):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:12]


def disk_build(base: Path | None = None) -> str:
    """回傳目前硬碟上的程式指紋。以檔案數量與 mtime 總和快取，沒變動就不重讀檔案。"""
    override = os.environ.get("PDFMAPPER_BUILD_OVERRIDE")
    if override:
        return override
    root = (base or PACKAGE_DIR).resolve()
    files = _iter_files(root)
    mtime_sum = 0
    for path in files:
        try:
            mtime_sum += path.stat().st_mtime_ns
        except OSError:
            continue
    key = (root, len(files), mtime_sum)
    with _cache_lock:
        if _cache["key"] == key and isinstance(_cache["value"], str):
            return _cache["value"]
    value = compute_build_id(root)
    with _cache_lock:
        _cache["key"] = key
        _cache["value"] = value
    return value


RUNNING_BUILD = compute_build_id()
