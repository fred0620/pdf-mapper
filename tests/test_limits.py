"""處理上限：危險的正規表達式、頁數、處理時間、渲染記憶體。"""
import copy

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


@pytest.mark.parametrize("pattern", [r"(\d+\s?){6}$", r"(\d+[,.]?){8}元$", r"(\w+\s?){5}$", r"(?:a+){3}"])
def test_rejects_bounded_nested_repeats(pattern):
    """外層有次數上限也會卡住：(\\d+\\s?){3} 遇到 300 字就要好幾秒。"""
    errors = []
    tpl._check_regex({"pattern": pattern}, ("pattern",), "欄位", errors)
    assert errors and "可能讓解析卡住" in errors[0]


@pytest.mark.parametrize("pattern", [r"(\d+\s?){2}", r"(\d+,){8}", r"\d{3}-\d{4}"])
def test_keeps_small_bounded_repeats(pattern):
    errors = []
    tpl._check_regex({"pattern": pattern}, ("pattern",), "欄位", errors)
    assert errors == []


def test_slow_pattern_times_out_instead_of_hanging(monkeypatch):
    """事前檢查擋不到的寫法，執行時也會在時限內停下來。"""
    monkeypatch.setattr(limits, "REGEX_SECONDS", 0.2)
    pattern = r"(a|aa)+$"
    errors = []
    tpl._check_regex({"pattern": pattern}, ("pattern",), "欄位", errors)
    assert errors == []  # 選項重疊的寫法事前偵測不到
    with pytest.raises(limits.PatternTimeout, match="比對超過"):
        limits.search(pattern, "a" * 60 + "!")
    assert limits.search(r"(\d+)", "No. 123").group(1) == "123"


def test_slow_pattern_fails_only_that_file(samples, template, monkeypatch):
    folder, _ = samples
    # 範例 PDF 的值都很短，真的寫法不容易逾時；這裡模擬逾時，確認會停在這份檔案並說明原因
    def timeout(pattern, text, flags=0, timeout=None):
        if pattern == "SLOW":
            raise TimeoutError("regex timed out")
        return original(pattern, text, flags, timeout=timeout)

    original = limits.regex.search
    monkeypatch.setattr(limits.regex, "search", timeout)
    slow = copy.deepcopy(template)
    slow["fields"][0]["pattern"] = "SLOW"
    result = parser.parse_pdf(folder / "sample_1_standard.pdf", slow)
    assert result["status"] == "failed"
    assert "正規表達式" in result["issues"][-1]["message"]
    assert parser.parse_pdf(folder / "sample_1_standard.pdf", template)["status"] != "failed"


def test_deadline_message_uses_actual_seconds():
    with limits.file_deadline(-1):
        with pytest.raises(limits.LimitExceeded, match="0 秒"):
            limits.check_deadline()
