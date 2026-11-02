#!/usr/bin/env bash
# macOS / Linux 啟動腳本。uv、Python 和套件都放在這個資料夾內，不動系統環境。
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8

UV_VERSION=0.13.6
ROOT=$(pwd)
UV="$ROOT/.tools/uv/uv"
export UV_PYTHON_INSTALL_DIR="$ROOT/.tools/python"
export UV_CACHE_DIR="$ROOT/.tools/cache"
export UV_SYSTEM_CERTS=1
export UV_PYTHON_PREFERENCE=only-managed
export UV_NO_PROGRESS=1

if [ ! -x "$UV" ]; then
  echo "第一次使用，正在下載 uv..."
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) ASSET=uv-aarch64-apple-darwin ;;
    Darwin-x86_64) ASSET=uv-x86_64-apple-darwin ;;
    Linux-aarch64) ASSET=uv-aarch64-unknown-linux-gnu ;;
    *) ASSET=uv-x86_64-unknown-linux-gnu ;;
  esac
  TEMP="$ROOT/.tools/uv-download"
  rm -rf "$TEMP"; mkdir -p "$TEMP"
  curl -fsSL "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$ASSET.tar.gz" -o "$TEMP/uv.tgz"
  tar xzf "$TEMP/uv.tgz" -C "$TEMP"
  rm -rf "$ROOT/.tools/uv"
  mv "$TEMP/$ASSET" "$ROOT/.tools/uv"
  rm -rf "$TEMP"
fi

[ -x .venv/bin/python ] || echo "正在準備 Python 與套件，第一次約需 1 到 3 分鐘..."
if [ -d wheels ]; then
  # 離線安裝：Python 和套件都來自複製過來的檔案，不連網
  export UV_OFFLINE=1
  .venv/bin/python -c pass 2>/dev/null || "$UV" venv --clear .venv
  "$UV" pip install --python .venv/bin/python --no-index --find-links wheels -r wheels/requirements.txt
else
  # 環境已經正確時，這一步會在一瞬間結束，也不需要連網
  "$UV" sync --frozen --no-dev
fi
exec .venv/bin/python -m pdfmapper "$@"
