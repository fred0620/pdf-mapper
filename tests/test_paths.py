"""workspace 的建立、示範範本與舊版資料搬移。"""
import json

import pdfmapper
from pdfmapper import paths


def _point_to(monkeypatch, home):
    workspace = home / "workspace"
    monkeypatch.setattr(paths, "HOME", home)
    monkeypatch.setattr(paths, "WORKSPACE", workspace)
    for name in ("templates", "output", "custom", "logs"):
        monkeypatch.setattr(paths, name.upper(), workspace / name)


def test_first_run_seeds_examples_once(tmp_path, monkeypatch):
    _point_to(monkeypatch, tmp_path)
    paths.prepare()
    seeded = sorted(p.name for p in paths.TEMPLATES.glob("*.json"))
    assert seeded == sorted(p.name for p in (paths.EXAMPLES / "templates").glob("*.json"))
    for path in paths.TEMPLATES.glob("*.json"):
        path.unlink()
    paths.prepare()  # 使用者刪掉示範範本後不會再放回來
    assert not list(paths.TEMPLATES.glob("*.json"))


def test_legacy_folders_are_copied_not_deleted(tmp_path, monkeypatch):
    _point_to(monkeypatch, tmp_path)
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "mine.json").write_text(json.dumps({"template_id": "mine"}), encoding="utf-8")
    (tmp_path / "custom").mkdir()
    (tmp_path / "custom" / "fix.py").write_text("def transform(r):\n    return r\n", encoding="utf-8")
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "old.xlsx").write_bytes(b"x")
    messages = paths.prepare()
    assert (paths.TEMPLATES / "mine.json").exists()
    assert (tmp_path / "templates" / "mine.json").exists()
    assert (paths.CUSTOM / "fix.py").exists()
    assert (paths.OUTPUT / "old.xlsx").exists()
    assert len(messages) == 3
    # 範本已經搬過時，不會把示範範本再塞進來或重複搬
    assert not (paths.TEMPLATES / "customs_demo.json").exists()
    assert paths.prepare() == []


def test_version_comes_from_pyproject():
    text = (paths.APP / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{pdfmapper.__version__}"' in text
