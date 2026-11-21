"""發版前檢查新功能導覽（app/pdfmapper/web/whatsnew.json）。

    python3 scripts/check_whatsnew.py

沿用「CHANGELOG 沒有這一版就不能發布」的做法：
- whatsnew.json 一定要有 app/pyproject.toml 這個版本的條目（沒有使用者看得到的改變就寫 "items": []）
- 每一項的 spotlight 要存在於 spotlights.js，導覽才指得到
- 標題 16 字、說明 40 字以內，長的說明放使用手冊
只用標準函式庫，CI 映像檔與打包腳本都能直接執行。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "app" / "pdfmapper" / "web"
TITLE_MAX = 16
BODY_MAX = 40


def read_version(pyproject: Path) -> str:
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise ValueError("app/pyproject.toml 找不到版本號")
    return match.group(1)


def spotlight_ids(source: Path) -> set[str]:
    """spotlights.js 裡每個步驟都寫成 id: "..."。"""
    return set(re.findall(r'\bid:\s*"([\w.-]+)"', source.read_text(encoding="utf-8")))


def check(whatsnew: Path, version: str, spotlights: Path) -> list[str]:
    try:
        data = json.loads(whatsnew.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"無法讀取 {whatsnew.name}：{exc}"]
    versions = data.get("versions") if isinstance(data, dict) else None
    if not isinstance(versions, list):
        return [f"{whatsnew.name} 要有 versions 清單"]
    errors: list[str] = []
    known = spotlight_ids(spotlights)
    seen_versions: set[str] = set()
    seen_items: set[str] = set()
    for entry in versions:
        name = entry.get("version") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not re.fullmatch(r"\d+\.\d+\.\d+", name):
            errors.append(f"版本號格式不對：{name!r}")
            continue
        if name in seen_versions:
            errors.append(f"{name} 重複出現")
        seen_versions.add(name)
        items = entry.get("items")
        if not isinstance(items, list):
            errors.append(f"{name} 的 items 要是清單（沒有可見改變就寫 []）")
            continue
        for item in items:
            if not isinstance(item, dict):
                errors.append(f"{name} 有一項格式不對")
                continue
            label = item.get("id") or item.get("title") or "?"
            for key in ("id", "title", "body", "spotlight"):
                if not isinstance(item.get(key), str) or not item[key]:
                    errors.append(f"{name}「{label}」缺少 {key}")
            if item.get("id") in seen_items:
                errors.append(f"{name}「{label}」的 id 重複")
            seen_items.add(item.get("id"))
            if isinstance(item.get("title"), str) and len(item["title"]) > TITLE_MAX:
                errors.append(f"{name}「{label}」標題超過 {TITLE_MAX} 字")
            if isinstance(item.get("body"), str) and len(item["body"]) > BODY_MAX:
                errors.append(f"{name}「{label}」說明超過 {BODY_MAX} 字，長的說明放使用手冊")
            if item.get("tab") not in (None, "train", "run"):
                errors.append(f"{name}「{label}」的 tab 只能是 train 或 run")
            if isinstance(item.get("spotlight"), str) and item["spotlight"] not in known:
                errors.append(f"{name}「{label}」的 spotlight「{item['spotlight']}」不在 spotlights.js")
    if version not in seen_versions:
        errors.append(f"{whatsnew.name} 沒有 {version} 的條目，請寫這版使用者看得到的改變（沒有就寫 \"items\": []）")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", type=Path, default=WEB / "whatsnew.json")
    parser.add_argument("--spotlights", type=Path, default=WEB / "spotlights.js")
    parser.add_argument("--version", help="要檢查的版本，預設讀 app/pyproject.toml")
    args = parser.parse_args(argv)
    version = args.version or read_version(ROOT / "app" / "pyproject.toml")
    errors = check(args.file, version, args.spotlights)
    if errors:
        print("新功能導覽檢查沒有通過：", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"新功能導覽有 {version} 的條目")
    return 0


if __name__ == "__main__":
    sys.exit(main())
