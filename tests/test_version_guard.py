"""版本不一致防護的單元測試：程式指紋、API、實例檔與第二次啟動流程。"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

import pdfmapper.build as build
import pdfmapper.server as server


def _make_fake_pkg(root: Path) -> Path:
    pkg = root / "pdfmapper"
    (pkg / "web").mkdir(parents=True)
    (pkg / "demo" / "labs").mkdir(parents=True)
    (pkg / "server.py").write_text("print('hi')\n", encoding="utf-8")
    (pkg / "web" / "app.js").write_text("console.log(1);\n", encoding="utf-8")
    (pkg / "demo" / "labs.json").write_text('{"a": 1}\n', encoding="utf-8")
    (pkg / "demo" / "labs" / "x.json").write_text('{"b": 2}\n', encoding="utf-8")
    return pkg


def test_compute_build_id_stability_sensitivity_and_pycache(tmp_path):
    """同內容同結果；改一個 web/ 檔案結果改變；__pycache__ 不影響。"""
    pkg = _make_fake_pkg(tmp_path)
    first = build.compute_build_id(pkg)
    assert len(first) == 12
    assert build.compute_build_id(pkg) == first

    cache_dir = pkg / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "server.cpython-312.pyc").write_bytes(b"pyc-bytes")
    (cache_dir / "extra.py").write_text("ignored = True\n", encoding="utf-8")
    assert build.compute_build_id(pkg) == first

    (pkg / "web" / "app.js").write_text("console.log(2);\n", encoding="utf-8")
    second = build.compute_build_id(pkg)
    assert second != first


def test_disk_build_cache_and_override(tmp_path, monkeypatch):
    """mtime 不變時不重算；mtime 變動時重算；環境變數 PDFMAPPER_BUILD_OVERRIDE 可覆蓋。"""
    pkg = _make_fake_pkg(tmp_path)
    monkeypatch.delenv("PDFMAPPER_BUILD_OVERRIDE", raising=False)
    monkeypatch.setitem(build._cache, "key", None)
    monkeypatch.setitem(build._cache, "value", None)

    calls = 0
    real_compute = build.compute_build_id

    def spy(base=None):
        nonlocal calls
        calls += 1
        return real_compute(base)

    monkeypatch.setattr(build, "compute_build_id", spy)
    first = build.disk_build(pkg)
    second = build.disk_build(pkg)
    assert first == second
    assert calls == 1

    target = pkg / "web" / "app.js"
    target.write_text("console.log(3);\n", encoding="utf-8")
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    third = build.disk_build(pkg)
    assert third != first
    assert calls == 2

    monkeypatch.setenv("PDFMAPPER_BUILD_OVERRIDE", "override1234")
    assert build.disk_build(pkg) == "override1234"
    assert calls == 2


def test_ping_and_status_include_build_without_paths(monkeypatch):
    """/api/ping 與 /api/status 回傳新欄位，且不外洩本機路徑。"""
    monkeypatch.delenv("PDFMAPPER_BUILD_OVERRIDE", raising=False)
    client = server.app.test_client()

    ping_resp = client.get("/api/ping")
    assert ping_resp.status_code == 200
    ping_data = ping_resp.json
    assert ping_data["version"] == server.__version__
    assert ping_data["build"] == server.RUNNING_BUILD
    assert len(ping_data["build"]) == 12
    assert str(server.paths.HOME) not in ping_resp.get_data(as_text=True)

    status_resp = client.get("/api/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json
    assert status_data["build"] == server.RUNNING_BUILD
    assert status_data["disk_build"] == server.disk_build()
    assert str(server.paths.HOME) not in status_resp.get_data(as_text=True)


def test_shutdown_api_auth_origin_busy_and_ok(monkeypatch):
    """/api/shutdown：缺 token、錯 token、跨站被擋、解析中回 busy、正確時回 ok 並觸發關閉。"""
    client = server.app.test_client()
    monkeypatch.setattr(server, "_instance_token", "secret-token-123")

    # 沒帶 token -> 403
    assert client.post("/api/shutdown").status_code == 403
    # token 錯 -> 403
    assert client.post("/api/shutdown", headers={"X-Instance-Token": "wrong"}).status_code == 403
    # 跨站 Origin -> 403
    assert client.post(
        "/api/shutdown",
        headers={"X-Instance-Token": "secret-token-123", "Origin": "https://evil.example"},
    ).status_code == 403
    assert client.post(
        "/api/shutdown",
        headers={"X-Instance-Token": "secret-token-123", "Sec-Fetch-Site": "cross-site"},
    ).status_code == 403

    # 解析進行中 -> busy，不觸發關閉
    called = threading.Event()
    reasons: list[str] = []

    def fake_shutdown(reason: str):
        reasons.append(reason)
        called.set()

    monkeypatch.setattr(server, "_shutdown", fake_shutdown)
    monkeypatch.setattr(server, "_busy", lambda: True)
    busy_resp = client.post("/api/shutdown", headers={"X-Instance-Token": "secret-token-123"})
    assert busy_resp.status_code == 200
    assert busy_resp.json == {"ok": False, "reason": "busy"}
    assert not called.wait(0.25)

    # 非解析中 -> ok，並在回應後觸發 _shutdown
    monkeypatch.setattr(server, "_busy", lambda: False)
    ok_resp = client.post("/api/shutdown", headers={"X-Instance-Token": "secret-token-123"})
    assert ok_resp.status_code == 200
    assert ok_resp.json == {"ok": True}
    assert called.wait(2.0)
    assert reasons == ["新版啟動，關閉舊版"]


def test_instance_file_write_remove_and_overwrite_stale(tmp_path, monkeypatch):
    """實例檔：啟動寫入、結束刪除、殘留檔可覆寫。"""
    monkeypatch.setattr(server, "RUN_DIR", tmp_path)
    monkeypatch.setattr(server, "_instance_token", None)
    path = tmp_path / "instance.json"

    # 殘留舊檔（不存在的 pid）
    path.write_text(json.dumps({"port": 8765, "pid": 99999999, "build": "old", "version": "0.4.0", "token": "stale"}),
                    encoding="utf-8")

    token = server._write_instance(8765)
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["port"] == 8765
    assert data["pid"] == os.getpid()
    assert data["build"] == server.RUNNING_BUILD
    assert data["version"] == server.__version__
    assert data["token"] == token
    assert server._instance_token == token

    server._remove_instance()
    assert not path.exists()
    assert server._instance_token is None


def test_second_launch_same_build_opens_browser(monkeypatch):
    """build 相同時維持現行為，只開瀏覽器。"""
    opened: list[str] = []
    monkeypatch.setattr(server, "compute_build_id", lambda: "samebuild123")
    monkeypatch.setattr(server.webbrowser, "open", opened.append)

    proceed = server._handle_running(8765, {"app": "pdfmapper", "version": "0.4.1", "build": "samebuild123"}, True)
    assert proceed is False
    assert opened == ["http://127.0.0.1:8765"]


def test_second_launch_different_build_yes_ok_starts_new(tmp_path, monkeypatch):
    """build 不同且回答 Y、shutdown 回 ok 時，等埠釋放後繼續啟動新版。"""
    monkeypatch.setattr(server, "RUN_DIR", tmp_path)
    (tmp_path / "instance.json").write_text(
        json.dumps({"port": 8765, "pid": 12345, "build": "oldbuild0000", "version": "0.4.0", "token": "tok-abc"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "compute_build_id", lambda: "newbuild9999")
    monkeypatch.setattr(server, "_is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "Y")

    shutdown_calls: list[tuple[int, str]] = []
    monkeypatch.setattr(server, "_request_shutdown", lambda port, tok: (shutdown_calls.append((port, tok)), "ok")[1])

    waits = []
    monkeypatch.setattr(server, "_wait_port_free", lambda port: (waits.append(port), True)[1])

    opened: list[str] = []
    monkeypatch.setattr(server.webbrowser, "open", opened.append)

    proceed = server._handle_running(8765, {"app": "pdfmapper", "version": "0.4.0", "build": "oldbuild0000"}, True)
    assert proceed is True
    assert shutdown_calls == [(8765, "tok-abc")]
    assert waits == [8765]
    assert opened == []


def test_second_launch_busy(tmp_path, monkeypatch, capsys):
    """舊版解析中回 busy：顯示提示、開瀏覽器到舊版後結束。"""
    monkeypatch.setattr(server, "RUN_DIR", tmp_path)
    (tmp_path / "instance.json").write_text(
        json.dumps({"port": 8765, "pid": 12345, "build": "oldbuild0000", "version": "0.4.1", "token": "tok-abc"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "compute_build_id", lambda: "newbuild9999")
    monkeypatch.setattr(server, "_is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
    monkeypatch.setattr(server, "_request_shutdown", lambda _port, _tok: "busy")
    opened: list[str] = []
    monkeypatch.setattr(server.webbrowser, "open", opened.append)

    proceed = server._handle_running(8765, {"app": "pdfmapper", "version": "0.4.1", "build": "oldbuild0000"}, True)
    assert proceed is False
    assert "舊版正在解析" in capsys.readouterr().out
    assert opened == ["http://127.0.0.1:8765"]


def test_second_launch_no_instance_file(tmp_path, monkeypatch, capsys):
    """沒有實例檔（例如 0.4.0 以前）：顯示手動關閉說明、開瀏覽器到舊版後結束。"""
    monkeypatch.setattr(server, "RUN_DIR", tmp_path)
    monkeypatch.setattr(server, "compute_build_id", lambda: "newbuild9999")
    monkeypatch.setattr(server, "_is_interactive", lambda: True)
    monkeypatch.setattr(server, "_fetch_version", lambda _port: "0.4.0")
    monkeypatch.setattr("builtins.input", lambda _prompt="": "Y")
    opened: list[str] = []
    monkeypatch.setattr(server.webbrowser, "open", opened.append)

    proceed = server._handle_running(8765, {"app": "pdfmapper"}, True)
    assert proceed is False
    out = capsys.readouterr().out
    assert "0.4.0" in out
    assert "請關閉所有工具分頁" in out
    assert opened == ["http://127.0.0.1:8765"]


def test_second_launch_answer_no(monkeypatch):
    """回答 N：不關閉舊版，開瀏覽器到舊版後結束。"""
    monkeypatch.setattr(server, "compute_build_id", lambda: "newbuild9999")
    monkeypatch.setattr(server, "_is_interactive", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
    opened: list[str] = []
    monkeypatch.setattr(server.webbrowser, "open", opened.append)
    shutdown_called = False
    monkeypatch.setattr(server, "_request_shutdown", lambda *_args: (shutdown_called := True))  # noqa: F841

    proceed = server._handle_running(8765, {"app": "pdfmapper", "version": "0.4.0", "build": "old"}, True)
    assert proceed is False
    assert opened == ["http://127.0.0.1:8765"]


@pytest.mark.parametrize("open_browser,interactive", [(False, True), (True, False)])
def test_second_launch_non_interactive_exits_nonzero(monkeypatch, capsys, open_browser, interactive):
    """非互動模式（--no-browser 或 stdin 不是 tty）：不詢問、印訊息、非 0 結束、不關閉舊版。"""
    monkeypatch.setattr(server, "compute_build_id", lambda: "newbuild9999")
    monkeypatch.setattr(server, "_is_interactive", lambda: interactive)
    monkeypatch.setattr("builtins.input", lambda *_args: pytest.fail("非互動模式不應詢問"))

    with pytest.raises(SystemExit) as exc:
        server._handle_running(8765, {"app": "pdfmapper", "version": "0.4.0", "build": "old"}, open_browser)
    assert exc.value.code == 1
    assert "0.4.0" in capsys.readouterr().out


def test_serve_writes_and_removes_instance_file(tmp_path, monkeypatch):
    """serve() 啟動成功後寫入 instance.json，正常結束時刪除。"""
    monkeypatch.setattr(server, "RUN_DIR", tmp_path / "run")
    monkeypatch.setattr(server, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(server, "UPLOADS", tmp_path / "uploads")
    monkeypatch.setattr(server.paths, "prepare", lambda: [])
    monkeypatch.setattr(server.logs, "setup", lambda _p: None)
    monkeypatch.setattr(server, "_pick_port", lambda _p: (18765, None))
    monkeypatch.setattr(server.ocr_engine, "available", lambda: False)

    seen_during_run: dict = {}

    class DummyServer:
        def serve_forever(self):
            seen_during_run.update(server._read_instance() or {})

        def server_close(self):
            pass

    monkeypatch.setattr(server, "make_server", lambda *_args, **_kwargs: DummyServer())

    server.serve(port=18765, open_browser=False)
    assert seen_during_run.get("port") == 18765
    assert seen_during_run.get("pid") == os.getpid()
    assert seen_during_run.get("build") == server.RUNNING_BUILD
    assert seen_during_run.get("token")
    assert not (tmp_path / "run" / "instance.json").exists()

