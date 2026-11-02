"""本機網頁工具的後端。只綁定 127.0.0.1，檔案不會離開這台電腦。"""
from __future__ import annotations

import io
import json
import re
import shutil
import threading
import time
import uuid
import webbrowser
from pathlib import Path

import cv2
from flask import Flask, jsonify, request, send_file, send_from_directory

from . import ocr as ocr_engine
from . import template as tpl
from .document import Document
from .excel import write_excel
from .extract import REASONS, read_box
from .parser import find_value, parse_pdf, summarize

ROOT = Path(__file__).resolve().parent.parent
WEB = Path(__file__).resolve().parent / "web"
WORKSPACE = ROOT / "workspace"
UPLOADS = WORKSPACE / "uploads"
TEMPLATES = ROOT / "templates"
OUTPUT = ROOT / "output"
PREVIEW_DPI = 120
MAX_OPEN_DOCS = 8

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024

_docs: dict[str, Document] = {}
_docs_lock = threading.Lock()
_runs: dict[str, dict] = {}


def _doc_path(doc_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", doc_id):
        raise FileNotFoundError(doc_id)
    matches = list(UPLOADS.glob(f"{doc_id}__*"))
    if not matches:
        raise FileNotFoundError(doc_id)
    return matches[0]


def _doc(doc_id: str) -> Document:
    with _docs_lock:
        if doc_id not in _docs:
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


def _run_job(run_id: str, template: dict, docs: list[str]) -> None:
    run = _runs[run_id]
    for doc_id in docs:
        path = _doc_path(doc_id)
        name = path.name.split("__", 1)[-1]
        run["current"] = name
        result = parse_pdf(path, template)
        result.update(file=name, doc_id=doc_id)
        run["results"].append(result)
        run["done"] += 1
    run["finished"] = True


@app.post("/api/runs")
def start_run():
    body = request.get_json()
    template = tpl.load(_template_path(body["template_id"]))
    if not body.get("docs"):
        return _error("請先加入 PDF")
    run_id = uuid.uuid4().hex
    _runs[run_id] = {"total": len(body["docs"]), "done": 0, "current": "", "results": [], "finished": False}
    threading.Thread(target=_run_job, args=(run_id, template, body["docs"]), daemon=True).start()
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


@app.post("/api/clear")
def clear_workspace():
    with _docs_lock:
        for doc in _docs.values():
            doc.close()
        _docs.clear()
    _runs.clear()
    shutil.rmtree(UPLOADS, ignore_errors=True)
    return jsonify({"cleared": True})


def serve(port: int = 8765, open_browser: bool = True) -> None:
    import socket

    TEMPLATES.mkdir(exist_ok=True)
    for candidate in range(port, port + 20):
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", candidate)) != 0:
                port = candidate
                break
    url = f"http://127.0.0.1:{port}"
    print(f"\n  PDF 解析器已啟動：{url}\n  使用完畢後關閉這個視窗即可。\n")
    if open_browser:
        threading.Timer(0.8, webbrowser.open, args=(url,)).start()
    threading.Thread(target=ocr_engine.available, daemon=True).start()  # 先載入模型
    app.run(host="127.0.0.1", port=port, threaded=True)
