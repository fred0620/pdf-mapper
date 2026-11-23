"""重建 app/samples/、app/examples/templates/ 的示範範本，以及新手導覽用的 app/pdfmapper/demo/。"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path[:0] = [str(APP), str(ROOT / "scripts")]

import make_samples  # noqa: E402

from pdfmapper import template as tpl  # noqa: E402
from pdfmapper.document import Document  # noqa: E402

make_samples.build_all(APP / "samples")
template = make_samples.build_template()
with Document(APP / "samples" / "sample_1_standard.pdf") as reference:
    tpl.finalize(template, reference)
tpl.save(template, APP / "examples" / "templates" / "customs_demo.json")
invoice = make_samples.build_invoice_template()
with Document(APP / "samples" / "sample_6_invoice.pdf") as reference:
    tpl.finalize(invoice, reference)
tpl.save(invoice, APP / "examples" / "templates" / "invoice_demo.json")
floating = make_samples.build_floating_template()
with Document(APP / "samples" / "sample_7_table_a.pdf") as reference:
    tpl.finalize(floating, reference)
tpl.save(floating, APP / "examples" / "templates" / "floating_demo.json")
# 新手導覽的示範檔：從上面產生的範例複製，跟著 app 更新、使用者刪不掉（不依賴 workspace/templates）
DEMO = APP / "pdfmapper" / "demo"
DEMO.mkdir(exist_ok=True)
for name in ("sample_1_standard.pdf", "sample_5_errors.pdf", "sample_6_invoice.pdf"):
    shutil.copy2(APP / "samples" / name, DEMO / name)
for name in ("invoice_demo.json", "customs_demo.json"):
    shutil.copy2(APP / "examples" / "templates" / name, DEMO / name)
make_samples.build_labs(DEMO / "labs")  # 實地練習的 PDF 與練習範本
print("完成")
