"""Pure, offline-safe adapters for PaddleOCR 3.x predict results.

Only recognized text and scores are extracted. Never treat layout labels,
filenames, model prompts, or metadata as OCR evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math


@dataclass(frozen=True)
class OCRLine:
    text: str
    score: float


def _mapping(result: Any) -> dict:
    if not isinstance(result, dict):
        return {}
    # PaddleOCR Res.json exposes {'res': {...}}, while the server's own
    # result/JSON may include the inner object directly.
    return result.get("res", result) if isinstance(result.get("res", result), dict) else {}


def parse_predict_output(result: Any, mode: str) -> list[OCRLine]:
    """Parse PP-OCRv6 rec_texts and SealRecognition seal_res_list.

    Each text must have its corresponding finite confidence. Missing scores are
    not counted as evidence (avoid accidentally accepting metadata strings).
    """
    if mode not in {"general", "seal"}:
        raise ValueError("Unsupported OCR mode")
    data = _mapping(result)
    if mode == "general":
        groups = [data]
    else:
        groups = data.get("seal_res_list", [])
        if not isinstance(groups, list):
            groups = []
        # Accept an independently isolated seal result payload too.
        if not groups and isinstance(data.get("rec_texts"), list) and data.get("text_type") == "seal":
            groups = [data]
    extracted: list[OCRLine] = []
    for group in groups[:16]:
        if not isinstance(group, dict):
            continue
        texts, scores = group.get("rec_texts"), group.get("rec_scores")
        if texts is None or scores is None or isinstance(texts, (str, bytes)):
            continue
        try:
            scores = list(scores)
            texts = list(texts)
        except (TypeError, ValueError):
            continue
        for text, score in zip(texts[:100], scores[:100]):
            if not isinstance(text, str) or not 1 <= len(text.strip()) <= 256:
                continue
            try:
                score = float(score)
            except (ValueError, TypeError):
                continue
            if not math.isfinite(score) or score < 0 or score > 1:
                continue
            extracted.append(OCRLine(text.strip(), score))
    return extracted[:150]


def safe_response(lines: list[OCRLine], mode: str) -> dict:
    return {
        "mode": mode,
        "lines": [{"text": item.text, "score": round(item.score, 5)} for item in lines],
    }


def parse_service_response(data: Any, mode: str) -> list[OCRLine]:
    if not isinstance(data, dict) or data.get("mode") != mode or not isinstance(data.get("lines"), list):
        raise ValueError("Invalid Paddle OCR response")
    out: list[OCRLine] = []
    for record in data["lines"][:150]:
        if not isinstance(record, dict):
            continue
        word, conf = record.get("text"), record.get("score")
        if not isinstance(word, str) or len(word) > 256 or not word.strip():
            continue
        if isinstance(conf, bool):
            continue
        if not isinstance(conf, (int, float)) or not math.isfinite(conf) or not 0 <= conf <= 1:
            continue
        out.append(OCRLine(word.strip(), float(conf)))
    return out
