"""改了畫面或後端之後跑畫面測試；跟上次通過時比，沒變動就略過。

    uv run --project app --group ui python scripts/ui_check.py          # 有變動才跑
    uv run --project app --group ui python scripts/ui_check.py --force  # 一定跑

也給 Claude Code 的 Stop hook 用（.claude/settings.json）：Claude 一輪修改結束時自動檢查，
失敗就把錯誤交回給 Claude 繼續修，不會在畫面壞掉的狀態下回報完成。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 畫面測試會走過的程式：前端、後端、測試本身。文件和 CI 設定改了不用重跑
WATCHED = [ROOT / "app" / "pdfmapper", ROOT / "tests" / "ui", ROOT / "tests" / "conftest.py",
           ROOT / "scripts" / "make_samples.py"]
STAMP = ROOT / ".pytest_cache" / "ui-check-passed"   # 已在 .gitignore
TAIL_LINES = 60


def fingerprint() -> str:
    digest = hashlib.sha256()
    for base in WATCHED:
        files = [base] if base.is_file() else sorted(p for p in base.rglob("*") if p.is_file())
        for path in files:
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def can_run() -> str | None:
    """回傳不能跑的原因；能跑就回傳 None。"""
    try:
        import playwright  # noqa: F401
    except ImportError:
        return "沒有安裝 playwright（uv sync --project app --group ui），略過畫面測試"
    return None


def run_tests() -> tuple[bool, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:logging", "tests/ui"],
                          cwd=ROOT, capture_output=True, text=True)
    output = (proc.stdout + proc.stderr).strip().splitlines()
    skipped_all = proc.returncode == 0 and " passed" not in (output[-1] if output else "")
    if skipped_all:  # 找不到瀏覽器時整組跳過，不能當成通過
        return True, "畫面測試整組跳過（找不到 Edge 或 Chrome），沒有實際檢查"
    return proc.returncode == 0, "\n".join(output[-TAIL_LINES:])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="沒有變動也跑")
    parser.add_argument("--hook", action="store_true", help="給 Claude Code 的 Stop hook 用")
    args = parser.parse_args()
    hook_input = {}
    if args.hook and not sys.stdin.isatty():
        try:
            hook_input = json.loads(sys.stdin.read() or "{}")
        except json.JSONDecodeError:
            hook_input = {}

    current = fingerprint()
    if not args.force and STAMP.exists() and STAMP.read_text().strip() == current:
        print("畫面相關的程式沒有變動，略過畫面測試")
        return 0
    reason = can_run()
    if reason:
        print(reason)
        return 0
    passed, report = run_tests()
    if passed:
        STAMP.parent.mkdir(exist_ok=True)
        STAMP.write_text(current)
        print(report.splitlines()[-1] if report else "畫面測試通過")
        return 0
    message = "畫面測試沒有通過，請修正後再回報完成：\n" + report
    if args.hook:
        if hook_input.get("stop_hook_active"):
            # 已經因為這個 hook 繼續修過一次還是失敗：不再擋，交給使用者判斷，避免無限循環
            print(json.dumps({"systemMessage": "畫面測試仍未通過，請查看 scripts/ui_check.py 的輸出"}, ensure_ascii=False))
            return 0
        print(message, file=sys.stderr)
        return 2  # Stop hook 回傳 2：擋下結束，把 stderr 交給 Claude
    print(message)
    return 1


if __name__ == "__main__":
    sys.exit(main())
