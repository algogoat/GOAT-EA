"""G4 golden generator for the B44 MQL deploy-profile writer (P-beta25-D5-dashboard-deploy-all).

The dashboard's own Deploy All returns through GOATDeployProfileWriter.mqh, which must write the same bytes as
studio_deploy_profile. This module emits those bytes from the Python writer itself for three whole fixture
portfolios (M1/M5/H1/H4/D1, AI off and on with both protocols, the deployment nonce appended and replaced in place,
UTF-16 and UTF-8 SETs with and without a BOM, astral characters) plus a set of refusal cases with Python's verdict.

    python deploy_profile_goldens.py           # check: the committed g4 files equal what the writer emits now
    python deploy_profile_goldens.py --write   # (re)write controller/contracts/profile-fixtures/g4

Nothing here touches MT5. test_deploy_profile_goldens.py pins the committed files to the live Python writer, and
scripts/test_profile_writer_goldens.cjs runs the production MQL source against the same files, so a drift on
either side fails a test. Design: docs/operations/B44-DEPLOY-ALL-DESIGN.md.
"""
import hashlib
import json
import sys
from pathlib import Path

import studio_demo_deploy as deploy
import studio_deploy_profile as profile
from studio_refusal import Refusal

FIXTURES = Path(__file__).resolve().parent / 'contracts' / 'profile-fixtures'
G4 = 'g4'
COMMON = 'C:\\Users\\Customer\\AppData\\Roaming\\MetaQuotes\\Terminal\\Common\\Files\\GOAT\\Deployments\\'
CODES = (profile.PERIOD_REFUSED, profile.SET_LINE_REFUSED, profile.SET_EMPTY, profile.SET_NONCE_INPUT_REFUSED)
# The MQL writer's names for the two Python failures that carry no refusal code of their own.
DECODE_REFUSED = 'SET_ENCODING_UNSUPPORTED'
VALUE_REFUSED = 'PROFILE_VALUE_UNSUPPORTED'


def utf16(text):
    return b'\xff\xfe' + text.encode('utf-16-le')


def utf8(text, bom=False):
    return (b'\xef\xbb\xbf' if bom else b'') + text.encode('utf-8')


# Each SET: (fixture file name, bytes). Texts are written out in full so a reviewer can read every case.
SETS = {
    'p1-gbpusd-runpath.set': utf8(
        '; GOAT V1.49 export\r\n'
        '; ===== Risk =====\r\n'
        'EA_Desc=P1 GBPUSD runpath\r\n'
        'Mode_Operation=9\r\n'
        'Risk=250\r\n'
        'Studio_MonitorRunPath=\r\n'
        'Mode_Bias=1\r\n'
        'Bias_threshold=40\r\n'
        'TP_Points=120.50\r\n'),
    'p2-usdjpy-hourly.set': utf16(
        '; P2 hourly, UTF-16 with CRLF\r\n'
        'EA_Desc=P2 USDJPY hourly\r\n'
        'Mode_Operation=9\r\n'
        'Mode_Bias=1\r\n'
        'Risk=100\r\n'
        'Bias_threshold=40\r\n'
        'Mode_Bias_Trades=1\r\n'
        'Mode_Bias_Exit=1\r\n'
        '   Lots_Mode=2\t\r\n'),
    'p2-xauusd-daily.set': utf8(
        'EA_Desc=P2 XAUUSD daily\n'
        'Mode_Operation=9\n'
        '\tRisk=75\t\n'
        '\n'
        'no key here\n'
        'Signal_TF=16408\n', bom=True),
    'p2-us30-index.set': utf8(
        'EA_Desc=P2 US30.cash\r\n'
        'Mode_Operation=9\n'
        'Risk=50\r\n'
        'Studio_MonitorRunPath='),
    'p3-eurusd-cafe.set': utf8(
        '; note=\u00e9t\u00e9 in a comment that holds =\n'
        'EA_Desc=Caf\u00e9 \u2615 \U0001F410\n'
        'Mode_Operation=9\n'
        'Mode_Bias=2\n'
        'Bias_Protocol=2\n'
        'Risk=120\n'),
    'p3-gbpjpy-goat.set': utf16(
        'EA_Desc=\U0001F410 GBPJPY \u200dH4\r\n'
        'Mode_Operation=9\r\n'
        'Note_Text=a\ufeffb\r\n'
        'Risk=90\r\n'),
    'p3-btcusd-crypto.set': utf16(
        'EA_Desc=P3 BTC\r\n'
        'Mode_Operation=9\r\n'
        'Mode_Bias_Trades=1\r\n'
        'Risk=30\r\n'),
    'p3-eurusd-second.set': utf8(
        'EA_Desc=P3 EURUSD second\r\n'
        'Mode_Operation=9\r\n'
        'Risk=60\r\n'
        'Studio_MonitorRunPath=\r\n'),
}

PORTFOLIOS = [
    dict(case='p1-m1-ai-off', deploymentId='a1b2c3d4e5f60718293a4b5c6d7e8f90', eaRelativePath='GOAT-EA\\GOAT V1.49.ex5',
         policy=dict(aiMode=0, aiThreshold=50, aiProtocol=2),
         note='AI off; two M1 members: the real B35-01 Kestrel SET (UTF-16) and a UTF-8 SET whose "" Studio_MonitorRunPath is replaced in place',
         members=[dict(set='kestrel-b35-01.set', fileName='GOAT V1.49 EURUSD,M1_B35-01_Kestrel-Trend-Breakout.set', symbol='EURUSD',
                       strategy='B35-01 Kestrel Trend Breakout'),
                  dict(set=G4 + '/p1-gbpusd-runpath.set', fileName='GOAT V1.49 GBPUSD,M1_P1-runpath.set', symbol='GBPUSD',
                       strategy='P1 runpath')]),
    dict(case='p2-h1-d1-ai-on', deploymentId='f0e1d2c3b4a5968778695a4b3c2d1e0f', eaRelativePath='GOAT Experiment\\GOAT V1.50.ex5',
         policy=dict(aiMode=2, aiThreshold=65, aiProtocol=2),
         note='AI on (protocol 2); H1, D1 and an H1 index with a dotted symbol; AI inputs replaced in place and appended; padding, '
              'blank and keyless lines, UTF-8 BOM with LF, no final line end',
         members=[dict(set=G4 + '/p2-usdjpy-hourly.set', fileName='GOAT V1.50 USDJPY,H1_P2-hourly.set', symbol='USDJPY', strategy='P2 hourly'),
                  dict(set=G4 + '/p2-xauusd-daily.set', fileName='GOAT V1.50 XAUUSD,D1_P2-daily.set', symbol='XAUUSD', strategy='P2 daily'),
                  dict(set=G4 + '/p2-us30-index.set', fileName='GOAT V1.50 US30.cash,H1_P2-index.set', symbol='US30.cash',
                       strategy='P2 index')]),
    dict(case='p3-unicode-mixed', deploymentId='c0ffee00c0ffee00c0ffee00c0ffee00', eaRelativePath='GOAT-EA\\GOAT V1.49.ex5',
         policy=dict(aiMode=2, aiThreshold=50, aiProtocol=1),
         note='AI on (protocol 1); M5, H4, D1 and M1; non-ASCII and astral characters in UTF-8 and UTF-16, U+200D and U+FEFF kept, '
              'a symbol with #, two members on EURUSD',
         members=[dict(set=G4 + '/p3-eurusd-cafe.set', fileName='GOAT V1.49 EURUSD,M5_P3-cafe.set', symbol='EURUSD', strategy='P3 caf\u00e9'),
                  dict(set=G4 + '/p3-gbpjpy-goat.set', fileName='GOAT V1.49 GBPJPY,H4_P3-goat.set', symbol='GBPJPY', strategy='P3 goat'),
                  dict(set=G4 + '/p3-btcusd-crypto.set', fileName='GOAT V1.49 BTCUSD#,D1_P3-crypto.set', symbol='BTCUSD#',
                       strategy='P3 crypto'),
                  dict(set=G4 + '/p3-eurusd-second.set', fileName='GOAT V1.49 EURUSD,M1_P3-second.set', symbol='EURUSD',
                       strategy='P3 second')]),
]

GOOD = '0123456789abcdef0123456789abcdef'
EA = 'GOAT-EA\\GOAT V1.49.ex5'
NAME = 'GOAT V1.49 EURUSD,M1_x.set'
OK_SET = utf16('EA_Desc=x\r\nRisk=1\r\n')
# Refusals beyond g2/refused.json: encodings, the nonce input, periods, symbols, EA paths and the deployment ID.
REFUSED = [
    ('odd UTF-16 length', dict(raw=OK_SET + b'A')),
    ('lone high surrogate', dict(raw=utf16('EA_Desc=x') + b'\x3d\xd8' + utf16('\r\n')[2:])),
    ('lone low surrogate', dict(raw=utf16('EA_Desc=x') + b'\x10\xdc' + utf16('\r\n')[2:])),
    ('high surrogate at the end', dict(raw=utf16('EA_Desc=x\r\n') + b'\x3d\xd8')),
    ('UTF-8 overlong slash', dict(raw=b'EA_Desc=\xc0\xaf\r\n')),
    ('UTF-8 truncated', dict(raw=b'EA_Desc=\xe2\x98')),
    ('UTF-8 encoded surrogate', dict(raw=b'EA_Desc=\xed\xa0\x80\r\n')),
    ('UTF-8 above U+10FFFF', dict(raw=b'EA_Desc=\xf4\x90\x80\x80\r\n')),
    ('UTF-8 stray continuation', dict(raw=b'EA_Desc=\x80\r\n')),
    ('UTF-8 NUL', dict(raw=b'EA_Desc=x\x00\r\n')),
    ('UTF-8 empty', dict(raw=b'')),
    ('UTF-8 BOM only', dict(raw=b'\xef\xbb\xbf')),
    ('ideographic space at the start of a key', dict(raw=utf16('\u3000EA_Desc=x\r\n'))),
    ('more than 4096 lines', dict(raw=utf8('EA_Desc=x\n' * 4097))),
    ('run path set to a value', dict(raw=utf16('EA_Desc=x\r\nStudio_MonitorRunPath=C:\\x\r\n'))),
    ('run path named twice', dict(raw=utf16('Studio_MonitorRunPath=\r\nEA_Desc=x\r\nStudio_MonitorRunPath=\r\n'))),
    ('run path already the nonce', dict(raw=utf16('EA_Desc=x\r\nStudio_MonitorRunPath=deploy=' + GOOD + '\r\n'))),
    ('period M15', dict(name='GOAT V1.49 EURUSD,M15_x.set')),
    ('period M30', dict(name='GOAT V1.49 EURUSD,M30_x.set')),
    ('period W1', dict(name='GOAT V1.49 EURUSD,W1_x.set')),
    ('lowercase period', dict(name='GOAT V1.49 EURUSD,m1_x.set')),
    ('no comma', dict(name='GOAT V1.49 EURUSD M1_x.set')),
    ('M10 is not M1', dict(name='GOAT V1.49 EURUSD,M10_x.set')),
    ('symbol with a slash', dict(symbol='EUR/USD')),
    ('empty symbol', dict(symbol='')),
    ('symbol of 65 characters', dict(symbol='A' * 65)),
    ('EA path with a forward slash', dict(ea='GOAT-EA/GOAT V1.49.ex5')),
    ('EA path with ..', dict(ea='..\\GOAT V1.49.ex5')),
    ('EA path absolute', dict(ea='C:\\GOAT V1.49.ex5')),
    ('EA path not ex5', dict(ea='GOAT-EA\\GOAT V1.49.mq5')),
    ('EA path with =', dict(ea='GOAT-EA\\GOAT=V1.49.ex5')),
    ('EA file name without a stem', dict(ea='GOAT-EA\\.ex5')),
    ('deployment ID upper case', dict(deploymentId=GOOD.upper())),
    ('deployment ID short', dict(deploymentId=GOOD[:31])),
]


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def set_bytes(relative):
    if relative.startswith(G4 + '/'):
        return SETS[relative[len(G4) + 1:]]
    return (FIXTURES / relative).read_bytes()


def verdict(case):
    """Python's answer for one refusal case: its refusal code, or the MQL writer's name for a plain decode/value error."""
    member = dict(name=case.get('name', NAME), symbol=case.get('symbol', 'EURUSD'), raw=case.get('raw', OK_SET))
    try:
        profile.child_chart(member, case.get('ea', EA), dict(aiMode=0, aiThreshold=50, aiProtocol=2), case.get('deploymentId', GOOD))
    except Refusal as exc:
        return exc.code
    except UnicodeDecodeError:
        return DECODE_REFUSED
    except ValueError as exc:
        code = str(exc).split(':', 1)[0]
        return code if code in CODES else VALUE_REFUSED
    return None


def build():
    """{path relative to profile-fixtures: bytes} for every G4 file."""
    files = {G4 + '/' + name: raw for name, raw in SETS.items()}
    portfolios = []
    for spec in PORTFOLIOS:
        members = [dict(name=m['fileName'], symbol=m['symbol'], raw=set_bytes(m['set'])) for m in spec['members']]
        profile.refuse_duplicates(members, spec['policy'])
        charts = profile.profile_files(spec['eaRelativePath'], spec['policy'], members, spec['deploymentId'])
        folder = G4 + '/' + spec['case'] + '/'
        rows = [dict(path=COMMON + spec['deploymentId'] + '\\' + m['fileName'], name=m['fileName'], symbol=m['symbol'],
                     strategy=m['strategy']) for m in spec['members']]
        charts['dashboard_state.tsv'] = deploy.state_bytes(dict(
            policy='\t'.join(str(spec['policy'][k]) for k in ('aiMode', 'aiThreshold', 'aiProtocol')), members=rows))
        for name, raw in charts.items():
            files[folder + name] = raw
        portfolios.append(dict(spec, profileName=profile.profile_name(spec['deploymentId']),
                               members=[dict(m, path=row['path'], setSha256=sha256(set_bytes(m['set'])))
                                        for m, row in zip(spec['members'], rows)],
                               files={name: sha256(raw) for name, raw in sorted(charts.items())}))
    refused = []
    for label, case in REFUSED:
        code = verdict(case)
        if code is None:
            raise AssertionError('The Python writer accepted the refusal case ' + repr(label))
        refused.append(dict(label=label, fileName=case.get('name', NAME), symbol=case.get('symbol', 'EURUSD'),
                            eaRelativePath=case.get('ea', EA), deploymentId=case.get('deploymentId', GOOD),
                            setHex=case.get('raw', OK_SET).hex(), code=code))
    manifest = dict(schema=1, writer='studio_deploy_profile ' + profile.PROFILE_FORMAT,
                    generator='controller/deploy_profile_goldens.py', portfolios=portfolios, refused=refused)
    files[G4 + '/cases.json'] = (json.dumps(manifest, indent=1, ensure_ascii=True) + '\n').encode('ascii')
    return files


def differences(root=FIXTURES):
    expected = build()
    changed = sorted(name for name, raw in expected.items() if not (root / name).is_file() or (root / name).read_bytes() != raw)
    extra = sorted(path.relative_to(root).as_posix() for path in (root / G4).rglob('*')
                   if path.is_file() and path.relative_to(root).as_posix() not in expected) if (root / G4).is_dir() else []
    return changed, extra


def write(root=FIXTURES):
    for name, raw in build().items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


if __name__ == '__main__':
    if '--write' in sys.argv[1:]:
        write()
    changed, extra = differences()
    print(json.dumps(dict(changed=changed, extra=extra, ok=not changed and not extra)))
    sys.exit(0 if not changed and not extra else 1)
