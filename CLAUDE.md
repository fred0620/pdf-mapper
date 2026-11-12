# 給 Claude 的工作規則

- 回覆一律用台灣繁體中文；文件與訊息不要用破折號。
- 設計決策寫在 `docs/design.md`，改變決策時一起更新，commit 說明原因。
- 改了 `app/pdfmapper/`（前端或後端）、`tests/ui/` 或 `scripts/make_samples.py`，回報完成前要跑畫面測試：
  `uv run --project app --group ui python scripts/ui_check.py`
  只在一輪修改告一段落時跑一次（約 1 分鐘），不用每改一個檔案就跑；跟上次通過時比沒有變動會自動略過。
  `.claude/settings.json` 的 Stop hook 也會在每輪結束時自動跑，沒過會把錯誤交回來繼續修。
- 畫面測試沒過不能回報完成；找不到瀏覽器而整組跳過時，要在回報裡說明沒有實際檢查。
- 新功能或修 bug 時，同時在 `tests/ui` 補上對應的操作測試。儲存格可以有多行，能修改的地方都要測多行。
- 頁面的 CSP 不允許 eval，畫面測試的等待條件用 `expect`，不用 `wait_for_function`。
