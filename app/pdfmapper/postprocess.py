"""第三層：客製化資料處理的接口（本專案不實作客製邏輯）。

在 workspace/custom/ 放一支 .py（範例在 app/examples/custom/），定義 transform(results: list[dict]) -> list[dict]，
即可在輸出 Excel 前改寫資料。第二層輸出的 value 都是原樣字串，轉數字、改欄名都放這裡。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


def apply(results: list[dict], script: str | Path | None) -> list[dict]:
    if not script:
        return results
    spec = importlib.util.spec_from_file_location("pdfmapper_custom", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.transform(results)
