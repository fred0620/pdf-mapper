# 測試用字型

`NotoSansTC-subset.otf` 是 Noto Sans CJK TC Regular 的子集，授權為 SIL Open Font License 1.1（見 `OFL.txt`）。
只含 `scripts/make_samples.py` 與測試用到的字，讓 CI 和每台電腦畫出來的範例掃描檔都一樣。不會打包進發布包。

範例或測試加了新的中文字時，`tests/test_fonts.py` 會失敗並列出缺的字。重新裁切：

```bash
pip install fonttools
python3 -c "
import pathlib
src = pathlib.Path('scripts/make_samples.py').read_text()
src += ''.join(p.read_text() for p in pathlib.Path('tests').glob('*.py') if p.name != 'test_fonts.py' and 'make_samples' in p.read_text())
chars = sorted({c for c in src if ord(c) > 0x7e})
pathlib.Path('/tmp/chars.txt').write_text(''.join(chars) + ''.join(chr(i) for i in range(0x20, 0x7f)))
"
pyftsubset NotoSansCJK-Regular.ttc --font-number=3 --text-file=/tmp/chars.txt \
  --output-file=tests/fonts/NotoSansTC-subset.otf --name-IDs='*'
```

`NotoSansCJK-Regular.ttc` 可從 https://github.com/notofonts/noto-cjk 下載，`--font-number=3` 是繁體中文（TC）。
