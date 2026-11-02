"""重建 samples/ 與示範範本。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import make_samples  # noqa: E402

from pdfmapper import template as tpl  # noqa: E402
from pdfmapper.document import Document  # noqa: E402

make_samples.build_all(ROOT / "samples")
template = make_samples.build_template()
with Document(ROOT / "samples" / "sample_1_standard.pdf") as reference:
    tpl.finalize(template, reference)
tpl.save(template, ROOT / "templates" / "customs_demo.json")
print("完成")
