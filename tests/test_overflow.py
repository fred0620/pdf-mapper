"""表格直欄「內容超出分隔線」：自動、可超出、不可超出。"""
from pdfmapper import template as tpl
from test_parser import _band_result, _band_template, _word


def _layout(rows, overflow=None, dividers=(0.1, 0.5, 0.9)):
    from pdfmapper.extract import _assign_chunks

    glyphs = [g for row in rows for g in row]
    return _assign_chunks(glyphs, list(dividers), set(), overflow)


def _glued_rows():
    """品名最後一個字壓在 0.5 的線上，緊接著稅則號碼（照片的情況）。前幾列正常，讓兩欄都判斷出靠左。"""
    normal = [_word("SHANJIA POWER", 0.11, 0.1 + i * 0.03) + _word("8537.10.90.00-5", 0.52, 0.1 + i * 0.03)
              for i in range(4)]
    name = _word("PUXIN Power Distribution Cabinet", 0.184, 0.25)   # 最後的 t 在 0.494 到 0.504
    code = _word("8537.10.90.00-5", 0.504, 0.25)
    return normal + [name + code], name, code


def test_glued_text_goes_to_one_column_by_default():
    rows, name, code = _glued_rows()
    layout = _layout(rows)
    assert layout[id(code[0])][0] == 0  # 記錄目前的行為：整段歸品名欄


def test_deny_cuts_glued_text_at_letter_digit_switch():
    rows, name, code = _glued_rows()
    for overflow in ({0: "deny"}, {1: "deny"}):  # 線的哪一邊設定都一樣
        layout = _layout(rows, overflow)
        assert {layout[id(g)] for g in name} == {(0, None)}
        assert {layout[id(g)] for g in code} == {(1, None)}


def test_deny_keeps_a_letter_that_only_overhangs_the_line():
    rows = [_word("POWER DISTRIBUTION", 0.322, 0.1)]  # 最後的 N 在 0.492 到 0.502，只超出線一點點
    layout = _layout(rows, {0: "deny"})
    assert {layout[id(g)] for g in rows[0]} == {(0, None)}


def test_deny_without_natural_cut_splits_by_center_and_flags():
    word = _word("ABCDEFGH", 0.46, 0.1)  # 0.46 到 0.54，同一種字，沒有空白
    layout = _layout([word], {0: "deny"})
    assert [layout[id(g)][0] for g in word] == [0, 0, 0, 0, 1, 1, 1, 1]
    assert {layout[id(g)][1] for g in word} == {"split_at_divider"}


def test_deny_prefers_space_near_the_line():
    word = _word("ABC DEFGH", 0.47, 0.1)  # 空白在 0.50 到 0.51
    layout = _layout([word], {0: "deny"})
    assert [layout[id(g)][0] for g in word if g.text.strip()] == [0, 0, 0, 1, 1, 1, 1, 1]
    assert {layout[id(g)][1] for g in word} == {None}


def test_allow_keeps_long_text_without_flag():
    rows = [_word("ITEM", 0.11, 0.1 + i * 0.03) + _word("99", 0.55, 0.1 + i * 0.03) for i in range(4)]
    long_name = _word("VERY LONG GOODS NAME RUNS INTO NEXT COLUMN", 0.11, 0.3)  # 0.11 到 0.53
    layout = _layout(rows + [long_name], {0: "allow"})
    assert {layout[id(g)] for g in long_name} == {(0, None)}


def test_allow_on_both_sides_falls_back_to_auto():
    rows = [_word("ITEM", 0.11, 0.1 + i * 0.03) + _word("99", 0.55, 0.1 + i * 0.03) for i in range(4)]
    long_name = _word("VERY LONG GOODS NAME RUNS INTO NEXT COLUMN", 0.11, 0.3)
    auto = _layout(rows + [long_name])
    both = _layout(rows + [long_name], {0: "allow", 1: "allow"})
    assert {auto[id(g)] for g in long_name} == {both[id(g)] for g in long_name}


def test_empty_overflow_is_identical_to_before():
    rows, _name, _code = _glued_rows()
    glyphs = [g for row in rows for g in row]
    from pdfmapper.extract import _assign_chunks

    assert _assign_chunks(glyphs, [0.1, 0.5, 0.9]) == _assign_chunks(glyphs, [0.1, 0.5, 0.9], set(), {})


def test_band_overflow_takes_the_strictest():
    from pdfmapper.extract import _band_overflow, _hard_dividers

    columns = [{"id": "a", "band": 0}, {"id": "b", "band": 1, "overflow": "allow"},
               {"id": "c", "band": 1, "overflow": "deny"}, {"id": "d", "band": 2, "overflow": "allow"}]
    assert _band_overflow(columns) == {1: "deny", 2: "allow"}
    assert _hard_dividers([0.0, 0.3, 0.6, 1.0], {1: "deny"}) == [1, 2]


def test_extract_table_passes_overflow(monkeypatch, tmp_path):
    from pdfmapper import extract

    seen = []
    original = extract._assign_chunks
    monkeypatch.setattr(extract, "_assign_chunks",
                        lambda glyphs, dividers, gap_bands=frozenset(), overflow=None:
                        seen.append(overflow) or original(glyphs, dividers, gap_bands, overflow))
    _band_result(tmp_path, ["text"], [{"id": "a", "name": "A", "band": 1, "overflow": "deny"}])
    assert seen and all(o == {1: "deny"} for o in seen)


def test_overflow_value_is_validated():
    template = _band_template([{"id": "a", "name": "A", "band": 1, "overflow": "maybe"}])
    assert any("超出分隔線" in e for e in tpl.validate(template))
    template = _band_template([{"id": "a", "name": "A", "band": 1, "overflow": "deny"}])
    assert not any("超出分隔線" in e for e in tpl.validate(template))
