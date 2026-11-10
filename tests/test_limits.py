"""處理上限：危險的正規表達式、頁數、處理時間、渲染記憶體。"""
import pytest

from pdfmapper import limits, parser
from pdfmapper import template as tpl
from pdfmapper.document import Document


@pytest.mark.parametrize("pattern", [r"(a+)+", r"(\w+\s?)+$", r"(.*)*", r"((ab)+)+", r"(a|b+)+"])
def test_rejects_catastrophic_patterns(pattern):
    errors = []
    tpl._check_regex({"pattern": pattern}, ("pattern",), "欄位", errors)
    assert errors and "可能讓解析卡住" in errors[0]


@pytest.mark.parametrize("pattern", [r"^\d{8}$", r"(\d+,)*\d+", r"(?:\d{1,3},)+\d{3}", r"[A-Z]+\d*", r"(ab)+"])
def test_keeps_normal_patterns(pattern):
    errors = []
    tpl._check_regex({"pattern": pattern}, ("pattern",), "欄位", errors)
    assert errors == []


def test_rejects_overlong_pattern():
    errors = []
    tpl._check_regex({"pattern": "a" * 501}, ("pattern",), "欄位", errors)
    assert errors


def test_page_limit(samples, monkeypatch):
    folder, _ = samples
    monkeypatch.setattr(limits, "MAX_PAGES", 0)
    with pytest.raises(limits.LimitExceeded):
        Document(folder / "sample_1_standard.pdf")


def test_deadline_stops_only_that_file(samples, template, monkeypatch):
    folder, _ = samples
    monkeypatch.setattr(limits, "FILE_SECONDS", -1)
    result = parser.parse_pdf(folder / "sample_1_standard.pdf", template)
    assert result["status"] == "failed"
    assert "已停止這份檔案" in result["issues"][-1]["message"]
    monkeypatch.undo()
    assert parser.parse_pdf(folder / "sample_1_standard.pdf", template)["status"] != "failed"


def test_render_cache_is_bounded(samples, monkeypatch):
    folder, _ = samples
    monkeypatch.setattr("pdfmapper.document.MAX_CACHED_RENDERS", 2)
    with Document(folder / "sample_8_table_b.pdf") as doc:
        for page in doc.pages:
            page.render(40)
            page.render(50)
        assert len(doc._renders) <= 2


def test_huge_page_is_downscaled(samples, monkeypatch):
    folder, _ = samples
    monkeypatch.setattr("pdfmapper.document.MAX_RENDER_PIXELS", 100_000)
    with Document(folder / "sample_1_standard.pdf") as doc:
        image = doc.pages[0].render(300)
    assert image.shape[0] * image.shape[1] <= 110_000
