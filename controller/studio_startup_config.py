"""Build a research startup payload from validated launch material.

No filesystem writes, process launch, shutdown, queue claim or authorization.
Caller must obtain material through validate_launch_material and subsequently
perform the research restart/ownership protocol before using this payload.
"""
import hashlib
import re


def startup_config(material):
    sections = material['sections']
    if set(sections) != {'Charts', 'Experts', 'Tester', 'TesterInputs'}:
        raise ValueError('Unexpected startup sections')
    if sections['Charts'] != {'ProfileLast': 'GOAT Research'}:
        raise ValueError('Research profile required')
    if sections['Experts'] != {'Enabled': '0', 'AllowLiveTrading': '0'}:
        raise ValueError('Disabled chart trading required')
    tester = sections['Tester']
    required = dict(UseLocal='1', UseRemote='0', UseCloud='0', Visual='0',
                    ReplaceReport='0', ShutdownTerminal='0')
    if any(tester.get(k) != v for k, v in required.items()):
        raise ValueError('Research worker/report policy differs')
    if not re.fullmatch(r'1:[1-9][0-9]*', tester.get('Leverage', '')):
        raise ValueError('Startup ratio leverage required')
    report = tester.get('Report', '')
    relative = material['manifest']['native_run_relative']
    if not report.startswith('MQL5\\Files\\'+relative+'\\reports\\') or not report.endswith('.xml'):
        raise ValueError('Report must belong to this native run')
    if any(part in ('', '.', '..') for part in report.split('\\')) or '/' in report or ':' in report:
        raise ValueError('Unsafe report path')
    payload = {k: dict(v) for k, v in sections.items()}
    payload['TesterInputs'] = dict(material['paste_inputs'])
    if 'startup_monitor' in material:
        payload['StartUp']=dict(material['startup_monitor'])
        if set(payload['StartUp'])!={'Expert','ExpertParameters','Symbol','Period'}:
            raise ValueError('Only verified monitor startup is supported')
    text = ''
    for section in payload:
        text += '['+section+']\r\n'
        for key, value in payload[section].items():
            if any(c in key+value for c in '\r\n\0'):
                raise ValueError('Multiline startup setting')
            text += key+'='+value+'\r\n'
    raw = text.encode('utf-16')
    return raw, dict(sha256=hashlib.sha256(raw).hexdigest(),
                     source_campaign_id=material['manifest']['campaign_id'],
                     report=report, launch_permitted=False)
