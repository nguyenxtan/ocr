"""Budget tests use a simulated clock, not model inference or real HTTP."""
from types import SimpleNamespace
from urllib.error import HTTPError
import numpy as np
import pytest
from app import paddle_gateway as gateway


@pytest.fixture
def image(monkeypatch):
    monkeypatch.setenv("PADDLE_ENDPOINT", "http://paddle:8877")
    monkeypatch.setenv("PADDLE_TIMEOUT_SEC", "18")
    return np.full((20, 20, 3), 255, np.uint8)


def test_each_new_pdf_can_retry_after_previous_failure(monkeypatch, image):
    calls = []
    def offline(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("offline")
    monkeypatch.setattr(gateway, "urlopen", offline)
    for _ in range(2):
        with gateway.paddle_request_budget():
            for mode in ("general", "seal"):
                with pytest.raises(gateway.PaddleUnavailable):
                    gateway.post_image(image, mode)
    assert len(calls) == 2


def test_successful_requests_share_remaining_timeout(monkeypatch, image):
    clock = [0.0]
    timeouts = []
    monkeypatch.setattr(gateway, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    monkeypatch.setattr(gateway, "parse_service_response", lambda *args: [])
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self, *_): return b"{}"
    def slow_response(*args, **kwargs):
        timeouts.append(kwargs["timeout"])
        clock[0] += min(1.25, kwargs["timeout"])
        return Response()
    monkeypatch.setattr(gateway, "urlopen", slow_response)
    with gateway.paddle_request_budget(3):
        for _ in range(3):
            assert gateway.post_image(image, "general") == []
        with pytest.raises(gateway.PaddleUnavailable):
            gateway.post_image(image, "seal")
    assert timeouts == pytest.approx([3, 1.75, .5])


def test_missing_seal_model_does_not_disable_general(monkeypatch, image):
    calls = []
    monkeypatch.setattr(gateway, "parse_service_response", lambda *args: [])
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self, *_): return b"{}"
    def respond(request, **kwargs):
        calls.append(request.full_url)
        if request.full_url.endswith("/seal"):
            raise HTTPError(request.full_url, 503, "not ready", None, None)
        return Response()
    monkeypatch.setattr(gateway, "urlopen", respond)
    with gateway.paddle_request_budget():
        with pytest.raises(gateway.PaddleUnavailable):
            gateway.post_image(image, "seal")
        with pytest.raises(gateway.PaddleUnavailable):
            gateway.post_image(image, "seal")
        assert gateway.post_image(image, "general") == []
    assert len(calls) == 2


@pytest.mark.parametrize("seconds", [0, -1, float("nan"), float("inf"), 301])
def test_invalid_total_budget_rejected(seconds):
    with pytest.raises(ValueError):
        with gateway.paddle_request_budget(seconds):
            pass


def test_nested_budget_does_not_reset_failed_circuit(monkeypatch, image):
    calls = []
    def offline(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("offline")
    monkeypatch.setattr(gateway, "urlopen", offline)
    with gateway.paddle_request_budget():
        with pytest.raises(gateway.PaddleUnavailable):
            gateway.post_image(image, "general")
        with gateway.paddle_request_budget():
            with pytest.raises(gateway.PaddleUnavailable):
                gateway.post_image(image, "general")
    assert len(calls) == 1
