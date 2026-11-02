"""客製化範例：把金額欄位去掉千分位。實際使用時複製一份再改。"""


def transform(results: list[dict]) -> list[dict]:
    for result in results:
        for field in result["fields"]:
            if field["id"].endswith("_amount"):
                field["value"] = field["value"].replace(",", "")
    return results
