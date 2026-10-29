import io
import os
from unittest.mock import patch
from urllib.error import URLError

import numpy as np
import pytest

from app.paddle_gateway import PaddleUnavailable, endpoint_from_env, post_image, seal_as_rgb


def test_no_ocr_server_is_default(monkeypatch):
    monkeypatch.delenv("PADDLE_ENDPOINT", raising=False)
    assert endpoint_from_env() is None
    with pytest.raises(PaddleUnavailable):
        post_image(np.zeros((10, 10, 3), np.uint8), "general")


@pytest.mark.parametrize("address", [
    "https://example.com/api", "http://evil.net:8877", "http://127.0.0.1:1234", "file:///etc/passwd",
    "http://paddle:8877/private", "http://user@paddle:8877",
])
def test_ocr_endpoint_cannot_send_private_files_to_remote_host(monkeypatch, address):
    monkeypatch.setenv("PADDLE_ENDPOINT", address)
    with pytest.raises(ValueError):
        endpoint_from_env()


def test_local_private_ocr_host_allowed(monkeypatch):
    monkeypatch.setenv("PADDLE_ENDPOINT", "http://paddle:8877")
    assert endpoint_from_env() == "http://paddle:8877"


def test_gateway_handles_ocr_failure_without_returning_fake_text(monkeypatch):
    monkeypatch.setenv("PADDLE_ENDPOINT", "http://paddle:8877")
    with patch("app.paddle_gateway.urlopen", side_effect=URLError("offline")):
        with pytest.raises(PaddleUnavailable):
            post_image(np.zeros((32, 32, 3), np.uint8), "seal")


def test_stamp_mask_becomes_red_ink_on_white():
    mask = np.zeros((5, 5), np.uint8)
    mask[2, 2] = 255
    image = seal_as_rgb(mask)
    assert image[0,0].tolist() == [255,255,255]
    assert image[2,2].tolist() == [178,44,45]
