# 範本 JSON 格式

一種單據版本對應一份範本。所有位置都是佔頁面的比例（0 到 1），格式為 `[左, 上, 右, 下]`。

```json
{
  "schema_version": 1,
  "template_id": "customs_v1",
  "name": "進口報單",
  "anchors": [],
  "fields": [],
  "tables": [],
  "validations": []
}
```

## 頁面規則 `page_rule`

`first` 第一頁、`rest` 第二頁起、`last` 最後一頁、`all` 每一頁、`page:3` 指定頁。

## 定位點 `anchors`

| 鍵 | 說明 |
|---|---|
| `id` | 唯一代號 |
| `text` | 比對文字，影像比對失敗時才用 |
| `box` | 在基準範例上的位置 |
| `page_rule` / `ref_page` | 套用頁面，以及標注時所在頁（從 0 起算） |
| `patch` | 基準範例的影像圖塊，儲存時自動產生 |
| `text_center` | 文字中心，儲存時自動產生 |

有標題的欄位，標題也會自動當定位點。

## 欄位 `fields`

| 鍵 | 說明 |
|---|---|
| `id` / `name` | 代號與顯示名稱 |
| `kind` | `key_value` 有標題；`position` 只有值 |
| `label` | `{text, box}`，僅 `key_value` |
| `value_box` | 數值範圍 |
| `page_rule` / `ref_page` | 同上 |
| `type` | `text`、`number`、`date` |
| `required` | 必填，沒抓到會標記 |
| `verify` | 文字層再用 OCR 核對一次 |
| `source` | `auto`、`text`、`ocr` |
| `pick_line` | 取第幾行，1 起算，-1 是最後一行 |
| `extract` | 正規表達式，有群組時取第一個群組 |
| `pattern` | 格式檢查的正規表達式 |
| `join` | `newline` 時，多行內容保留換行 |
| `continuation` | 下一頁的接續範圍：`{box, ref_page}` |

所有正規表達式（`extract`、`pattern`、`key_pattern`、`stop_pattern`）最多 500 字，而且不能在無上限的重複裡再放重複，例如 `(\d+)+` 要寫成 `\d+`。這種寫法遇到比不中的文字會讓解析卡住，範本儲存與載入時會直接擋下。

## 表格 `tables`

| 鍵 | 說明 |
|---|---|
| `id` / `name` | 代號與顯示名稱 |
| `columns` | 輸出欄：`{id, name, band, type, pick_line, start, end, extract, part_by, part, pattern, join, row_required}` |
| `regions` | 各頁範圍：`{page_rule, ref_page, box, dividers, header}`，`header` 為選用的表頭 |
| `end_marker` | 選用的表尾標記：`{text, box, ref_page}` |
| `key_column` | 判斷新一列的欄，例如項次。沒設定時每行文字算一列 |
| `key_pattern` | 新一列的格式，預設純數字 |
| `key_position` | `auto` 自動判斷；`middle` 在列中間或不固定；`top` 在列最上方。舊範本沒有此設定時視為 `middle` |
| `stop_pattern` | 遇到這段文字就結束表格 |
| `source` | `auto`、`text`、`ocr` |

`band` 指向實際的直欄，`dividers` 的相鄰兩條線圍出一個直欄。同一格有上下兩行要分開時，讓兩個輸出欄指向同一個 `band`，再用 `pick_line` 區分行數固定的內容，或用 `start` 依開頭文字切段。`start` 取開頭文字後面的值，`end` 決定結束位置：`line` 到這一行結束、`word` 到第一個空白、`next` 到下一個已設定的開頭為止（未設定時為 `next`）。表格欄的 `extract` 比對不到時留空。`part_by` 為 `space` 或 `gap` 時依空格或字距分段，`part` 是第幾段（從 1 起算）；同一直欄設定了幾個這類欄，就預期有幾段，段數不符時內容全放第一段並標記。都沒設定時，整格內容原樣輸出。

`key_position` 為 `middle` 時，以相鄰兩個項次之間最大的空白切列，新一頁開頭的內容依 `row_required` 判斷歸屬，無法判斷時會標記。為 `top` 時，頁首在第一個項次之前的內容會併到上一頁最後一列，並標記給人確認。

## 輸出 `output`（選用）

只影響乾淨資料。清單順序就是輸出順序，沒列到的欄位預設輸出。

```json
{"fields": [{"id": "f1", "name": "報單號碼", "include": true}],
 "tables": {"t1": [{"id": "c1", "name": "項次", "include": true}]}}
```

## 檢查 `validations`

```json
{"type": "sum_fields", "fields": ["duty", "vat"], "equals": "tax_total", "tolerance": 1}
{"type": "sum_column", "table": "items", "column": "value", "equals": "total", "tolerance": 1}
{"type": "page_count", "field": "page_info"}
```
