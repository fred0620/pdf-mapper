import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import make_samples  # noqa: E402

from pdfmapper import template as tpl  # noqa: E402
from pdfmapper.document import Document  # noqa: E402


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    folder = tmp_path_factory.mktemp("samples")
    return folder, make_samples.build_all(folder)


@pytest.fixture(scope="session")
def template(samples):
    folder, _docs = samples
    data = make_samples.build_template()
    with Document(folder / "sample_1_standard.pdf") as reference:
        return tpl.finalize(data, reference)


@pytest.fixture(scope="session")
def invoice_template(samples):
    folder, _docs = samples
    data = make_samples.build_invoice_template()
    with Document(folder / "sample_6_invoice.pdf") as reference:
        return tpl.finalize(data, reference)


@pytest.fixture(scope="session")
def floating_template(samples):
    folder, _docs = samples
    data = make_samples.build_floating_template()
    with Document(folder / "sample_7_table_a.pdf") as reference:
        return tpl.finalize(data, reference)
