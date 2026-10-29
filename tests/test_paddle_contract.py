"""Offline fixtures from official PaddleOCR 3.x JSON response shapes."""
import math
import numpy as np
import pytest

from app.paddle_contract import parse_predict_output, parse_service_response, safe_response, OCRLine


def test_pp_ocrv6_predict_json_parsing():
    payload = {"res": {"rec_texts": ["CÔNG TY CỔ PHẦN", "3501556139"],
                       "rec_scores": np.array([.94, .991]),
                       "input_path": "/private/document.pdf"}}
    result = parse_predict_output(payload, "general")
    assert [r.text for r in result] == ["CÔNG TY CỔ PHẦN", "3501556139"]
    assert result[1].score == pytest.approx(.991)


def test_seal_recognition_nested_json():
    payload = {"res": {"seal_res_list": [
        {"rec_texts": ["TÂN CẢNG CYPRESS"], "rec_scores": np.array([.96])},
        {"rec_texts": ["3501556139"], "rec_scores": np.array([.98])},
    ], "layout_det_res": {"boxes": [{"label": "seal"}]}}}
    result = parse_predict_output(payload, "seal")
    assert [r.text for r in result] == ["TÂN CẢNG CYPRESS", "3501556139"]


def test_metadata_or_unscored_text_never_counts_as_ocr():
    x = {"res": {"rec_texts": ["CYPRESS"], "input_path": "CYPRESS"}}
    assert parse_predict_output(x, "general") == []
    assert parse_predict_output({"res": {"rec_texts": ["TAN"], "rec_scores": [float("nan")]}}, "general") == []


def test_response_roundtrip_and_size_cap():
    rows = [OCRLine("TÂN CẢNG", 0.892)]
    assert parse_service_response(safe_response(rows, "general"), "general") == [OCRLine("TÂN CẢNG", 0.892)]
    assert not parse_service_response({"mode": "general", "lines": [{"text": "TAN", "score": True}]}, "general")


def test_response_rejects_wrong_mode():
    with pytest.raises(ValueError):
        parse_service_response({"mode": "seal", "lines": []}, "general")
    with pytest.raises(ValueError):
        parse_predict_output({}, "other")
