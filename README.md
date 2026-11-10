# PDF 解析器

標注一次範本，之後同格式的 PDF 就能批次轉成 Excel。文字層和影像都能讀，有疑慮的值會標記給人確認。全部在本機執行，資料不會離開這台電腦。

| 你是 | 請看 |
|---|---|
| 使用者 | [使用手冊](docs/使用手冊.md)（工具右上角也能開啟） |
| 負責人、接手的人 | [工具卡](OWNER.md) → [維護手冊](docs/maintain.md) → [設計決策](docs/design.md) |
| 要發布新版 | [維護手冊的發布步驟](docs/maintain.md#3-發布新版) 與 [資安檢查清單](docs/security-checklist.md) |

## 使用

不需要先安裝 Python。從共用資料夾取得 `pdf-mapper-版本.zip`，解壓後雙擊 `run.bat`（macOS / Linux 執行 `bash run.sh`）。第一次會自動準備 uv 和 Python，約 1 到 3 分鐘。

之後每次雙擊 `run.bat`，都會先檢查有沒有新版。更新只換掉 `app` 和 `run.bat`，範本與匯出資料不受影響；新版有問題時執行 `run.bat rollback` 就能退回。

```text
pdf-mapper/
  run.bat       入口
  app/          程式，每次更新整包換掉，不要放自己的檔案
  workspace/    範本、匯出結果、客製腳本、操作紀錄（更新不會動）
  runtime/      uv、Python 和套件（自動建立，刪掉會重建）
```

## 三層架構

| 層 | 輸入 | 輸出 | 位置 |
|---|---|---|---|
| 1. 建立範本 | 範例 PDF | 範本 JSON | 網頁工具的「建立範本」 |
| 2. 解析 | PDF + 範本 | Excel + 檢查報告 | 網頁工具的「解析 PDF」或指令列 |
| 3. 客製處理 | 解析結果 | 使用者格式 | `workspace/custom/` 的腳本，本專案只提供接口 |

第 2 層只忠實取值，例如 `1,234.50` 就原樣輸出。轉數字、改欄名都放第 3 層，客戶格式改變時不必重新標注。

## 專案結構

```text
run.bat, run.sh          使用者入口（只有一行，轉給 app/launcher）
app/                     發布時整包給使用者的內容
  launcher.ps1           Windows 啟動程式：環境、檢查更新、回滾
  launcher.sh            macOS / Linux 啟動程式（開發用，不含自動更新）
  pyproject.toml         套件與版本號（版本只寫在這裡）
  uv.lock                鎖定的套件版本
  pdfmapper/
    paths.py             所有檔案位置
    document.py          PDF 讀取，文字層與 OCR 統一成帶座標的字
    ocr.py               OCR 引擎包裝，要換引擎只改這裡
    align.py             用定位點校正位置
    template.py          範本格式、檢查、自動找定位點
    extract.py           取值、切表格、疑點標記
    parser.py            解析主流程與整份驗證
    excel.py             檢查用 Excel
    clean.py             乾淨資料匯出
    postprocess.py       第三層接口
    logs.py              本機日誌
    server.py            本機網頁後端
    web/                 前端，無外部相依
  examples/              示範範本與客製腳本範例，第一次啟動時複製到 workspace
  samples/               虛構範例 PDF
  使用手冊.html           由 docs/使用手冊.md 產生
docs/                    使用手冊、範本格式、設計決策、維護手冊、資安檢查清單
scripts/                 打包發布、重建範例與手冊
tests/
.gitlab-ci.yml           測試、弱點檢查、打包與 Release
OWNER.md                 工具卡：用途、負責人、資料等級、風險分級
CHANGELOG.md             每一版改了什麼（發布時必填）
```

## 開發

```bash
uv sync --project app                                 # 含開發用套件
uv run --project app pytest tests
bash run.sh                                           # 用使用者的方式啟動
uv run --project app python scripts/build_release.py  # 打包到 dist/
```

詳細流程、升級套件與發布步驟見 [維護手冊](docs/maintain.md)。
