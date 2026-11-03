from app.web_compare import compare


def f(value, status='read'):
    return {'value':value, 'normalized': value, 'status':status, 'regions':[]}


def documents():
    return {'gpkd': {'fields': {'tax_id':f('0123456789'), 'company_vi':f('CONG TY ALPHA'), 'legal_rep':f('NGUYEN VAN A'),'seal':f('Có','manual')}},
            'eport': {'fields': {'tax_id':f('0123456789'), 'registration_id':f('0123456789'), 'company_vi':f('CONG TY ALPHA'), 'authorized_rep':f('NGUYEN VAN A'), 'signer':f('NGUYEN VAN A'), 'signature':f('Có','manual'), 'seal':f('Có','manual'), 'seal_tax_id':f('0123456789'), 'seal_company':f('CONG TY ALPHA')}}}


def row(report, key):
    return next(r for r in report['rows'] if r['id']==key)


def test_complete_pair_passes_without_confidence_percentage():
    r = compare(documents())
    assert r['conclusion'] == 'PASS'
    assert len(r['rows']) == 9


def test_mst_conflict_cannot_be_overridden_by_matching_name():
    d=documents(); d['eport']['fields']['seal_tax_id']=f('9876543210')
    r=compare(d)
    assert row(r,'seal_identity')['status']=='FAIL'
    assert r['conclusion']=='FAIL'


def test_missing_and_unreadable_are_never_equal():
    d=documents()
    for kind in d:
        d[kind]['fields']['tax_id']=f('', 'missing')
    r=compare(d)
    assert row(r,'tax_id')['status']=='REVIEW'


def test_different_representative_requires_authorization_review():
    d=documents(); d['eport']['fields']['authorized_rep']=f('TRAN THI B')
    r=compare(d)
    assert row(r,'representative')['status']=='REVIEW'
    assert 'ủy quyền' in row(r,'representative')['reason']


def test_seal_name_fallback_only_when_id_unreadable():
    d=documents(); d['eport']['fields']['seal_tax_id']=f('', 'missing')
    assert row(compare(d),'seal_identity')['status']=='PASS'
    d['eport']['fields']['seal_tax_id']=f('0123456789 / 9876543210','ambiguous')
    assert row(compare(d),'seal_identity')['status']=='REVIEW'


def test_suspected_signature_does_not_pass():
    d=documents(); d['eport']['fields']['signature']=f('Nghi có', 'uncertain')
    assert compare(d)['conclusion']=='REVIEW'


def test_identifier_letters_are_not_silently_discarded():
    d=documents();d['eport']['fields']['tax_id']=f('ABC0123456789')
    assert row(compare(d),'tax_id')['status']=='REVIEW'


def test_different_readable_company_fails_and_blurred_seal_reviews():
    d=documents();d['eport']['fields']['company_vi']=f('CONG TY BETA')
    assert row(compare(d),'company')['status']=='FAIL'
    d=documents();d['eport']['fields']['seal']=f('Nghi có','uncertain');d['eport']['fields']['seal_tax_id']=f('','missing');d['eport']['fields']['seal_company']=f('','uncertain')
    assert row(compare(d),'seal_identity')['status']=='REVIEW'
    assert row(compare(d),'seal')['status']=='REVIEW'
