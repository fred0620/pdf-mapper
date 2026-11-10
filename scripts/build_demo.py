"""重建 app/samples/ 與 app/examples/templates/ 的示範範本。"""
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
print("完成")
