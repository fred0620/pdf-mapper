"""指令列入口。

    python -m pdfmapper                       開啟網頁工具
    python -m pdfmapper run -t 範本.json -i 資料夾 -o 結果.xlsx
    python -m pdfmapper doctor                檢查環境
    python -m pdfmapper --version             顯示版本
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _command_run(args) -> int:
    from . import logs, paths, postprocess, template as tpl
    from .clean import write_clean
    from .excel import write_excel
    from .parser import parse_best

    paths.prepare()
    logs.setup(paths.LOGS)
    source = Path(args.template)
    templates = ([tpl.load(p) for p in sorted(source.glob("*.json"))] if source.is_dir() else [tpl.load(source)])
    target = Path(args.input)
    files = sorted(target.glob("**/*.pdf")) if target.is_dir() else [target]
    if not files:
        print(f"找不到 PDF：{target}", file=sys.stderr)
        return 2
    results = []
    for index, path in enumerate(files, start=1):
        result = parse_best(path, templates, use_ocr=not args.no_ocr)
        results.append(result)
        counts = result["counts"]
        print(f"[{index}/{len(files)}] {path.name}：{result['template_name']}，{result['status']}，"
              f"需檢查 {counts['review']}，缺值 {counts['missing']}")
    results = postprocess.apply(results, args.post)
    output = write_excel(results, args.output or paths.OUTPUT / "解析結果.xlsx")
    print(f"已輸出 {output}")
    if args.clean:
        by_id = {template["template_id"]: template for template in templates}
        print(f"已輸出 {write_clean(results, by_id, args.clean, args.only_confirmed)}")
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if any(r["status"] == "failed" for r in results) else 0


def _command_doctor(_args) -> int:
    import platform

    from . import __version__, paths

    print(f"PDF 解析器 {__version__}，Python {platform.python_version()}")
    print(f"資料位置：{paths.WORKSPACE}")
    healthy = True
    for name in ("pdfplumber", "pypdfium2", "cv2", "numpy", "PIL", "openpyxl", "flask"):
        try:
            __import__(name)
            print(f"  OK   {name}")
        except ImportError as exc:
            healthy = False
            print(f"  缺少 {name}：{exc}")
    from . import ocr

    if ocr.available():
        print("  OK   影像辨識")
    else:
        print(f"  無法使用影像辨識（文字層仍可用）：{ocr.status()}")
    return 0 if healthy else 1


def main() -> int:
    from . import __version__

    parser = argparse.ArgumentParser(prog="pdfmapper", description="PDF 解析器")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    commands = parser.add_subparsers(dest="command")
    run = commands.add_parser("run", help="批次解析")
    run.add_argument("-t", "--template", required=True, help="範本 JSON，或放範本的資料夾（每份自動挑最符合的）")
    run.add_argument("-i", "--input", required=True, help="PDF 或資料夾")
    run.add_argument("-o", "--output", help="預設為 workspace/output/解析結果.xlsx")
    run.add_argument("--clean", help="同時輸出乾淨資料的 Excel")
    run.add_argument("--only-confirmed", action="store_true", help="乾淨資料排除需檢查和缺值的資料")
    run.add_argument("--json", help="同時輸出完整結果 JSON")
    run.add_argument("--post", help="第三層客製化腳本")
    run.add_argument("--no-ocr", action="store_true", help="只用文字層")
    commands.add_parser("doctor", help="檢查環境")
    args = parser.parse_args()
    if args.command == "run":
        return _command_run(args)
    if args.command == "doctor":
        return _command_doctor(args)
    from .server import serve

    serve(args.port, not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
