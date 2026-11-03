"""Photocopied seal candidates must keep real coordinates and require review."""
import cv2
import fitz
import numpy as np
import pytest

from app.web_extract import detect_stamps, store_seal_presence, extract_fields, extract, inspect_marks
from app.seal_ocr import SealEvidence


def seal_image(ink=35, center=(445, 610), axes=(90, 90), size=(900, 700)):
    image = np.full((*size, 3), 248, np.uint8)
    for factor in (1, .78):
        cv2.ellipse(image, center, tuple(round(v*factor) for v in axes),
                    17, 0, 360, (ink, ink, ink), 3, cv2.LINE_AA)
    x, y = center
    cv2.putText(image, 'DON VI', (x-47, y-8), cv2.FONT_HERSHEY_SIMPLEX,
                .52, (ink, ink, ink), 1, cv2.LINE_AA)
    cv2.putText(image, 'THU NGHIEM', (x-55, y+18), cv2.FONT_HERSHEY_SIMPLEX,
                .4, (ink, ink, ink), 1, cv2.LINE_AA)
    return image


@pytest.mark.parametrize('ink,center,axes,size', [
    (25, (445, 610), (90, 90), (900, 700)),
    (175, (210, 330), (75, 54), (700, 900)),
    (70, (840, 1140), (150, 150), (1800, 1400)),
])
def test_monochrome_seal_is_located_without_red_and_requires_review(ink, center, axes, size):
    image = seal_image(ink, center, axes, size)
    found = detect_stamps(image, with_boxes=True)
    assert found, 'Photocopied seal was missed'
    score, mask, (x0, y0, x1, y1) = found[0]
    assert x0 < center[0] < x1 and y0 < center[1] < y1
    assert x1-x0 < axes[0]*3 and y1-y0 < axes[0]*3
    assert mask.shape == (y1-y0, x1-x0)
    fields = extract_fields([], 'gpkd')
    store_seal_presence(fields, [(score, {'page': 2, 'box': [.1,.2,.4,.5]})])
    assert fields['seal']['status'] == 'uncertain'
    assert fields['seal']['value'] == 'Nghi có'


@pytest.mark.parametrize('graphic', ['text', 'table', 'circle', 'empty_rings', 'solid'])
def test_ordinary_monochrome_content_is_not_a_seal_candidate(graphic):
    image = np.full((900, 700, 3), 255, np.uint8)
    if graphic == 'text':
        for y in range(80, 800, 30):
            cv2.putText(image, 'COMPANY REGISTRATION 0123456789', (35,y),
                        cv2.FONT_HERSHEY_SIMPLEX, .7, (25,25,25), 1)
    elif graphic == 'table':
        for x in range(80, 620, 90): cv2.line(image, (x,150), (x,690), (0,0,0), 2)
        for y in range(150, 700, 90): cv2.line(image, (80,y), (530,y), (0,0,0), 2)
    else:
        cv2.circle(image, (350,450), 90, (0,0,0), -1 if graphic=='solid' else 3)
        if graphic=='empty_rings': cv2.circle(image, (350,450), 70, (0,0,0), 3)
    assert detect_stamps(image, with_boxes=True) == []


def test_red_and_photocopied_candidates_on_same_page_keep_both_sources():
    image = seal_image(center=(200, 570))
    for radius in (90, 70): cv2.circle(image, (500,230), radius, (180,25,25), 3)
    found = detect_stamps(image, with_boxes=True)
    assert any(x0 < 200 < x1 and y0 < 570 < y1 for _,_,(x0,y0,x1,y1) in found)
    assert any(x0 < 500 < x1 and y0 < 230 < y1 for _,_,(x0,y0,x1,y1) in found)


def test_crossing_signature_and_text_do_not_hide_a_photocopied_seal():
    image = seal_image()
    cv2.line(image, (330, 590), (570, 650), (0,0,0), 2)
    cv2.putText(image, 'NGUOI DAI DIEN', (350, 540), cv2.FONT_HERSHEY_SIMPLEX,
                .7, (0,0,0), 2)
    found = detect_stamps(image, with_boxes=True)
    assert any(x0 < 445 < x1 and y0 < 610 < y1 for _,_,(x0,y0,x1,y1) in found)


def test_monochrome_stamp_ocr_cannot_confirm_tax_id_before_region_confirmation(monkeypatch):
    # A clean OCR number may come from printed text crossing a suspected seal.
    monkeypatch.setattr('app.web_extract.read_seal', lambda *args:
                        SealEvidence(('0123456789',), frozenset({'0123456789'})))
    fields = extract_fields([], 'eport')
    pages = [{'number':1, 'width':700, 'height':900, 'method':'ocr', 'rotation':0}]
    inspect_marks(None, pages, [], {1:seal_image()}, fields, 'eng')
    assert fields['seal_tax_id']['value'] == '0123456789'
    assert fields['seal_tax_id']['status'] == 'uncertain'
    assert fields['seal_tax_id']['regions'] == fields['seal']['regions']


@pytest.mark.parametrize('kind,title', [
    ('gpkd', 'GIAY CHUNG NHAN DANG KY DOANH NGHIEP'),
    ('eport', 'BAN DANG KY SU DUNG EPORT'),
])
def test_pdf_photocopied_seal_on_later_page_has_real_source_and_needs_review(tmp_path, kind, title):
    path = tmp_path/'photocopy.pdf'
    image = seal_image()
    with fitz.open() as doc:
        p = doc.new_page(width=700, height=900)
        p.insert_text((40, 60), title+'\nMa so doanh nghiep: 0123456789\nTen doanh nghiep: CONG TY THU NGHIEM')
        p = doc.new_page(width=700, height=900)
        p.insert_image(p.rect, stream=cv2.imencode('.png', image)[1].tobytes())
        doc.save(path)
    result = extract(path, kind)
    assert result['detected_kind'] == kind
    field = result['fields']['seal']
    assert field['status'] == 'uncertain' and field['value'] == 'Nghi có'
    assert len(field['regions']) == 1
    proof = field['regions'][0]
    assert proof['page'] == 2
    x0, y0, x1, y1 = proof['box']
    assert x0 < 445/700 < x1 and y0 < 610/900 < y1
    if kind == 'eport':
        assert result['fields']['seal_tax_id']['status'] != 'read'
