"""新功能導覽的發版檢查（scripts/check_whatsnew.py）。"""
import json

import check_whatsnew


def _write(tmp_path, versions):
    path = tmp_path / "whatsnew.json"
    path.write_text(json.dumps({"versions": versions}, ensure_ascii=False), encoding="utf-8")
    return path


def test_repo_whatsnew_has_current_version():
    version = check_whatsnew.read_version(check_whatsnew.ROOT / "app" / "pyproject.toml")
    assert check_whatsnew.main([]) == 0
    assert check_whatsnew.check(check_whatsnew.WEB / "whatsnew.json", version, check_whatsnew.WEB / "spotlights.js") == []


def test_missing_version_fails(tmp_path):
    path = _write(tmp_path, [{"version": "0.1.0", "items": []}])
    assert check_whatsnew.main(["--file", str(path), "--version", "0.2.0"]) == 1
    assert check_whatsnew.main(["--file", str(path), "--version", "0.1.0"]) == 0  # 沒有可見改變可以是空的


def test_unknown_spotlight_and_long_text_fail(tmp_path):
    item = {"id": "x", "title": "跳到下一個待檢查", "body": "短說明", "spotlight": "no-such-step"}
    errors = check_whatsnew.check(_write(tmp_path, [{"version": "1.0.0", "items": [item]}]), "1.0.0",
                                  check_whatsnew.WEB / "spotlights.js")
    assert any("no-such-step" in e for e in errors)
    item = {"id": "x", "title": "標" * 17, "body": "說" * 41, "spotlight": "run-next-flagged"}
    errors = check_whatsnew.check(_write(tmp_path, [{"version": "1.0.0", "items": [item]}]), "1.0.0",
                                  check_whatsnew.WEB / "spotlights.js")
    assert len(errors) == 2
