from unittest.mock import patch

import numpy as np

from app.paddle_contract import OCRLine
from app.ensemble import strengthen_seal
from app.seal_ocr import SealEvidence
from app.analysis import tax_code_valid
from app.paddle_gateway import PaddleUnavailable

COMPANY = "CÔNG TY CỔ PHẦN TÂN CẢNG CYPRESS"
MASK = np.zeros((100, 100), np.uint8)


def result_with(tess, gen, seal, mst=None):
    def mocked_post(_img, mode):
        return gen if mode == "general" else seal

    with patch("app.ensemble.post_image", side_effect=mocked_post):
        return strengthen_seal(COMPANY, tess, MASK, tax_code_valid, document_mst=mst)


def test_base_result_is_preserved_when_paddle_unavailable():
    tess = SealEvidence(("TAN CANG CYPRESS",), frozenset())
    with patch("app.ensemble.post_image", side_effect=PaddleUnavailable("offline")):
        out = strengthen_seal(COMPANY, tess, MASK, tax_code_valid)
    assert out.name.matched and not out.paddle_used


def test_two_paddle_models_alone_cannot_promote_to_pass():
    # PP-OCRv6 general + SealRecognition may share the text recognizer.
    output = [OCRLine("TAN CANG CYPRESS", .95)]
    out = result_with(SealEvidence(("OOX",), frozenset()), output, output)
    assert not out.name.matched and out.note != "NAME_ENSEMBLE"


def test_paddle_one_model_alone_does_not_make_pass():
    output = [OCRLine("TAN CANG CYPRESS", .99)]
    out = result_with(SealEvidence(("ABC",), frozenset()), output, [])
    assert not out.name.matched


def test_tesseract_partial_and_paddle_general_agree():
    output = [OCRLine("TAN CANG CYPRESS", .95)]
    tess = SealEvidence(("TAN CANG",), frozenset())
    out = result_with(tess, output, [])
    assert out.name.matched and out.note == "NAME_ENSEMBLE"


def test_different_mst_prevents_name_pass_even_if_name_matches():
    # 3501556146 has correct checksum but does not match the document code.
    other = "3501556146"
    assert tax_code_valid(other)
    gen = [OCRLine("TAN CANG CYPRESS", .98), OCRLine(other, .97)]
    seal = [OCRLine("TAN CANG CYPRESS", .99)]
    out = result_with(SealEvidence(("TAN CANG CYPRESS",), frozenset()), gen, seal, "3501556139")
    assert out.ambiguous and out.note == "MST OCR bất đồng"


def test_identical_mst_from_paddle_alone_requires_more_evidence():
    # Identical readings may still be correlated errors.
    code = "3501556139"
    good = [OCRLine("TAN CANG CYPRESS", .97), OCRLine(code, .96)]
    out = result_with(SealEvidence((), frozenset()), good, good, code)
    assert out.msts == frozenset()
    assert not out.ambiguous


def test_two_new_models_disagree_on_mst_requires_review():
    gen = [OCRLine("3501556139", .99)]
    seal = [OCRLine("3501556146", .98)]
    out = result_with(SealEvidence((), frozenset()), gen, seal, "3501556139")
    assert out.ambiguous


def test_weak_recognition_scores_cannot_make_pass():
    weak = [OCRLine("TAN CANG CYPRESS", .31)]
    out = result_with(SealEvidence(("TAN",), frozenset()), weak, weak)
    assert not out.name.matched


def test_tesseract_code_kept_when_paddle_is_silent():
    code = "3501556139"
    out = result_with(SealEvidence((), frozenset({code})), [], [], code)
    assert out.msts == frozenset({code})
    assert not out.ambiguous


def test_paddle_contradicts_confirmed_tesseract_tax_id():
    out = result_with(
        SealEvidence(("TAN CANG CYPRESS",), frozenset({"3501556139"})),
        [OCRLine("3501556146", .98)], [], "3501556139"
    )
    assert out.ambiguous
    assert "MST" in out.note
