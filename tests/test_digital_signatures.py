from pathlib import Path
from unittest.mock import patch
from subprocess import TimeoutExpired
from app.digital_signatures import parse_pdfsig, inspect_digital_signatures
from app.analysis import Result


SAMPLE = '''Digital Signature Info of: example.pdf
Signature #1:
  - Signature Field Name: Signature_0
  - Signer Certificate Common Name: CONG TY EXAMPLE
  - Signature Validation: Signature is Valid.
  - Certificate Validation: Certificate issuer isn't Trusted.
  - Total document signed
'''


def test_digitally_signed_pdf_with_untrusted_issuer():
    result = parse_pdfsig(SAMPLE)
    assert result.status == 'VALID_CRYPTO'
    assert result.trusted is False and result.count == 1


def test_digital_signature_scan_is_not_embedded():
    result = parse_pdfsig("File '/x/file.pdf' does not contain any signatures")
    assert result.status == 'NONE'


def test_invalid_embedded_signature_is_invalid():
    x = SAMPLE.replace('Signature is Valid.', 'Signature is Invalid.')
    assert parse_pdfsig(x).status == 'INVALID'


def test_incomplete_signing_range_is_not_full_integrity():
    x = SAMPLE.replace('  - Total document signed\n', '')
    assert parse_pdfsig(x).status == 'UNVERIFIED'


def test_timeout_reports_error_instead_of_hanging():
    with patch('app.digital_signatures.subprocess.run', side_effect=TimeoutExpired('pdfsig', 1)):
        assert inspect_digital_signatures(Path('sample.pdf'), timeout_s=1).status == 'ERROR'


def test_crypto_signature_does_not_substitute_for_red_seal():
    msg = Result('FAIL', 'Không phát hiện dấu tròn đỏ.', digital_signature='VALID_CRYPTO').telegram_html()
    assert 'KHÔNG ĐẠT' in msg and 'Không thay thế dấu đỏ' in msg
