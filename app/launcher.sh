#!/usr/bin/env bash
# macOS / Linux 啟動程式，由最外層的 run.sh 呼叫。主要給開發與測試用，
# 自動更新只在 Windows 版（launcher.ps1）提供。
# 用法：bash run.sh [run ... | doctor | version]
set -euo pipefail
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$APP_DIR")"
cd "$ROOT"

UV_VERSION=0.13.6
RUNTIME="$ROOT/runtime"
UV="$RUNTIME/uv/uv"
VENV="$RUNTIME/venv"
export PYTHONIOENCODING=utf-8
export PDFMAPPER_HOME="$ROOT"
export PYTHONPATH="$APP_DIR"
export UV_PYTHON_INSTALL_DIR="$RUNTIME/python"
export UV_CACHE_DIR="$RUNTIME/cache"
export UV_PROJECT_ENVIRONMENT="$VENV"
export UV_SYSTEM_CERTS=1
export UV_PYTHON_PREFERENCE=only-managed
export UV_NO_PROGRESS=1

if [ "${1:-}" = "version" ]; then
  sed -n 's/^version *= *"\(.*\)"/\1/p' "$APP_DIR/pyproject.toml"
  exit 0
fi

if [ ! -x "$UV" ]; then
  echo "第一次使用，正在下載 uv..."
  case "$(uname -s)-$(uname -m)" in
    # 官方 release 的 .sha256；升級 uv 版本時要一起更新，下載內容不符就不執行
    Darwin-arm64) ASSET=uv-aarch64-apple-darwin; SHA=60fbd5c8a1ed681845eea28d9d622fcde03c51e91a43465b64a1e17db1ed3472 ;;
    Darwin-x86_64) ASSET=uv-x86_64-apple-darwin; SHA=63ba17fdda55ad1a230d4b37fc6017ffa10c23688c83818bd3bfdf914c652a02 ;;
    Linux-aarch64) ASSET=uv-aarch64-unknown-linux-gnu; SHA=229e194255c7958d86d56e8790d969a6f74736592133f0dfd0076f754c642c1d ;;
    *) ASSET=uv-x86_64-unknown-linux-gnu; SHA=f29c3e94ffabd7e6f3ba521dba169a9b7ec12100bf3257087f0f24f6123f3645 ;;
  esac
  TEMP="$RUNTIME/uv-download"
  rm -rf "$TEMP"; mkdir -p "$TEMP"
  curl -fsSL "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$ASSET.tar.gz" -o "$TEMP/uv.tgz"
  ACTUAL=$( (command -v sha256sum >/dev/null && sha256sum "$TEMP/uv.tgz" || shasum -a 256 "$TEMP/uv.tgz") | cut -d' ' -f1)
  if [ "$ACTUAL" != "$SHA" ]; then
    rm -rf "$TEMP"
    echo "下載的 uv 驗證不符（SHA256 $ACTUAL），可能被竄改或下載不完整" >&2
    exit 1
  fi
  tar xzf "$TEMP/uv.tgz" -C "$TEMP"
  rm -rf "$RUNTIME/uv"
  mv "$TEMP/$ASSET" "$RUNTIME/uv"
  rm -rf "$TEMP"
fi

# 資料夾搬過位置時，舊環境無法使用，重建即可
if [ -e "$VENV/bin/python" ] && ! "$VENV/bin/python" -c pass 2>/dev/null; then rm -rf "$VENV"; fi
[ -x "$VENV/bin/python" ] || echo "正在準備 Python 與套件，第一次約需 1 到 3 分鐘..."
# app/wheels 是給 Windows 的離線套件，這裡一律依 uv.lock 安裝
"$UV" sync --frozen --no-dev --project "$APP_DIR"
# -P：不把目前資料夾加進模組搜尋路徑
exec "$VENV/bin/python" -P -m pdfmapper "$@"
