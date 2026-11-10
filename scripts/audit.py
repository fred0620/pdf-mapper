"""檢查套件有沒有已知弱點（發版前、每月在能連到 pypi.org 的電腦執行一次）。

    python3 scripts/audit.py

公司鏡像沒有弱點資料庫，所以這一步不放在 CI。
只檢查同事電腦會安裝的套件（不含開發用的 pytest 等）。
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIP_AUDIT = "pip-audit==2.10.1"


def main() -> int:
    with tempfile.TemporaryDirectory() as folder:
        requirements = Path(folder) / "requirements.txt"
        subprocess.run(["uv", "export", "--project", str(ROOT / "app"), "--frozen", "--no-dev", "--no-hashes",
                        "--no-emit-project", "--quiet", "--output-file", str(requirements)], check=True)
        result = subprocess.run(["uvx", PIP_AUDIT, "--disable-pip", "--no-deps", "--progress-spinner", "off",
                                 "-r", str(requirements)])
    if result.returncode == 0:
        print("沒有已知弱點。")
    else:
        print("\n有弱點或檢查失敗。有弱點時用 uv lock --project app --upgrade-package 套件名稱 升級，"
              "跑完測試後發布修正版。", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
