"""Bind native dispatch receipts to immutable controller issuance records."""
import hashlib
import json
from pathlib import Path
import re


def observe_dispatch(root, attempt_id):
    if not re.fullmatch(r'[0-9a-f]{64}',attempt_id):raise ValueError('Invalid attempt identity')
    root=Path(root);issued=root/('issued-'+attempt_id+'.json')
    if not issued.exists():return dict(status='not_issued',retry_permitted=False)
    record=json.loads(issued.read_text(encoding='utf-8'));request=record['request']
    body=json.dumps(request,ensure_ascii=False,allow_nan=False)+'\n'
    if request['request_id']!=attempt_id or hashlib.sha256(body.encode()).hexdigest()!=record['request_sha256']:
        raise ValueError('Dispatch issuance record drift')
    result=root/('result-'+attempt_id+'.json')
    consumed=root/('consumed-'+attempt_id+'.json')
    consumption=consumed.exists()
    if consumption and hashlib.sha256(consumed.read_bytes()).hexdigest()!=record['request_sha256']:
        raise ValueError('Native consumption record drift')
    evidence=dict(status='awaiting_receipt',consumed=consumption,retry_permitted=False,
                  request_sha256=record['request_sha256'])
    if result.exists():
        receipt=json.loads(result.read_text(encoding='utf-8'))
        if receipt['request_id']!=attempt_id or receipt['request_sha256']!=record['request_sha256']:
            raise ValueError('Native receipt belongs to another request')
        if not isinstance(receipt.get('status'),str):raise ValueError('Invalid native receipt status')
        evidence.update(status='receipt_observed',receipt=receipt)
    # A sent Start signal is not evidence that the tester started. Missing
    # receipt/consumption cannot establish that retry would be safe either.
    return evidence
