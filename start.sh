#!/usr/bin/env bash
# macOS / Linux 啟動腳本
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  PY=$(command -v python3 || command -v python) || { echo "請先安裝 Python 3.10 以上版本"; exit 1; }
  "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "需要 Python 3.10 以上版本"; exit 1; }
  [ -x .venv/bin/python ] || "$PY" -m venv .venv
  echo "正在安裝套件，約需 1 到 3 分鐘..."
  if [ -d wheels ]; then
    .venv/bin/python -m pip install --quiet --no-index --find-links wheels -r requirements.txt
  else
    .venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt
  fi
  touch .venv/.installed
fi
exec .venv/bin/python -m pdfmapper "$@"
