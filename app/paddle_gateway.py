"""Optional Docker-internal PaddleOCR gateway. The base bot never needs Paddle.

No internet API, no document logging, and no silent external OCR fallback.
"""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import cv2
import numpy as np

from app.paddle_contract import OCRLine, parse_service_response


class PaddleUnavailable(Exception):
    """Optional OCR engine offline, slow, or malformed response."""


def endpoint_from_env() -> str | None:
    endpoint = os.environ.get("PADDLE_ENDPOINT", "").strip().rstrip("/")
    if not endpoint:
        return None
    url = urlparse(endpoint)
    # Never let an OCR error silently send private PDFs to a third party.
    if url.scheme != "http" or url.hostname not in ("paddle", "localhost", "127.0.0.1") or url.path or url.query or url.username:
        raise ValueError("PADDLE_ENDPOINT must be a private local Paddle service")
    if url.port not in (None, 8877):
        raise ValueError("Unsupported OCR sidecar port")
    return endpoint


def post_image(rgb: np.ndarray, mode: str, *, timeout_s: float | None = None) -> list[OCRLine]:
    endpoint = endpoint_from_env()
    if not endpoint:
        raise PaddleUnavailable("Paddle service disabled")
    if mode not in {"seal", "general"}:
        raise ValueError("Unsupported OCR mode")
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.size > 18_000_000:
        raise PaddleUnavailable("Image too large")
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok or len(encoded) > 2_000_000:
        raise PaddleUnavailable("Image too large for sidecar")
    seconds = timeout_s or float(os.getenv("PADDLE_TIMEOUT_SEC", "18"))
    body = encoded.tobytes()
    request = Request(
        endpoint + "/v1/" + mode,
        data=body,
        headers={"Content-Type": "image/png"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=seconds) as response:
            if response.status != 200:
                raise PaddleUnavailable("OCR backend unavailable")
            raw = response.read(65537)
    except (URLError, HTTPError, OSError, TimeoutError) as e:
        raise PaddleUnavailable(type(e).__name__) from e
    if len(raw) > 65536:
        raise PaddleUnavailable("OCR response too large")
    try:
        return parse_service_response(json.loads(raw), mode)
    except (ValueError, TypeError, UnicodeError) as e:
        raise PaddleUnavailable("Malformed OCR response") from e


def seal_as_rgb(mask: np.ndarray) -> np.ndarray:
    """Reconstruct red ink on white from *isolated* seal mask, never doc text."""
    if mask.ndim != 2 or mask.size == 0:
        raise ValueError("Invalid stamp crop")
    rgb = np.full((*mask.shape, 3), 255, dtype=np.uint8)
    rgb[mask > 0] = (178, 44, 45)
    return rgb
