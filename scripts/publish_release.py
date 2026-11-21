"""在 GitLab CI 上傳 dist/ 的檔案並建立 Release。

只用 Python 標準函式庫，跟其他 job 共用同一個映像檔，不需要另外從 Docker Hub
或 registry.gitlab.com 拉 curl、release-cli。用 CI_JOB_TOKEN 驗證，不需要另外設定 token。

    python3 scripts/publish_release.py            （只在打標籤的 pipeline 執行）
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
PACKAGE = "pdf-mapper"


def _context() -> ssl.SSLContext:
    # 預設會讀 SSL_CERT_FILE；runner 設了 GitLab 的憑證時一併信任
    context = ssl.create_default_context()
    for name in ("CA_BUNDLE", "CI_SERVER_TLS_CA_FILE"):
        path = os.environ.get(name)
        if path and Path(path).is_file():
            context.load_verify_locations(cafile=path)
    return context


def _request(method: str, url: str, data: bytes | None = None, content_type: str | None = None) -> dict:
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("JOB-TOKEN", os.environ["CI_JOB_TOKEN"])
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, context=_context(), timeout=300) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise SystemExit(f"{method} {url} 失敗：HTTP {exc.code} {detail}") from None
    return json.loads(body) if body.strip().startswith(b"{") else {}


def package_url(version: str, name: str) -> str:
    api = os.environ["CI_API_V4_URL"].rstrip("/")
    project = os.environ["CI_PROJECT_ID"]
    return f"{api}/projects/{project}/packages/generic/{PACKAGE}/{quote(version)}/{quote(name)}"


def release_body(tag: str, version: str) -> dict:
    zip_name = f"{PACKAGE}-{version}.zip"
    return {
        "tag_name": tag,
        "name": f"PDF 解析器 {version}",
        "description": (f"下載 {zip_name} 和 SHA256SUMS.txt，不用解壓，兩個都放進工具資料夾後雙擊 run.bat，"
                        "核對相符就會安裝，範本不受影響。步驟見 ZIP 裡的 app/換版說明.html，更新內容見 CHANGELOG.md。"),
        "assets": {"links": [
            {"name": zip_name, "url": package_url(version, zip_name), "link_type": "package"},
            {"name": "SHA256SUMS.txt", "url": package_url(version, "SHA256SUMS.txt"), "link_type": "other"},
        ]},
    }


def main() -> None:
    tag = os.environ.get("CI_COMMIT_TAG")
    if not tag:
        sys.exit("只在打標籤的 pipeline 發布")
    version = tag.lstrip("v")
    files = sorted(path for path in DIST.iterdir() if path.is_file()) if DIST.is_dir() else []
    if not any(path.name == f"{PACKAGE}-{version}.zip" for path in files):
        sys.exit(f"dist/ 裡沒有 {PACKAGE}-{version}.zip，請先跑打包")
    for path in files:
        print(f"上傳 {path.name}（{path.stat().st_size / 1024 / 1024:.1f} MB）", flush=True)
        _request("PUT", package_url(version, path.name), path.read_bytes(), "application/octet-stream")
    api = os.environ["CI_API_V4_URL"].rstrip("/")
    release = _request("POST", f"{api}/projects/{os.environ['CI_PROJECT_ID']}/releases",
                       json.dumps(release_body(tag, version)).encode("utf-8"), "application/json")
    print(f"已建立 Release {release.get('name', tag)}")


if __name__ == "__main__":
    main()
