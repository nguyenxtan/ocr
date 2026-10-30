"""Optional Docker-internal OCR with a per-PDF budget, never an external API."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import math
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import cv2
import numpy as np

from app.paddle_contract import OCRLine, parse_service_response


class PaddleUnavailable(Exception):
    """Optional OCR engine offline, slow, or malformed response."""


@dataclass
class _PaddleBudget:
    remaining_s: float
    offline: bool = False
    unavailable_modes: set[str] = field(default_factory=set)


_budget: ContextVar[_PaddleBudget | None] = ContextVar("paddle_pdf_budget", default=None)


@contextmanager
def paddle_request_budget(total_timeout_s: float | None = None):
    """All optional requests for ONE PDF share a wait allowance.

    Transport failure closes only this PDF's circuit. The next PDF may retry.
    No text, images or success decisions are cached across users. Nested calls
    share the outer budget. The worker process still enforces its hard deadline.
    """
    if _budget.get() is not None:
        yield
        return
    seconds = (float(os.getenv("PADDLE_TOTAL_TIMEOUT_SEC", "18"))
               if total_timeout_s is None else float(total_timeout_s))
    if not math.isfinite(seconds) or not 1 <= seconds <= 300:
        raise ValueError("PADDLE_TOTAL_TIMEOUT_SEC must be between 1 and 300")
    token = _budget.set(_PaddleBudget(seconds))
    try:
        yield
    finally:
        _budget.reset(token)


def endpoint_from_env() -> str | None:
    endpoint = os.environ.get("PADDLE_ENDPOINT", "").strip().rstrip("/")
    if not endpoint:
        return None
    url = urlparse(endpoint)
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
    budget = _budget.get()
    if budget and (budget.offline or budget.remaining_s <= 0 or mode in budget.unavailable_modes):
        raise PaddleUnavailable("Paddle unavailable or budget exhausted for this PDF")
    if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.size > 18_000_000:
        raise PaddleUnavailable("Image too large")
    ok, encoded = cv2.imencode(".png", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    if not ok or len(encoded) > 2_000_000:
        raise PaddleUnavailable("Image too large for sidecar")
    seconds = float(os.getenv("PADDLE_TIMEOUT_SEC", "18")) if timeout_s is None else float(timeout_s)
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("PADDLE_TIMEOUT_SEC must be positive and finite")
    if budget:
        seconds = min(seconds, budget.remaining_s)
    request = Request(endpoint + "/v1/" + mode, data=encoded.tobytes(),
                      headers={"Content-Type": "image/png"}, method="POST")
    started = time.monotonic()
    try:
        with urlopen(request, timeout=seconds) as response:
            if response.status != 200:
                if budget:
                    budget.unavailable_modes.add(mode)
                raise PaddleUnavailable("OCR backend unavailable")
            raw = response.read(65537)
    except HTTPError as error:
        # An unavailable seal model must not disable a working general model.
        if budget:
            budget.unavailable_modes.add(mode)
        raise PaddleUnavailable(type(error).__name__) from error
    except (URLError, OSError, TimeoutError) as error:
        if budget:
            budget.offline = True
        raise PaddleUnavailable(type(error).__name__) from error
    finally:
        if budget:
            budget.remaining_s = max(0.0, budget.remaining_s - (time.monotonic() - started))
    if len(raw) > 65536:
        if budget:
            budget.unavailable_modes.add(mode)
        raise PaddleUnavailable("OCR response too large")
    try:
        return parse_service_response(json.loads(raw), mode)
    except (ValueError, TypeError, UnicodeError) as error:
        if budget:
            budget.unavailable_modes.add(mode)
        raise PaddleUnavailable("Malformed OCR response") from error


def seal_as_rgb(mask: np.ndarray) -> np.ndarray:
    """Reconstruct red ink on white from isolated seal pixels, never doc text."""
    if mask.ndim != 2 or mask.size == 0:
        raise ValueError("Invalid stamp crop")
    rgb = np.full((*mask.shape, 3), 255, dtype=np.uint8)
    rgb[mask > 0] = (178, 44, 45)
    return rgb
