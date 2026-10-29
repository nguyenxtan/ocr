"""Optional local-only PP-OCRv6 / SealRecognition sidecar.

Model weights download at first boot and are cached in a Docker volume.
The OCR API is reachable only on the private Compose network, never published.
"""
from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import numpy as np

from app.paddle_contract import parse_predict_output, safe_response

log = logging.getLogger("paddle-service")


class Engines:
    def __init__(self):
        self.general = None
        self.seal = None
        # Avoid loading Paddlex in the base container.
        from paddleocr import PaddleOCR, SealRecognition

        self.general = PaddleOCR(
            lang="vi", ocr_version="PP-OCRv6", device="cpu",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        try:
            self.seal = SealRecognition(
                device="cpu", use_doc_orientation_classify=False,
                use_doc_unwarping=False, use_layout_detection=False,
                seal_text_detection_model_name="PP-OCRv4_mobile_seal_det",
                text_recognition_model_name="PP-OCRv6_medium_rec",
            )
        except Exception as exc:  # optional pipeline may be unavailable
            log.warning("Seal pipeline unavailable (%s)", type(exc).__name__)

    def predict(self, image: np.ndarray, mode: str) -> dict:
        pipeline = self.general if mode == "general" else self.seal
        if pipeline is None:
            raise RuntimeError("Requested Paddle model not ready")
        result = []
        for prediction in pipeline.predict(image):
            json_value = getattr(prediction, "json", None)
            result.extend(parse_predict_output(json_value, mode))
        return safe_response(result[:150], mode)


class Handler(BaseHTTPRequestHandler):
    engines: Engines | None = None

    def log_message(self, _format, *_args):
        # No user-controlled PDF text, filenames, or byte payloads in logs.
        return

    def _json(self, status: int, data: dict):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path != "/health":
            return self._json(404, {"ok": False})
        self._json(200 if self.engines and self.engines.general else 503, {
            "ok": bool(self.engines and self.engines.general),
            "general": bool(self.engines and self.engines.general),
            "seal": bool(self.engines and self.engines.seal),
        })

    def do_POST(self):
        mode = self.path.removeprefix("/v1/") if self.path.startswith("/v1/") else ""
        if mode not in ("general", "seal"):
            return self._json(404, {"ok": False})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self._json(400, {"ok": False})
        if self.headers.get("Content-Type") != "image/png" or not 0 < length <= 2_000_000:
            return self._json(413, {"ok": False})
        body = self.rfile.read(length)
        if len(body) != length:
            return self._json(400, {"ok": False})
        img = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None or img.ndim != 3 or img.size > 18_000_000:
            return self._json(400, {"ok": False})
        try:
            if not self.engines:
                raise RuntimeError("No OCR models")
            return self._json(200, self.engines.predict(img, mode))
        except Exception as exc:
            log.warning("OCR backend error (%s)", type(exc).__name__)
            return self._json(503, {"ok": False})


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    Handler.engines = Engines()
    port = int(os.getenv("PADDLE_PORT", "8877"))
    log.info("PaddleOCR private service ready on %s", port)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
