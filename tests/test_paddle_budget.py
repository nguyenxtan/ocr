"""A slow optional sidecar must not cost its full timeout for every crop."""
import json
from unittest.mock import patch
from urllib.error import URLError
import numpy as np
import pytest
from app import paddle_gateway as gateway

IMAGE=np.zeros((8,8,3),np.uint8)


def test_sidecar_outage_is_attempted_once_per_pdf(monkeypatch):
    monkeypatch.setenv('PADDLE_ENDPOINT','http://paddle:8877')
    with patch.object(gateway,'urlopen',side_effect=URLError('offline')) as network:
        with gateway.request_budget():
            for _ in range(5):
                with pytest.raises(gateway.PaddleUnavailable): gateway.post_image(IMAGE,'general')
        assert network.call_count==1
        with gateway.request_budget():
            with pytest.raises(gateway.PaddleUnavailable): gateway.post_image(IMAGE,'general')
        assert network.call_count==2, 'New PDF must be able to retry a recovered service'


def test_budget_caps_per_call_timeout_even_when_compose_sets_18s(monkeypatch):
    monkeypatch.setenv('PADDLE_ENDPOINT','http://paddle:8877')
    monkeypatch.setenv('PADDLE_TIMEOUT_SEC','18')
    monkeypatch.setenv('PADDLE_BUDGET_SEC','8')
    with patch.object(gateway,'urlopen',side_effect=URLError('offline')) as network:
        with gateway.request_budget():
            with pytest.raises(gateway.PaddleUnavailable): gateway.post_image(IMAGE,'seal')
        assert 0 < network.call_args.kwargs['timeout'] <= 8


def test_slow_success_consumes_budget_for_later_requests(monkeypatch):
    monkeypatch.setenv('PADDLE_ENDPOINT','http://paddle:8877')
    monkeypatch.setenv('PADDLE_BUDGET_SEC','8')
    clock=[0.0];timeouts=[]
    monkeypatch.setattr(gateway.time,'monotonic',lambda:clock[0])
    class Response:
        status=200
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,*args): clock[0]+=3; return b'{}'
    def open_url(req,timeout): timeouts.append(timeout);return Response()
    with patch.object(gateway,'urlopen',side_effect=open_url), patch.object(gateway,'parse_service_response',return_value=[]):
        with gateway.request_budget():
            gateway.post_image(IMAGE,'general')
            gateway.post_image(IMAGE,'seal')
            with pytest.raises(gateway.PaddleUnavailable): gateway.post_image(IMAGE,'general')
            with pytest.raises(gateway.PaddleUnavailable): gateway.post_image(IMAGE,'seal')
    assert timeouts==[8,5,2]


def test_zero_budget_disables_optional_network_only(monkeypatch):
    monkeypatch.setenv('PADDLE_ENDPOINT','http://paddle:8877')
    monkeypatch.setenv('PADDLE_BUDGET_SEC','0')
    with patch.object(gateway,'urlopen') as network:
        with gateway.request_budget():
            with pytest.raises(gateway.PaddleUnavailable): gateway.post_image(IMAGE,'general')
        network.assert_not_called()


def test_analysis_creates_a_fresh_budget_for_each_document(monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    from app import analysis
    monkeypatch.setenv('PADDLE_ENDPOINT','http://paddle:8877')
    def check(*args):
        for _ in range(3):
            with pytest.raises(gateway.PaddleUnavailable): gateway.post_image(IMAGE,'general')
        return analysis.Result('REVIEW','uncertain')
    monkeypatch.setattr(analysis,'_analyze_stamp_pdf',check)
    monkeypatch.setattr(analysis,'inspect_digital_signatures',lambda *_:SimpleNamespace(status='NONE',trusted=None))
    with patch.object(gateway,'urlopen',side_effect=URLError('offline')) as network:
        analysis.analyze_pdf(Path('first.pdf'))
        analysis.analyze_pdf(Path('second.pdf'))
    assert network.call_count==2
