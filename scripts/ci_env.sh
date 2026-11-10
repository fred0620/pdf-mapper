# CI 共用設定，每個 job 開始時用 `. scripts/ci_env.sh` 載入。
#
# 選用的 CI/CD 變數（Settings > CI/CD > Variables）：
#   PIP_MIRROR   公司內部 PyPI 鏡像，例如 https://nexus.example.com/repository/pypi/simple
#                runner 連不到 pypi.org 時一定要設。所有套件改從這裡下載，仍然逐一比對 uv.lock 的 SHA256
#   CA_BUNDLE    公司憑證（類型選 File）。鏡像或 GitLab 用公司自己的憑證時才需要
#
# 設定後會先試著連一次套件來源，連不到就停下來，並說明要找誰、設什麼。

if [ -n "${PIP_MIRROR:-}" ]; then
  export UV_DEFAULT_INDEX="$PIP_MIRROR"   # uv 安裝、解析套件
  export PIP_INDEX_URL="$PIP_MIRROR"      # 打包時的 pip download
  PACKAGE_SOURCE="$PIP_MIRROR"
else
  PACKAGE_SOURCE="https://pypi.org/simple"
fi

for ca in "${CA_BUNDLE:-}" "${CI_SERVER_TLS_CA_FILE:-}"; do
  if [ -n "$ca" ] && [ -f "$ca" ]; then
    export SSL_CERT_FILE="$ca" PIP_CERT="$ca" REQUESTS_CA_BUNDLE="$ca"
    break
  fi
done

if ! python3 - "$PACKAGE_SOURCE" <<'EOF'
import sys
import urllib.request

url = sys.argv[1].rstrip("/") + "/six/"
try:
    urllib.request.urlopen(url, timeout=20).close()
except Exception as exc:  # noqa: BLE001
    print(f"連線失敗：{type(exc).__name__}: {exc}")
    sys.exit(1)
EOF
then
  echo ""
  echo "無法連到套件來源 $PACKAGE_SOURCE"
  if [ -z "${PIP_MIRROR:-}" ]; then
    echo "公司網路擋住 pypi.org 時，請向 IT 要內部 PyPI 鏡像的網址（Nexus、Artifactory 等，通常以 /simple 結尾），"
    echo "到 Settings > CI/CD > Variables 新增變數 PIP_MIRROR。"
  else
    echo "請確認 PIP_MIRROR 的網址正確；若出現憑證錯誤，請向 IT 要公司憑證，新增 File 類型的變數 CA_BUNDLE。"
  fi
  echo "暫時拿不到鏡像時，可以照 docs/maintain.md「在自己的電腦發布」手動發布。"
  exit 1
fi
echo "套件來源：$PACKAGE_SOURCE"
