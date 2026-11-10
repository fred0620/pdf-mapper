"""本機網頁工具的後端。只綁定 127.0.0.1，檔案不會離開這台電腦。"""
from __future__ import annotations

import hashlib
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
from werkzeug.exceptions import HTTPException

from . import __version__, logs, paths
from . import ocr as ocr_engine
from . import template as tpl
from .clean import write_clean
from .document import Document
from .excel import write_excel
from .extract import REASONS, read_box
from .logs import clean as log_text
from .logs import log
from .parser import find_value, parse_best, parse_pdf, summarize

WEB = Path(__file__).resolve().parent / "web"
UPLOADS = paths.UPLOADS
TEMPLATES = paths.TEMPLATES
OUTPUT = paths.OUTPUT
LOGS = paths.LOGS
PREVIEW_DPI = 120
MIN_DPI, MAX_DPI = 30, 220
MAX_OPEN_DOCS = 8
MAX_RUNS = 20                # 保留最近幾次解析結果，舊的釋放記憶體
MAX_CLIENTS = 50
MAX_NAME_LENGTH = 120
MAX_EDIT_LENGTH = 10000
PORT_RANGE = 20
CLOSE_GRACE_SECONDS = 8      # 容許重新整理頁面，不會誤關
CLIENT_TIMEOUT_SECONDS = 1800  # 瀏覽器當掉、沒通知就消失時的上限
NO_CLIENT_TIMEOUT_SECONDS = 600  # 啟動後一直沒有開啟頁面
WATCH_SECONDS = 2
SLEEP_GAP_SECONDS = 30       # 檢查間隔突然變長，代表電腦剛從睡眠醒來

# 只接受本機名稱，擋掉 DNS rebinding（外部網域解析成 127.0.0.1 再來讀資料）
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
UNSAFE_NAME = re.compile(r'[\x00-\x1f\x7f<>:"/\\|?*]')
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; "
       "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
ROOT_ID = hashlib.sha256(str(paths.HOME).encode("utf-8")).hexdigest()[:16]  # 不把完整路徑（含使用者名稱）傳出去

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 300 * 1024 * 1024

_docs: dict[str, Document] = {}
_docs_lock = threading.Lock()
_runs: dict[str, dict] = {}
_run_templates: dict[str, dict[str, dict]] = {}  # 含影像圖塊，不放進回傳給頁面的資料
_clients: dict[str, float] = {}
_clients_lock = threading.Lock()
_runs_lock = threading.Lock()


class Missing(Exception):
    """找不到使用者要的東西，訊息會直接顯示在頁面上。"""


def _doc_path(doc_id: str) -> Path:
    if not isinstance(doc_id, str) or not re.fullmatch(r"[0-9a-f]{32}", doc_id):
        raise FileNotFoundError("doc_id")
    matches = [p for p in UPLOADS.glob(f"{doc_id}__*") if p.parent == UPLOADS and p.is_file()]
    if not matches:
        raise FileNotFoundError("doc_id")
    return matches[0]


def _run(run_id: str) -> dict:
    run = _runs.get(run_id)
    if run is None:
        raise Missing("找不到這次解析結果，請重新解析")
    return run


def _safe_name(raw: str | None) -> str:
    """上傳檔名只保留檔名本身，去掉路徑、控制字元與 Windows 不允許的字元。"""
    name = Path((raw or "").replace("\\", "/")).name
    name = UNSAFE_NAME.sub("_", name).strip(" .")
    if len(name) > MAX_NAME_LENGTH:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:MAX_NAME_LENGTH - len(ext) - 1] + dot + ext) if dot and len(ext) <= 8 else name[:MAX_NAME_LENGTH]
    return name or "file.pdf"


def _looks_like_pdf(item) -> bool:
    head = item.stream.read(1024)
    item.stream.seek(0)
    return b"%PDF-" in head


def _json_body() -> dict:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError("請求內容格式不正確")
    return body


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
    if not isinstance(template_id, str) or not re.fullmatch(r"[\w\-]{1,64}", template_id):
        raise ValueError("範本代號只能用文字、數字、底線與連字號，最多 64 個字")
    if template_id.lower() in WINDOWS_RESERVED:
        raise ValueError("這個範本代號是 Windows 保留名稱，請換一個")
    return TEMPLATES / f"{template_id}.json"


def _error(message: str, code: int = 400):
    return jsonify({"error": message}), code


def _is_local(netloc: str) -> bool:
    host = netloc.rsplit(":", 1)[0] if not netloc.endswith("]") else netloc
    return host.lower() in LOCAL_HOSTS


@app.before_request
def _guard():
    """本機服務也會被瀏覽器裡其他網站呼叫，這裡擋掉非本工具頁面發出的請求。"""
    if not _is_local(request.host):
        log.warning("拒絕請求：Host 不是本機 host=%s path=%s", log_text(request.host), log_text(request.path))
        return _error("只接受本機連線", 403)
    if not request.path.startswith("/api/"):
        return None
    site = request.headers.get("Sec-Fetch-Site")
    if site and site not in ("same-origin", "none"):
        log.warning("拒絕請求：跨站呼叫 site=%s path=%s", log_text(site), log_text(request.path))
        return _error("只接受本工具頁面發出的請求", 403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("Origin")
        if origin is not None and origin.split("://", 1)[-1] != request.host:
            log.warning("拒絕請求：來源不符 origin=%s path=%s", log_text(origin), log_text(request.path))
            return _error("只接受本工具頁面發出的請求", 403)
    return None


@app.after_request
def _headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    if response.mimetype == "text/html":
        response.headers["Content-Security-Policy"] = CSP
    if request.path.startswith("/api/") and not request.path.endswith(".png"):
        response.headers["Cache-Control"] = "no-store"  # 資料與匯出檔不留在瀏覽器快取
    return response


@app.errorhandler(FileNotFoundError)
def _not_found(_exc):
    return _error("找不到這個檔案，請重新加入 PDF", 404)


@app.errorhandler(Missing)
def _missing(exc):
    return _error(str(exc), 404)


@app.errorhandler(ValueError)
def _bad_value(exc):
    log.info("輸入不正確 path=%s：%s", log_text(request.path), log_text(exc, 300))
    return _error(str(exc))


@app.errorhandler(HTTPException)
def _http_error(exc):
    messages = {404: "找不到這個頁面", 405: "不支援這個操作", 413: "檔案太大，請分批加入"}
    return _error(messages.get(exc.code, "請求無法處理"), exc.code or 400)


@app.errorhandler(Exception)
def _unexpected(exc):
    """其他錯誤只回一般訊息，細節（含程式位置）只寫進本機日誌。"""
    if isinstance(exc, (KeyError, TypeError, IndexError)):
        log.warning("請求內容不完整 path=%s", log_text(request.path), exc_info=exc)
        return _error("請求內容不完整，請重新整理頁面再試一次")
    log.error("處理請求時發生錯誤 path=%s", log_text(request.path), exc_info=exc)
    return _error("處理時發生錯誤，詳細內容已記錄在 workspace/logs", 500)


@app.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@app.get("/manual")
def manual():
    return send_from_directory(paths.MANUAL.parent, paths.MANUAL.name)


@app.get("/web/<path:name>")
def web_file(name):
    return send_from_directory(WEB, name)


@app.get("/api/ping")
def ping():
    """給第二次啟動判斷「工具是否已經開著」，不能碰到載入中的 OCR。"""
    return jsonify({"app": "pdfmapper", "root": ROOT_ID})


@app.post("/api/heartbeat")
def heartbeat():
    client = request.args.get("client", "")
    if not re.fullmatch(r"[\w\-]{1,64}", client):
        raise ValueError("連線代號不正確")
    with _clients_lock:
        if client not in _clients and len(_clients) >= MAX_CLIENTS:
            return _error("開啟的頁面太多，請關閉一些分頁", 429)
        _clients[client] = time.time()
    return jsonify({"ok": True})


@app.post("/api/bye")
def bye():
    with _clients_lock:
        _clients.pop(request.args.get("client", ""), None)
    return jsonify({"ok": True})


@app.get("/api/status")
def status():
    return jsonify({"ocr": ocr_engine.available(), "ocr_error": ocr_engine.status(), "reasons": REASONS,
                    "version": __version__})


@app.post("/api/docs")
def upload():
    UPLOADS.mkdir(parents=True, exist_ok=True)
    added, failed = [], []
    for item in request.files.getlist("files"):
        name = _safe_name(item.filename)
        if not _looks_like_pdf(item):
            failed.append({"name": name, "error": "不是 PDF 檔"})
            log.info("上傳拒絕：不是 PDF")
            continue
        doc_id = uuid.uuid4().hex
        target = UPLOADS / f"{doc_id}__{name}"
        item.save(target)
        try:
            added.append(_describe(doc_id, name))
            log.info("上傳 doc=%s size=%d", doc_id, target.stat().st_size)
        except Exception as exc:
            target.unlink(missing_ok=True)
            failed.append({"name": name, "error": "無法開啟，檔案可能損壞或有密碼保護"})
            log.warning("上傳失敗 doc=%s：%s", doc_id, type(exc).__name__, exc_info=exc)
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
    with _runs_lock:
        for run in _runs.values():
            run["results"] = [r for r in run["results"] if r.get("doc_id") != doc_id]
    log.info("移除 doc=%s", doc_id)
    return jsonify({"removed": doc_id})


@app.get("/api/docs/<doc_id>/page/<int:index>.png")
def page_image(doc_id, index):
    dpi = min(max(request.args.get("dpi", PREVIEW_DPI, type=int) or PREVIEW_DPI, MIN_DPI), MAX_DPI)
    doc = _doc(doc_id)
    if index >= len(doc.pages):
        raise Missing("沒有這一頁")
    image = doc.pages[index].render(dpi)
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("無法產生頁面圖片")
    response = send_file(io.BytesIO(encoded.tobytes()), mimetype="image/png", max_age=3600)
    response.cache_control.public = False
    response.cache_control.private = True  # 只留在這個瀏覽器，不給中間的代理快取
    return response


@app.post("/api/docs/<doc_id>/read")
def read_region(doc_id):
    body = _json_body()
    page = _doc(doc_id).pages[body["page"]]
    reading = read_box(page, tuple(body["box"]), body.get("source", "auto"))
    return jsonify({"text": reading.text, "lines": reading.lines, "source": reading.source,
                    "confidence": reading.confidence,
                    "notes": [REASONS.get(r, r) for r in reading.reasons]})


@app.post("/api/docs/<doc_id>/suggest-anchors")
def suggest(doc_id):
    body = _json_body()
    page = _doc(doc_id).pages[body["page"]]
    return jsonify({"anchors": tpl.suggest_anchors(page, body.get("avoid", []), body.get("page_rule", "first"))})




@app.post("/api/test")
def test_template():
    """用範例測試目前的範本（不存檔）。"""
    body = _json_body()
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
        except (ValueError, KeyError, TypeError, OSError):
            log.warning("略過無法讀取的範本 file=%s", log_text(path.name))
            continue
    return jsonify({"templates": items})


@app.get("/api/templates/<template_id>")
def get_template(template_id):
    return jsonify(tpl.load(_template_path(template_id)))


@app.post("/api/templates")
def save_template():
    body = _json_body()
    template = body["template"]
    if not isinstance(template, dict):
        raise ValueError("範本格式不正確")
    path = _template_path(template.get("template_id"))
    if body.get("reference"):
        tpl.finalize(template, _doc(body["reference"]))
    tpl.save(template, path)
    log.info("儲存範本 template=%s", template["template_id"])
    return jsonify({"saved": template["template_id"]})


def _failed_result(doc_id: str, name: str) -> dict:
    result = {"file": name, "doc_id": doc_id, "template_id": None, "template_name": "", "match": None,
              "fields": [], "tables": [], "error": "unexpected",
              "issues": [{"code": "failed", "page": None, "message": "無法解析這份 PDF，詳細內容已記錄在 workspace/logs"}]}
    summarize(result)
    return result


def _run_job(run_id: str, templates: list[dict], docs: list[str]) -> None:
    run = _runs[run_id]
    started = time.time()
    try:
        for doc_id in docs:
            name = ""
            try:
                path = _doc_path(doc_id)
                name = path.name.split("__", 1)[-1]
                run["current"] = name
                result = parse_best(path, templates)
                result.update(file=name, doc_id=doc_id)
            except Exception as exc:  # 一份失敗不能讓整批停住，否則頁面會一直顯示解析中
                log.error("解析失敗 run=%s doc=%s", run_id, log_text(doc_id, 40), exc_info=exc)
                result = _failed_result(str(doc_id), name)
            with _runs_lock:
                run["results"].append(result)
                run["done"] += 1
    finally:
        run["finished"] = True
        run["current"] = ""
        failed = sum(1 for r in run["results"] if r.get("status") == "failed")
        log.info("解析完成 run=%s files=%d failed=%d seconds=%.1f",
                 run_id, run["done"], failed, time.time() - started)


def _forget_old_runs() -> None:
    with _runs_lock:
        finished = [run_id for run_id, run in _runs.items() if run["finished"]]
        for run_id in finished[:max(0, len(_runs) - MAX_RUNS + 1)]:
            _runs.pop(run_id, None)
            _run_templates.pop(run_id, None)


@app.post("/api/runs")
def start_run():
    body = _json_body()
    if not body.get("template_ids"):
        return _error("請先選擇範本")
    if not body.get("docs"):
        return _error("請先加入 PDF")
    if not isinstance(body["docs"], list) or not isinstance(body["template_ids"], list):
        raise ValueError("請求內容格式不正確")
    docs = list(dict.fromkeys(body["docs"]))
    for doc_id in docs:
        _doc_path(doc_id)  # 先確認檔案都在，避免背景工作中途才失敗
    templates = [tpl.load(_template_path(template_id)) for template_id in body["template_ids"]]
    _forget_old_runs()
    run_id = uuid.uuid4().hex
    with _runs_lock:
        _runs[run_id] = {"total": len(docs), "done": 0, "current": "", "results": [], "finished": False}
        _run_templates[run_id] = {t["template_id"]: t for t in templates}
    log.info("開始解析 run=%s files=%d templates=%s", run_id, len(docs),
             ",".join(t["template_id"] for t in templates))
    threading.Thread(target=_run_job, args=(run_id, templates, docs), daemon=True).start()
    return jsonify({"run_id": run_id})


@app.get("/api/runs/<run_id>")
def run_status(run_id):
    run = _run(run_id)
    with _runs_lock:
        return jsonify(run)


@app.post("/api/runs/<run_id>/edit")
def edit_value(run_id):
    """人工修正或確認。原值保留，方便回頭查。"""
    body = _json_body()
    results = _run(run_id)["results"]
    index = body.get("file_index")
    if not isinstance(index, int) or not 0 <= index < len(results):
        raise Missing("找不到這份檔案的結果")
    result = results[index]
    value = find_value(result, body["ref"])
    if value is None:
        return _error("找不到這個項目")
    action = body.get("action")
    if action == "confirm":
        value["status"], value["reasons"] = "confirmed", []
    else:
        new = body.get("value")
        if not isinstance(new, str) or len(new) > MAX_EDIT_LENGTH:
            raise ValueError(f"修正的內容必須是文字，最多 {MAX_EDIT_LENGTH} 字")
        value.setdefault("original", value["value"])
        value["value"], value["status"], value["reasons"] = new, "corrected", []
        value["source"] = "manual"
    summarize(result)
    log.info("人工%s run=%s doc=%s", "確認" if action == "confirm" else "修正", run_id,
             log_text(result.get("doc_id", ""), 40))  # 不記錄修正的內容
    return jsonify(result)


@app.get("/api/runs/<run_id>/excel")
def export(run_id):
    run = _run(run_id)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = write_excel(run["results"], OUTPUT / f"解析結果_{stamp}.xlsx")
    log.info("匯出檢查用 Excel run=%s file=%s", run_id, path.name)
    return send_file(path, as_attachment=True, download_name=path.name)


@app.get("/api/runs/<run_id>/clean")
def export_clean(run_id):
    run = _run(run_id)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    only_confirmed = request.args.get("only_confirmed") == "1"
    path = write_clean(run["results"], _run_templates.get(run_id, {}),
                       OUTPUT / f"乾淨資料_{stamp}.xlsx", only_confirmed)
    log.info("匯出乾淨資料 run=%s file=%s only_confirmed=%s", run_id, path.name, only_confirmed)
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
    log.info("關閉：%s", reason)
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
    return data.get("app") == "pdfmapper" and data.get("root") == ROOT_ID


def _pick_port(start: int) -> tuple[int, bool]:
    """回傳 (埠, 工具是否已在這個埠上執行)。"""
    for port in range(start, start + PORT_RANGE):
        if _port_is_free(port):
            return port, False
        if _is_this_tool(port):
            return port, True
    raise OSError(f"連接埠 {start} 到 {start + PORT_RANGE - 1} 都被其他程式佔用")


def serve(port: int = 8765, open_browser: bool = True) -> None:
    notices = paths.prepare()
    logs.setup(LOGS)
    for notice in notices:
        print(f"  {notice}", flush=True)
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
        print(f"\n  PDF 解析器 {__version__} 已啟動：{url}\n  使用完畢後關閉瀏覽器頁面，或關閉這個視窗。\n", flush=True)
        log.info("啟動 version=%s port=%d", __version__, chosen)
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
