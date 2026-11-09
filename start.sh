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
    # 官方 release 的 .sha256；升級 uv 版本時要一起更新，下載內容不符就不執行
    Darwin-arm64) ASSET=uv-aarch64-apple-darwin; SHA=60fbd5c8a1ed681845eea28d9d622fcde03c51e91a43465b64a1e17db1ed3472 ;;
    Darwin-x86_64) ASSET=uv-x86_64-apple-darwin; SHA=63ba17fdda55ad1a230d4b37fc6017ffa10c23688c83818bd3bfdf914c652a02 ;;
    Linux-aarch64) ASSET=uv-aarch64-unknown-linux-gnu; SHA=229e194255c7958d86d56e8790d969a6f74736592133f0dfd0076f754c642c1d ;;
    *) ASSET=uv-x86_64-unknown-linux-gnu; SHA=f29c3e94ffabd7e6f3ba521dba169a9b7ec12100bf3257087f0f24f6123f3645 ;;
  esac
  TEMP="$ROOT/.tools/uv-download"
  rm -rf "$TEMP"; mkdir -p "$TEMP"
  curl -fsSL "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$ASSET.tar.gz" -o "$TEMP/uv.tgz"
  ACTUAL=$( (command -v sha256sum >/dev/null && sha256sum "$TEMP/uv.tgz" || shasum -a 256 "$TEMP/uv.tgz") | cut -d' ' -f1)
  if [ "$ACTUAL" != "$SHA" ]; then
    rm -rf "$TEMP"
    echo "下載的 uv 驗證不符（SHA256 $ACTUAL），可能被竄改或下載不完整" >&2
    exit 1
  fi
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
