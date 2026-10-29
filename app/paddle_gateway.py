"""Optional Docker-internal PaddleOCR gateway. The base bot never needs Paddle.

No internet API, no document logging, and no silent external OCR fallback.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import cv2
import numpy as np

from app.paddle_contract import OCRLine, parse_service_response


class PaddleUnavailable(Exception):
    """Optional OCR engine offline, slow, or malformed response."""


@dataclass
class _RequestBudget:
    remaining: float
    unavailable: bool = False


_budget: ContextVar[_RequestBudget | None] = ContextVar("paddle_request_budget", default=None)


@contextmanager
def request_budget():
    """Bound optional remote OCR per PDF, resetting on the next document.

    Counts only time inside sidecar calls, not intervening local OCR. Never
    caches document bytes or shares failure state between users/documents.
    """
    seconds = float(os.getenv("PADDLE_BUDGET_SEC", "8"))
    if not 0 <= seconds <= 60:
        raise ValueError("PADDLE_BUDGET_SEC must be between 0 and 60")
    token = _budget.set(_RequestBudget(seconds))
    try:
        yield
    finally:
        _budget.reset(token)


def post_image(rgb: np.ndarray, mode: str, *, timeout_s: float | None = None) -> list[OCRLine]:
    budget = _budget.get()
    seconds = timeout_s if timeout_s is not None else float(os.getenv("PADDLE_TIMEOUT_SEC", "18"))
    if seconds <= 0:
        raise ValueError("Paddle timeout must be positive")
    if budget is not None:
        if budget.unavailable or budget.remaining <= 0:
            raise PaddleUnavailable("Paddle budget exhausted or service unavailable for this PDF")
        seconds = min(seconds, budget.remaining)
    started = time.monotonic()
    try:
        result = _post_image(rgb, mode, timeout_s=seconds)
        # Socket timeouts can apply to individual operations. Do not accept a
        # late response as if it were within the optional processing budget.
        if budget is not None and time.monotonic() - started > seconds:
            raise PaddleUnavailable("Paddle request exceeded its remaining budget")
        return result
    except PaddleUnavailable:
        if budget is not None:
            budget.unavailable = True
        raise
    finally:
        if budget is not None:
            budget.remaining = max(0.0, budget.remaining - (time.monotonic() - started))


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


def _post_image(rgb: np.ndarray, mode: str, *, timeout_s: float | None = None) -> list[OCRLine]:
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
