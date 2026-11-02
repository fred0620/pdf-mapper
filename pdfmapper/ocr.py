"""OCR 包裝層。之後要換引擎，只需改這個檔案。"""
from __future__ import annotations

import logging
import threading

import cv2
import numpy as np

_engine = None
_lock = threading.Lock()
_import_error: str | None = None
_PADDING = 24


def available() -> bool:
    return _get_engine() is not None


def status() -> str | None:
    """無法使用時回傳原因。"""
    _get_engine()
    return _import_error


def _get_engine():
    global _engine, _import_error
    if _engine is not None or _import_error is not None:
        return _engine
    with _lock:
        if _engine is None and _import_error is None:
            try:
                from rapidocr import RapidOCR

                logging.getLogger("RapidOCR").setLevel(logging.ERROR)
                _engine = RapidOCR(params={
                    "Global.log_level": "error",
                    # 預設會把小圖放大到 736 像素，裁切區塊會慢上數倍
                    "Det.limit_type": "max",
                    "Det.limit_side_len": 1600,
                })
            except Exception as exc:  # 缺套件或模型損毀時，文字層仍可運作
                _import_error = str(exc)
    return _engine


def read(image: np.ndarray) -> list[tuple[str, tuple[float, float, float, float], float]]:
    """回傳 (文字, 像素框, 信心)。image 為 RGB，座標以原圖為準。"""
    engine = _get_engine()
    if engine is None or image.size == 0:
        return []
    bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
    padded = cv2.copyMakeBorder(
        bgr, _PADDING, _PADDING, _PADDING, _PADDING, cv2.BORDER_CONSTANT, value=(255, 255, 255)
    )
    with _lock:
        # 每次都要明確指定：RapidOCR 會記住上一次呼叫的開關，
        # 否則單行模式之後，偵測會一直被關掉。
        output = engine(padded, use_det=True, use_cls=False, use_rec=True)
    boxes = getattr(output, "boxes", None)
    if boxes is None or not len(boxes):
        return _read_single_line(engine, padded, image.shape)
    lines = []
    for quad, text, score in zip(boxes, output.txts, output.scores):
        quad = np.asarray(quad, dtype=float) - _PADDING
        lines.append(
            (
                str(text),
                (float(quad[:, 0].min()), float(quad[:, 1].min()),
                 float(quad[:, 0].max()), float(quad[:, 1].max())),
                float(score),
            )
        )
    return lines


def _read_single_line(engine, padded: np.ndarray, shape) -> list:
    """偵測不到文字框時（很小的裁切常見），把整塊當成一行再辨識一次。"""
    with _lock:
        output = engine(padded, use_det=False, use_cls=False, use_rec=True)
    texts = getattr(output, "txts", None)
    if not texts or not str(texts[0]).strip():
        return []
    return [(str(texts[0]), (0.0, 0.0, float(shape[1]), float(shape[0])), float(output.scores[0]))]
