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
- [ ] 有 GitLab 專案的 Maintainer 權限，能建立受保護的版本標籤
- [ ] 能寫入發布用的共用資料夾
- [ ] 看過一次 [設計決策](design.md)，特別是「發布、更新與資料夾分工」

## 2. 日常開發

| 要做的事 | 指令 |
|---|---|
| 跑全部測試 | `uv run --project app pytest tests` |
| 只跑一個檔案 | `uv run --project app pytest tests/test_server.py` |
| 用使用者的方式啟動 | `bash run.sh` 或 `run.bat` |
| 重建範例 PDF 與示範範本 | `uv run --project app python scripts/build_demo.py` |
| 改了使用手冊後重建 HTML | `uv run --project app python scripts/build_manual.py` |
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
2. 在 `CHANGELOG.md` 最上面加一段 `## 版本號 - 日期`，用使用者看得懂的話條列改了什麼。這段會顯示在同事的更新提示上。
3. 跑測試，並依 [資安檢查清單](security-checklist.md) 勾選。
4. 合併到 main 後打標籤：

   ```bash
   git tag v0.2.1
   git push origin v0.2.1
   ```

5. GitLab 會自動跑測試、弱點檢查、打包，並建立 Release。任何一步失敗都不會發布。
6. 發布到共用資料夾（見下方）。
7. 通知同事有新版，下次開啟工具時會自動提示。

### 發布到共用資料夾

有設定 `SHARE_PATH` 和能寫入共用資料夾的 runner 時，第 5 步會自動完成。沒有的話手動做：

1. 到 GitLab 的 **Deploy > Releases**，下載 `pdf-mapper-版本.zip` 和 `latest.json`。
2. **先**把 ZIP 複製到共用資料夾。
3. 在 PowerShell 確認雜湊和 `latest.json` 裡的 `sha256` 相同：

   ```powershell
   (Get-FileHash -Algorithm SHA256 \\fileserver\tools\pdf-mapper\pdf-mapper-0.2.1.zip).Hash.ToLower()
   ```

4. **最後**才用新的 `latest.json` 覆蓋舊的。順序反過來的話，同事可能看到新版卻下載不到。

舊版的 ZIP 可以保留幾版，方便查問題；同事只會依 `latest.json` 下載。

### 第一次設定（只做一次）

1. **共用資料夾**：建一個資料夾，例如 `\\fileserver\tools\pdf-mapper\`，設成同事唯讀、只有負責人與備援人可寫入。
2. **GitLab CI/CD 變數**（Settings > CI/CD > Variables）：
   - `PDFMAPPER_UPDATE_SOURCE`：`\\fileserver\tools\pdf-mapper\latest.json`。會寫進發布包，同事從這裡檢查更新。
   - 公司要用內部映像檔或 PyPI 鏡像時，設定 `UV_IMAGE`、`UV_DEFAULT_INDEX`。
3. **受保護的標籤**（Settings > Repository > Protected tags）：保護 `v*`，只允許 Maintainer 建立。這樣只有負責人能發布。
4. **每月排程**（Build > Pipeline schedules）：每月一次，跑在 main。排程時弱點檢查失敗會亮紅燈。
5. **第一次發給同事**：把 ZIP 放到共用資料夾，請大家從那裡複製（不要用 email 附件，Windows 會擋下執行）。

同事如果能直接連到 GitLab 且不需要登入，也可以把 `PDFMAPPER_UPDATE_SOURCE` 設成 Release 裡 `latest.json` 的網址，就不用共用資料夾。

## 4. 例行維護

| 頻率 | 做什麼 |
|---|---|
| 每月 | 看排程 pipeline 的弱點檢查。有弱點就升級該套件並發布修正版 |
| 每季 | 檢視 OWNER.md：還有人在用嗎？負責人、備援人、資料等級有沒有變？更新「最近一次檢視」 |
| 每半年 | 升級全部套件與 uv，發一個小版本 |
| 交接時 | 新負責人照第 1 節做一次，並在備援人陪同下發布一次 |

### 升級套件

```bash
uv lock --project app --upgrade-package pypdfium2     # 只升級一個（處理弱點時）
uv lock --project app --upgrade                       # 全部升級
uv run --project app pytest tests
uv export --project app --frozen --no-dev --no-hashes --no-emit-project -o /tmp/req.txt
uvx pip-audit --disable-pip --no-deps -r /tmp/req.txt # 本機先檢查一次弱點
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

### 安全修正，要所有人立刻更新

1. 照第 3 節發布修正版，發布前把 CI/CD 變數 `PDFMAPPER_MIN_VERSION` 設成這個新版本。
2. 低於這個版本的人開啟工具時，必須更新才能使用。
3. 發布完成後清掉 `PDFMAPPER_MIN_VERSION`，之後的版本才不會都變成必要更新。

### 發現嚴重錯誤，要所有人先停用

直接編輯共用資料夾的 `latest.json`，加上兩個欄位：

```json
"retired": true,
"notes": "發現金額欄位解析錯誤，修正前請改用人工作業"
```

所有人下次開啟時會看到這段說明，工具不會啟動。修正後發布新版，`latest.json` 會被覆蓋，停用自然解除。

### 要讓所有人回到上一版

啟動程式只會往新版更新。把有問題的修改 revert，用新的版本號（例如 0.2.2）發布。

## 7. 資料夾與檔案一覽

| 位置 | 用途 | 進版控 | 進發布包 |
|---|---|---|---|
| `run.bat`、`run.sh` | 使用者入口 | 是 | 是 |
| `app/` | 程式、啟動程式、示範範本、範例 PDF、使用手冊 | 是 | 是（逐一列在 `scripts/build_release.py`） |
| `app/wheels/` | Windows 離線套件 | 否 | 是（CI 打包時下載） |
| `app/update-source.txt` | 更新來源 | 否 | 是（CI 依變數產生） |
| `workspace/` | 使用者資料 | 否 | 否 |
| `runtime/` | uv、Python、套件 | 否 | 否 |
| `app.old/` | 使用者電腦上的上一版 | 否 | 否 |
| `docs/`、`scripts/`、`tests/` | 開發用 | 是 | 否 |
| `dist/` | 打包產物 | 否 | — |
