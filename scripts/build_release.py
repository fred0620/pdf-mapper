"""打包發布用的 ZIP，並產生 latest.json 給啟動程式檢查更新。

    uv run --project app python scripts/build_release.py                  只打包程式（測試用）
    uv run --project app python scripts/build_release.py --wheels         附上 Windows 離線套件（正式發布）

輸出到 dist/：
    pdf-mapper-<版本>.zip   解壓後是 run.bat、run.sh 和 app/，不含 workspace 與 runtime
    latest.json             版本、檔名、SHA256、更新說明，啟動程式靠它判斷要不要更新
    SHA256SUMS.txt

只打包明確列出的檔案，測試、腳本、開發文件和任何資料都不會進到發布包。
版本號只寫在 app/pyproject.toml；CHANGELOG.md 一定要有這個版本的段落，否則不給發布。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
NAME = "pdf-mapper"
TOP_FILES = ["run.bat", "run.sh"]
APP_FILES = ["launcher.ps1", "launcher.sh", "pyproject.toml", "uv.lock", ".python-version", "使用手冊.html"]
APP_DIRS = ["pdfmapper", "examples", "samples"]
SKIP = {"__pycache__", ".DS_Store"}
WINDOWS_TEXT = {".bat", ".cmd", ".ps1"}
WINDOWS_PLATFORM = ("x86_64-pc-windows-msvc", "win_amd64")


def read_version() -> str:
    text = (APP / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', text, re.MULTILINE)
    if not match:
        sys.exit("app/pyproject.toml 的版本號要是 x.y.z 格式")
    return match.group(1)


def release_notes(version: str) -> str:
    """取 CHANGELOG.md 裡這個版本的條列，合成一行，顯示在更新提示上。"""
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[?{re.escape(version)}\]?.*?$(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        sys.exit(f"CHANGELOG.md 沒有 {version} 的段落，請先寫好這版改了什麼")
    items = [line.strip()[2:].strip() for line in match.group(1).splitlines() if line.strip().startswith("- ")]
    if not items:
        sys.exit(f"CHANGELOG.md 的 {version} 段落沒有任何條列")
    return "；".join(items)


def check_tag(version: str) -> None:
    tag = os.environ.get("CI_COMMIT_TAG")
    if tag and tag.lstrip("v") != version:
        sys.exit(f"標籤 {tag} 和 app/pyproject.toml 的版本 {version} 不一致")


def copy_tree(source: Path, target: Path) -> None:
    for path in sorted(source.rglob("*")):
        if any(part in SKIP for part in path.relative_to(source).parts) or path.suffix == ".pyc":
            continue
        destination = target / path.relative_to(source)
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)


def normalize_newlines(path: Path) -> None:
    """不管在哪個系統打包，Windows 腳本都用 CRLF，shell 腳本都用 LF。"""
    data = path.read_bytes().replace(b"\r\n", b"\n")
    if path.suffix in WINDOWS_TEXT:
        data = data.replace(b"\n", b"\r\n")
    path.write_bytes(data)


def run(command: list[str]) -> None:
    print("  $", " ".join(command), flush=True)
    subprocess.run(command, check=True, cwd=ROOT)


def download_wheels(target: Path) -> None:
    """下載 Windows 64 位元、對應 Python 版本的套件檔，版本完全依照 uv.lock。"""
    python_version = (APP / ".python-version").read_text(encoding="utf-8").strip()
    target.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as temp:
        universal = Path(temp) / "universal.txt"
        run(["uv", "export", "--project", str(APP), "--frozen", "--no-dev", "--no-hashes",
             "--no-emit-project", "--quiet", "--output-file", str(universal)])
        requirements = target / "requirements.txt"
        # 依 Windows 的條件挑出要用的套件；全部都已鎖版本，不會解出不同的版本
        run(["uv", "pip", "compile", str(universal), "--python-platform", WINDOWS_PLATFORM[0],
             "--python-version", python_version, "--no-header", "--no-annotate", "--quiet",
             "--output-file", str(requirements)])
        run(["uv", "run", "--no-project", "--with", "pip", "python", "-m", "pip", "download",
             "--quiet", "--disable-pip-version-check", "--no-deps", "--only-binary=:all:",
             "--platform", WINDOWS_PLATFORM[1], "--python-version", python_version,
             "--implementation", "cp", "-r", str(requirements), "-d", str(target)])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_zip(stage: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(stage.rglob("*")):
            if path.is_dir():
                continue
            name = f"{stage.name}/{path.relative_to(stage).as_posix()}"
            info = zipfile.ZipInfo(name, date_time=time.localtime(path.stat().st_mtime)[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if path.suffix == ".sh" else 0o644) << 16
            bundle.writestr(info, path.read_bytes())


def build(out: Path, wheels: bool, update_source: str | None, min_version: str | None) -> Path:
    version = read_version()
    check_tag(version)
    notes = release_notes(version)
    stage = out / f"{NAME}-{version}"
    shutil.rmtree(out, ignore_errors=True)
    (stage / "app").mkdir(parents=True)

    for name in TOP_FILES:
        shutil.copy2(ROOT / name, stage / name)
    for name in APP_FILES:
        shutil.copy2(APP / name, stage / "app" / name)
    for name in APP_DIRS:
        copy_tree(APP / name, stage / "app" / name)
    if update_source:
        (stage / "app" / "update-source.txt").write_text(
            "# 啟動時從這裡檢查新版（latest.json 的網址或共用資料夾路徑）\n" + update_source + "\n", encoding="utf-8")
    for path in stage.rglob("*"):
        if path.is_file() and path.suffix in WINDOWS_TEXT | {".sh"}:
            normalize_newlines(path)
    if wheels:
        print("下載 Windows 離線套件...")
        download_wheels(stage / "app" / "wheels")

    archive = out / f"{stage.name}.zip"
    write_zip(stage, archive)
    digest = sha256(archive)
    latest = {"version": version, "file": archive.name, "sha256": digest, "notes": notes,
              "released": time.strftime("%Y-%m-%d")}
    if min_version:
        latest["min_version"] = min_version
    (out / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    shutil.rmtree(stage)
    size = archive.stat().st_size / 1024 / 1024
    print(f"完成：{archive}（{size:.1f} MB）\nSHA256 {digest}")
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default=str(ROOT / "dist"))
    parser.add_argument("--wheels", action="store_true", help="附上 Windows 離線套件，使用者不需要連到 PyPI")
    parser.add_argument("--update-source", default=os.environ.get("PDFMAPPER_UPDATE_SOURCE"),
                        help="使用者檢查更新的位置：latest.json 的網址或共用資料夾路徑")
    parser.add_argument("--min-version", default=os.environ.get("PDFMAPPER_MIN_VERSION"),
                        help="低於這個版本的使用者必須更新（有安全修正時設定）")
    args = parser.parse_args()
    build(Path(args.out), args.wheels, args.update_source, args.min_version)


if __name__ == "__main__":
    main()
