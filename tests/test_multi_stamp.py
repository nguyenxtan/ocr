from unittest.mock import patch

import numpy as np

from app.analysis import analyze_pdf
from app.document_reader import DocumentIdentity
from app.seal_ocr import SealEvidence


class FakePDF:
    is_pdf = True
    needs_pass = False
    page_count = 1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def __iter__(self):
        return iter([object()])


MASK_UNRELATED = np.full((10, 10), 10, np.uint8)
MASK_ISSUER = np.full((10, 10), 20, np.uint8)


def run_with_seals(evidence_for_mask):
    def mock_read(mask, *_):
        return evidence_for_mask[int(mask[0, 0])]

    with (patch('app.analysis.fitz.open', return_value=FakePDF()),
          patch('app.analysis.render_page', return_value=np.zeros((100, 100, 3), np.uint8)),
          patch('app.analysis.detect_stamps', return_value=[(.90, MASK_UNRELATED), (.85, MASK_ISSUER)]),
          patch('app.analysis.read_document_identity', return_value=DocumentIdentity('CONG TY CO PHAN MINH PHUC', '3501556139')),
          patch('app.analysis.read_seal', side_effect=mock_read)):
        return analyze_pdf('mock.pdf')


def test_second_candidate_can_supply_issuer_name():
    result = run_with_seals({
        10: SealEvidence(('QUAN LY NHAN SU',), frozenset()),
        20: SealEvidence(('CONG TY CO PHAN MINH PHUC',), frozenset()),
    })
    assert result.status == 'PASS'
    assert result.method == 'NAME_FALLBACK'


def test_conflicting_mst_on_other_stamp_is_not_silent_pass():
    # Another stamp carries a readable, structurally valid but different MST.
    result = run_with_seals({
        10: SealEvidence(('CONG TY CO PHAN KHAC',), frozenset({'3501556146'})),
        20: SealEvidence(('CONG TY CO PHAN MINH PHUC',), frozenset()),
    })
    assert result.status == 'REVIEW'


def test_only_unrelated_stamps_do_not_pass():
    result = run_with_seals({
        10: SealEvidence(('CONG TY CO PHAN KHAC',), frozenset()),
        20: SealEvidence(('CONG TY CO PHAN VINH PHUC',), frozenset()),
    })
    assert result.status == 'REVIEW'
