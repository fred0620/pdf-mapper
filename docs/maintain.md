# 維護手冊

目標：新的負責人照著這份做一次，就能獨立修改、測試和發布。先看 [OWNER.md](../OWNER.md) 了解這個工具的定位。

## 1. 第一次接手

只需要安裝 [uv](https://docs.astral.sh/uv/) 和 Git，不用另外裝 Python。

```bash
git clone <GitLab 專案網址> pdf-mapper
cd pdf-mapper
uv sync --project app                      # 建立開發環境（app/.venv，含測試套件）
uv run --project app pytest tests          # 全部通過才算環境正確，約 4 分鐘
bash run.sh                                # 或 Windows 雙擊 run.bat，用使用者的方式開啟
```

接手時請一併確認：

- [ ] OWNER.md 的負責人與備援人已改成自己
- [ ] 有 GitLab 專案的 Maintainer 權限，能建立版本標籤
- [ ] 看過一次 [設計決策](design.md)，特別是「發布、更新與資料夾分工」

## 2. 日常開發

| 要做的事 | 指令 |
|---|---|
| 跑全部測試 | `uv run --project app pytest tests` |
| 只跑一個檔案 | `uv run --project app pytest tests/test_server.py` |
| 跑畫面測試（用電腦上的 Edge 或 Chrome 實際操作） | `uv run --project app --group ui python scripts/ui_check.py`（跟上次通過時比沒變動就略過，`--force` 一定跑） |
| 用使用者的方式啟動 | `bash run.sh` 或 `run.bat` |
| 重建範例 PDF 與示範範本 | `uv run --project app python scripts/build_demo.py` |
| 改了使用手冊的示意圖 | 改 `scripts/make_manual_figures.py` 後執行它 |
| 改了使用手冊或換版說明後重建 HTML | `uv run --project app python scripts/build_manual.py` |
| 新增套件 | `uv add --project app 套件名稱` |
| 試打包（不含離線套件） | `uv run --project app python scripts/build_release.py` |

規則：

- 程式放 `app/`，使用者資料只能寫到 `workspace/`。新的檔案位置一律加在 `app/pdfmapper/paths.py`。
- `app/` 裡不要放任何真實資料，它會整包發給所有人。
- 改到範本格式時，提高 `template.py` 的 `SCHEMA_VERSION`，並讓新版能讀舊範本。
- 改到解析邏輯時，用自己電腦上的真實樣本跑一次，和上一版的結果比對。真實樣本不進版控。

## 3. 發布新版

### 版本號怎麼訂

| 改了什麼 | 例子 | 版本 |
|---|---|---|
| 修錯、小調整，範本不用改 | 0.2.0 → 0.2.1 | 第三碼 +1 |
| 新功能，舊範本照樣能用 | 0.2.1 → 0.3.0 | 第二碼 +1 |
| 舊範本要重做，或操作方式大改 | 0.3.0 → 1.0.0 | 第一碼 +1 |

### 步驟

1. 改 `app/pyproject.toml` 的 `version`，然後執行 `uv lock --project app` 讓 `uv.lock` 跟著更新。
2. 在 `CHANGELOG.md` 最上面加一段 `## 版本號 - 日期`，用使用者看得懂的話條列改了什麼。
3. 跑測試和弱點檢查（`python3 scripts/audit.py`，要能連到 pypi.org），並依 [發版檢查清單](security-checklist.md) 勾選。
4. 合併到 main 後打標籤：

   ```bash
   git tag v0.2.1
   git push origin v0.2.1
   ```

5. GitLab 會自動跑測試、打包，並在 **Deploy > Releases** 建立 Release。測試或打包失敗都不會發布。
6. 通知同事：到 Releases 頁下載新版 ZIP 和 `SHA256SUMS.txt`，放進工具資料夾，雙擊 `run.bat`。沒有 `SHA256SUMS.txt` 或對不上時，工具不會安裝。可以直接把 CHANGELOG 這一段貼給大家，並附上 [換版說明](換版說明.md) 的連結（工具裡也能從使用手冊連過去）。

### 第一次設定（只做一次）

1. **受保護的標籤**（Settings > Repository > Protected tags）：保護 `v*`，只允許 Maintainer 建立。這樣只有負責人能發布。
2. **同事的權限**：同事要能看到專案的 Releases 頁才能下載，通常給 Reporter 權限即可。
3. **套件來源**：runner 連不到 pypi.org 時，在 Settings > CI/CD > Variables 設定 `PIP_MIRROR`，見下一節。

### CI 在公司網路跑不起來

CI 會在每個 job 開頭先試著連套件來源，連不到就停下來並顯示原因。常見情況：

| 畫面上的訊息 | 原因 | 怎麼做 |
|---|---|---|
| 無法連到套件來源 https://pypi.org/simple | 公司網路擋住外部 PyPI | 向 IT 要「內部 PyPI 鏡像」的網址（Nexus、Artifactory 等，通常以 `/simple` 結尾），新增變數 `PIP_MIRROR` |
| 有設 `PIP_MIRROR`，但出現 certificate、SSL 字樣 | 鏡像用公司自己的憑證 | 向 IT 要公司根憑證（.crt 或 .pem），新增 **File** 類型的變數 `CA_BUNDLE` |
| job 一開始就拉不到映像檔（pull image 失敗） | runner 連不到 ghcr.io | 請 IT 把 `ghcr.io/astral-sh/uv:0.13.6-python3.12-trixie-slim` 放進公司的映像檔庫，再把變數 `UV_IMAGE` 設成內部的位置 |

向 IT 詢問時可以這樣說：「GitLab CI 要安裝 Python 套件，請問公司有沒有 PyPI 的內部鏡像（proxy repository）？網址和憑證是什麼？」

換了來源也不會降低安全性：CI 只安裝和 `uv.lock` 雜湊完全相同的檔案，打包時也會逐一比對。

弱點檢查（pip-audit）不在 CI 裡：它要查 pypi.org 的弱點資料庫，公司鏡像沒有，放在 CI 只會一直失敗。改成發版前和每月在自己的電腦執行 `python3 scripts/audit.py`。

### 在自己的電腦發布（暫時沒有鏡像時）

在能連到 pypi.org 的電腦上：

1. 照上面的步驟 1 到 3 改版本號、寫 CHANGELOG、跑測試，合併到 main。
2. 打包：`uv run --project app python scripts/build_release.py --wheels`，會在 `dist/` 產生 ZIP 和 `SHA256SUMS.txt`。
3. 打標籤並推上去。CI 打包失敗沒關係，標籤本身會留著。
4. 到 **Deploy > Releases > New release**，選剛才的標籤，在 Release notes 貼上 CHANGELOG 這一版的段落。
5. 在 **Release assets** 上傳或連結 `dist/` 裡的兩個檔案。檔名不要改，同事的工具要靠檔名找新版和核對檔。

## 4. 例行維護

| 頻率 | 做什麼 |
|---|---|
| 每月 | 在能連到 pypi.org 的電腦執行 `python3 scripts/audit.py`。有弱點就升級該套件並發布修正版 |
| 每半年 | 升級全部套件與 uv，發一個小版本；順便確認 OWNER.md 還正確、還有人在用 |
| 交接時 | 新負責人照第 1 節做一次，並在備援人陪同下發布一次 |

### 升級套件

```bash
uv lock --project app --upgrade-package pypdfium2     # 只升級一個（處理弱點時）
uv lock --project app --upgrade                       # 全部升級
uv run --project app pytest tests
python3 scripts/audit.py                              # 檢查一次弱點
```

`pypdfium2`（PDFium）和 `pdfplumber` 負責讀取不受信任的 PDF，是最需要跟上更新的套件。

### 升級 uv

1. 到 uv 的 GitHub Release 頁，找新版本的 `.sha256` 檔。
2. 改 `app/launcher.ps1` 的 `$UvVersion` 和 `$UvSha256`，以及 `app/launcher.sh` 的 `UV_VERSION` 和各平台的 `SHA`。
3. 改 `.gitlab-ci.yml` 的 `UV_IMAGE` 版本。
4. 刪掉本機的 `runtime/` 後用 `run.bat` 啟動一次，確認能下載並通過驗證。

### 升級 Python

改 `app/.python-version`，執行 `uv lock --project app`，跑測試，再改 `.gitlab-ci.yml` 的映像檔版本。使用者更新後會自動建立新的環境。

## 5. 使用者回報問題時

請對方提供：

- 版本號（畫面左上角，或 `run.bat version`）
- `workspace/logs/pdfmapper.log`（只有 doc_id 和數量，不含檔名與資料內容）
- 可以的話，一份能重現問題、已去識別化的 PDF

先請對方執行 `run.bat rollback`，確認是不是新版造成的。環境壞掉時，刪除 `runtime` 資料夾重新啟動即可，範本不受影響。

## 6. 緊急處理

### 發現嚴重錯誤

1. 通知所有使用者先暫停使用，改回人工作業。
2. 修正後照第 3 節發布，通知大家更新。
3. 要回到上一版的行為時，把有問題的修改 revert，用新的版本號（例如 0.2.2）發布。安裝程式只會往新版更新。

## 7. 資料夾與檔案一覽

| 位置 | 用途 | 進版控 | 進發布包 |
|---|---|---|---|
| `run.bat`、`run.sh` | 使用者入口 | 是 | 是 |
| `app/` | 程式、啟動程式、示範範本、範例 PDF、使用手冊 | 是 | 是（逐一列在 `scripts/build_release.py`） |
| `app/wheels/` | Windows 離線套件 | 否 | 是（CI 打包時下載） |
| `workspace/` | 使用者資料，第一次啟動時建立 | 否 | 否 |
| `runtime/` | uv、Python、套件 | 否 | 否 |
| `app.old/` | 使用者電腦上的上一版 | 否 | 否 |
| `docs/`、`scripts/`、`tests/` | 開發用 | 是 | 否 |
| `dist/` | 打包產物 | 否 | — |
