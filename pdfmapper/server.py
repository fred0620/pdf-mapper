"""本機網頁工具的後端。只綁定 127.0.0.1，檔案不會離開這台電腦。"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import socket
import threading
import time
import urllib.request
import uuid
import webbrowser
from pathlib import Path

import cv2
from flask import Flask, jsonify, request, send_file, send_from_directory

from . import ocr as ocr_engine
from . import template as tpl
from .clean import write_clean
from .document import Document
from .excel import write_excel
from .extract import REASONS, read_box
from .parser import find_value, parse_best, parse_pdf, summarize

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent / "web"
WORKSPACE = ROOT / "workspace"
UPLOADS = WORKSPACE / "uploads"
TEMPLATES = ROOT / "templates"
OUTPUT = ROOT / "output"
PREVIEW_DPI = 120
MAX_OPEN_DOCS = 8
PORT_RANGE = 20
CLOSE_GRACE_SECONDS = 8      # 容許重新整理頁面，不會誤關
CLIENT_TIMEOUT_SECONDS = 1800  # 瀏覽器當掉、沒通知就消失時的上限
NO_CLIENT_TIMEOUT_SECONDS = 600  # 啟動後一直沒有開啟頁面
WATCH_SECONDS = 2
SLEEP_GAP_SECONDS = 30       # 檢查間隔突然變長，代表電腦剛從睡眠醒來

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024

_docs: dict[str, Document] = {}
_docs_lock = threading.Lock()
_runs: dict[str, dict] = {}
_run_templates: dict[str, dict[str, dict]] = {}  # 含影像圖塊，不放進回傳給頁面的資料
_clients: dict[str, float] = {}
_clients_lock = threading.Lock()


def _doc_path(doc_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", doc_id):
        raise FileNotFoundError(doc_id)
    matches = list(UPLOADS.glob(f"{doc_id}__*"))
    if not matches:
        raise FileNotFoundError(doc_id)
    return matches[0]


def _doc(doc_id: str) -> Document:
    with _docs_lock:
        if doc_id in _docs:
            _docs[doc_id] = _docs.pop(doc_id)  # 移到最新，淘汰最久沒用的
        else:
            if len(_docs) >= MAX_OPEN_DOCS:
                _docs.pop(next(iter(_docs))).close()
            _docs[doc_id] = Document(_doc_path(doc_id))
        return _docs[doc_id]


def _describe(doc_id: str, name: str) -> dict:
    doc = _doc(doc_id)
    has_text = any(len(p.glyphs) > 0 for p in doc.pages[:3])
    return {"id": doc_id, "name": name, "pages": len(doc), "has_text": has_text,
            "sizes": [[p.width, p.height] for p in doc.pages]}


def _template_path(template_id: str) -> Path:
    if not re.fullmatch(r"[\w\-]+", template_id):
        raise ValueError("範本代號只能用文字、數字、底線與連字號")
    return TEMPLATES / f"{template_id}.json"


def _error(message: str, code: int = 400):
    return jsonify({"error": message}), code


@app.errorhandler(FileNotFoundError)
def _not_found(_exc):
    return _error("找不到這個檔案，請重新加入 PDF", 404)


@app.errorhandler(ValueError)
def _bad_value(exc):
    return _error(str(exc))


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/manual")
def manual():
    return send_from_directory(ROOT, "使用手冊.html")


@app.get("/web/<path:name>")
def web_file(name):
    return send_from_directory(WEB, name)


@app.get("/api/ping")
def ping():
    """給第二次啟動判斷「工具是否已經開著」，不能碰到載入中的 OCR。"""
    return jsonify({"app": "pdfmapper", "root": str(ROOT)})


@app.post("/api/heartbeat")
def heartbeat():
    with _clients_lock:
        _clients[request.args["client"]] = time.time()
    return jsonify({"ok": True})


@app.post("/api/bye")
def bye():
    with _clients_lock:
        _clients.pop(request.args.get("client", ""), None)
    return jsonify({"ok": True})


@app.get("/api/status")
def status():
    return jsonify({"ocr": ocr_engine.available(), "ocr_error": ocr_engine.status(), "reasons": REASONS})


@app.post("/api/docs")
def upload():
    UPLOADS.mkdir(parents=True, exist_ok=True)
    added, failed = [], []
    for item in request.files.getlist("files"):
        name = Path(item.filename or "file.pdf").name
        doc_id = uuid.uuid4().hex
        target = UPLOADS / f"{doc_id}__{name}"
        item.save(target)
        try:
            added.append(_describe(doc_id, name))
        except Exception as exc:
            target.unlink(missing_ok=True)
            failed.append({"name": name, "error": f"無法開啟：{exc}"})
    return jsonify({"docs": added, "failed": failed})


@app.delete("/api/docs/<doc_id>")
def remove_doc(doc_id):
    if _busy():
        return _error("解析進行中，完成後才能移除檔案", 409)
    path = _doc_path(doc_id)
    with _docs_lock:
        doc = _docs.pop(doc_id, None)
        if doc:
            doc.close()
    path.unlink(missing_ok=True)
    for run in _runs.values():
        run["results"] = [r for r in run["results"] if r.get("doc_id") != doc_id]
    return jsonify({"removed": doc_id})


@app.get("/api/docs/<doc_id>/page/<int:index>.png")
def page_image(doc_id, index):
    dpi = min(int(request.args.get("dpi", PREVIEW_DPI)), 220)
    image = _doc(doc_id).pages[index].render(dpi)
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    return send_file(io.BytesIO(encoded.tobytes()), mimetype="image/png", max_age=3600)


@app.post("/api/docs/<doc_id>/read")
def read_region(doc_id):
    body = request.get_json()
    page = _doc(doc_id).pages[body["page"]]
    reading = read_box(page, tuple(body["box"]), body.get("source", "auto"))
    return jsonify({"text": reading.text, "lines": reading.lines, "source": reading.source,
                    "confidence": reading.confidence,
                    "notes": [REASONS.get(r, r) for r in reading.reasons]})


@app.post("/api/docs/<doc_id>/suggest-anchors")
def suggest(doc_id):
    body = request.get_json()
    page = _doc(doc_id).pages[body["page"]]
    return jsonify({"anchors": tpl.suggest_anchors(page, body.get("avoid", []), body.get("page_rule", "first"))})




@app.post("/api/test")
def test_template():
    """用範例測試目前的範本（不存檔）。"""
    body = request.get_json()
    template = body["template"]
    errors = tpl.validate(template)
    if errors:
        return _error("；".join(errors))
    tpl.finalize(template, _doc(body["reference"]))
    results = [parse_pdf(_doc_path(doc_id), template) for doc_id in body["docs"]]
    for doc_id, result in zip(body["docs"], results):
        result["doc_id"] = doc_id
        result["file"] = result["file"].split("__", 1)[-1]
    return jsonify({"results": results, "template": template})


@app.get("/api/templates")
def list_templates():
    items = []
    for path in sorted(TEMPLATES.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append({"id": data["template_id"], "name": data.get("name", data["template_id"]),
                          "fields": len(data.get("fields", [])), "tables": len(data.get("tables", []))})
        except (ValueError, KeyError):
            continue
    return jsonify({"templates": items})


@app.get("/api/templates/<template_id>")
def get_template(template_id):
    return jsonify(tpl.load(_template_path(template_id)))


@app.post("/api/templates")
def save_template():
    body = request.get_json()
    template = body["template"]
    if body.get("reference"):
        tpl.finalize(template, _doc(body["reference"]))
    path = tpl.save(template, _template_path(template["template_id"]))
    return jsonify({"saved": str(path)})


def _run_job(run_id: str, templates: list[dict], docs: list[str]) -> None:
    run = _runs[run_id]
    for doc_id in docs:
        path = _doc_path(doc_id)
        name = path.name.split("__", 1)[-1]
        run["current"] = name
        result = parse_best(path, templates)
        result.update(file=name, doc_id=doc_id)
        run["results"].append(result)
        run["done"] += 1
    run["finished"] = True


@app.post("/api/runs")
def start_run():
    body = request.get_json()
    if not body.get("template_ids"):
        return _error("請先選擇範本")
    if not body.get("docs"):
        return _error("請先加入 PDF")
    templates = [tpl.load(_template_path(template_id)) for template_id in body["template_ids"]]
    run_id = uuid.uuid4().hex
    _runs[run_id] = {"total": len(body["docs"]), "done": 0, "current": "", "results": [], "finished": False}
    _run_templates[run_id] = {t["template_id"]: t for t in templates}
    threading.Thread(target=_run_job, args=(run_id, templates, body["docs"]), daemon=True).start()
    return jsonify({"run_id": run_id})


@app.get("/api/runs/<run_id>")
def run_status(run_id):
    return jsonify(_runs[run_id])


@app.post("/api/runs/<run_id>/edit")
def edit_value(run_id):
    """人工修正或確認。原值保留，方便回頭查。"""
    body = request.get_json()
    result = _runs[run_id]["results"][body["file_index"]]
    value = find_value(result, body["ref"])
    if value is None:
        return _error("找不到這個項目")
    if body["action"] == "confirm":
        value["status"], value["reasons"] = "confirmed", []
    else:
        value.setdefault("original", value["value"])
        value["value"], value["status"], value["reasons"] = body["value"], "corrected", []
        value["source"] = "manual"
    summarize(result)
    return jsonify(result)


@app.get("/api/runs/<run_id>/excel")
def export(run_id):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = write_excel(_runs[run_id]["results"], OUTPUT / f"解析結果_{stamp}.xlsx")
    return send_file(path, as_attachment=True, download_name=path.name)


@app.get("/api/runs/<run_id>/clean")
def export_clean(run_id):
    stamp = time.strftime("%Y%m%d_%H%M%S")
    only_confirmed = request.args.get("only_confirmed") == "1"
    path = write_clean(_runs[run_id]["results"], _run_templates.get(run_id, {}),
                       OUTPUT / f"乾淨資料_{stamp}.xlsx", only_confirmed)
    return send_file(path, as_attachment=True, download_name=path.name)


def _clear_uploads() -> None:
    with _docs_lock:
        for doc in _docs.values():
            doc.close()
        _docs.clear()
    shutil.rmtree(UPLOADS, ignore_errors=True)


def _busy() -> bool:
    return any(not run["finished"] for run in _runs.values())


def _shutdown(reason: str) -> None:
    print(f"\n  {reason}，工具已關閉。\n", flush=True)
    _clear_uploads()
    os._exit(0)  # 結束整個行程，連接埠、檔案和記憶體都由系統回收


def _watch_clients() -> None:
    """所有頁面都關閉後自動結束，避免背景程式一直留著。"""
    started = last_tick = time.time()
    empty_since: float | None = None
    seen_client = False
    while True:
        time.sleep(WATCH_SECONDS)
        now = time.time()
        with _clients_lock:
            if now - last_tick > SLEEP_GAP_SECONDS:  # 睡眠期間頁面也無法回報，不算離線
                for client in _clients:
                    _clients[client] = now
            for client, seen in list(_clients.items()):
                if now - seen > CLIENT_TIMEOUT_SECONDS:
                    del _clients[client]
            seen_client = seen_client or bool(_clients)
            active = bool(_clients)
        last_tick = now
        if active or _busy():
            empty_since = None
            continue
        if not seen_client:
            if now - started > NO_CLIENT_TIMEOUT_SECONDS:
                _shutdown("沒有開啟頁面")
            continue
        empty_since = empty_since or now
        if now - empty_since >= CLOSE_GRACE_SECONDS:
            _shutdown("頁面已全部關閉")


def _port_is_free(port: int) -> bool:
    with socket.socket() as probe:
        if os.name != "nt":  # Windows 的這個選項會允許搶佔使用中的埠，不能設定
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _is_this_tool(port: int) -> bool:
    # 不走系統代理：公司電腦常設 HTTP_PROXY，會讓 127.0.0.1 的檢查失敗
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/ping", timeout=2) as response:
            data = json.loads(response.read())
    except (OSError, ValueError):
        return False
    return data.get("app") == "pdfmapper" and data.get("root") == str(ROOT)


def _pick_port(start: int) -> tuple[int, bool]:
    """回傳 (埠, 工具是否已在這個埠上執行)。"""
    for port in range(start, start + PORT_RANGE):
        if _port_is_free(port):
            return port, False
        if _is_this_tool(port):
            return port, True
    raise OSError(f"連接埠 {start} 到 {start + PORT_RANGE - 1} 都被其他程式佔用")


def serve(port: int = 8765, open_browser: bool = True) -> None:
    TEMPLATES.mkdir(exist_ok=True)
    for attempt in range(3):
        chosen, running = _pick_port(port)
        url = f"http://127.0.0.1:{chosen}"
        if running:
            print(f"\n  工具已經開著，直接開啟 {url}\n", flush=True)
            if open_browser:
                webbrowser.open(url)
            return
        if attempt == 0:
            shutil.rmtree(UPLOADS, ignore_errors=True)  # 清掉上次異常結束留下的暫存
        print(f"\n  PDF 解析器已啟動：{url}\n  使用完畢後關閉瀏覽器頁面，或關閉這個視窗。\n", flush=True)
        if open_browser:
            threading.Timer(0.8, webbrowser.open, args=(url,)).start()
            threading.Thread(target=_watch_clients, daemon=True).start()
        threading.Thread(target=ocr_engine.available, daemon=True).start()  # 先載入模型
        try:
            app.run(host="127.0.0.1", port=chosen, threaded=True)
            return
        except (OSError, SystemExit):  # 兩次啟動幾乎同時發生，等一下再判斷
            time.sleep(1)
    raise SystemExit("無法啟動工具，請關閉其他視窗後再試一次。")
