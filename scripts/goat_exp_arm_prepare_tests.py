"""Exp-arm preparation checks; no terminal, network or credential operations."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace as S
from unittest.mock import patch

import goat_demo_pair_connection as c
import goat_demo_pair_guard as g
import goat_demo_pair_prepare as prep
import goat_exp_arm_prepare as x

SET_TEXT=('; frozen fixture\nMode_Operation=9\nEA_Desc=Strategy {i}\nMode_Lots=2\nRisk=500.0\nMode_Bias=1\n'
          'Bias_Protocol=1\nBias_threshold=60\nMode_Bias_Trades=0\nActive_Time_ASIA=01:30-11:00\n')
HEADERS={9:'#GOAT_AI_LAUNCH_V147_2\t0\t50\t2',10:'#GOAT_AI_LAUNCH_V147_2\t2\t50\t2'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def utf16(text):
    return text.replace('\n','\r\n').encode('utf-16')


class Host:
    """powershell -> signature JSON or the process list; per-arm processes -> none."""
    def __init__(self, procs, status='Valid', subject='CN=MetaQuotes Ltd., O=MetaQuotes Ltd.'):
        self.procs=procs; self.signature=dict(status=status,subject=subject)
    def powershell(self, script):
        return json.dumps(self.signature if 'Get-AuthenticodeSignature' in script else self.procs)
    def processes(self, row):
        return []


class Base(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root=root=Path(tmp.name)
        src=root/'src'; (src/'sets').mkdir(parents=True)
        blobs=dict(terminal=b'MZ fixture terminal',servers=b'fixture servers',ea=b'fixture GOAT V1.49 ex5')
        sources={}
        for key,name in (('terminal','terminal64.exe'),('servers','servers.dat'),('ea','GOAT V1.49.ex5')):
            (src/name).write_bytes(blobs[key]); sources[key]=dict(path=str(src/name),sha256=digest(blobs[key]))
        self.blobs=blobs; self.common=root/'Common'/'Files'; self.common.mkdir(parents=True); (root/'VPS').mkdir()
        self.output=root/'out'; self.lock=root/'lifecycle.lock'
        self.live=[dict(pid=100+i,path=str(root/'Live'/f'0{i+1} - Protected'/'terminal64.exe'),
                        created='2026-10-10T01:00:00.100000Z') for i in range(3)]
        self.host=Host(self.live)
        self.plan=dict(schema='goat-exp-arm-install-v1',experiment='Exp 03',commonFiles=str(self.common),
            outputDirectory=str(self.output),setNamespace='GOAT Experiments/Exp 03 - 2026-10-10',sources=sources,
            ea=dict(buildId='V1.49-BETA17-43',expertRelativePath='MQL5/Experts/GOAT Experiment/GOAT V1.49.ex5',
                    sha256=sources['ea']['sha256'],credentialRelativePath='GOAT/Credentials/api-bearer-exp03-fixture.token'),
            account=dict(server='Darwinex-Demo',currency='USD',leverage=100),
            policy=dict(Mode_Lots=2,Risk=500.0,Mode_Bias=1,memberCount=3),members=[],
            arms=[dict(terminal=9,login=3000200001,directory=str(root/'VPS'/'09 - Exp 03 - AI OFF'),label='Exp 03 - AI OFF',
                       aiLaunch=dict(mode=0,threshold=50,protocol=2)),
                  dict(terminal=10,login=3000200002,directory=str(root/'VPS'/'10 - Exp 03 - AI ON'),label='Exp 03 - AI ON',
                       aiLaunch=dict(mode=2,threshold=50,protocol=2))])
        for i in range(3):
            path=src/'sets'/f'member{i}.set'
            self.plan['members'].append(dict(index=i,source=dict(path=str(path),sha256=''),symbol='EURUSD' if i%2 else 'USDJPY',
                                             strategyName=f'Strategy {i}',name=f'GOAT V1.49 {i:02d},M1_Trds={100+i}.set'))
            self.set_member(i,SET_TEXT.format(i=i))
        self.witnesses=0; self.witness=self.write_witness()

    def set_member(self, i, text, rehash=True):
        member=self.plan['members'][i]; data=utf16(text); Path(member['source']['path']).write_bytes(data)
        if rehash: member['source']['sha256']=digest(data)
        return data

    def write_witness(self, **changes):
        value=dict(schema='goat-protected-terminals-v1',observedAtUtc=time.time()-1,expiresAtUtc=time.time()+600,
                   processes=self.live,expectedCount=len(self.live),lifecycleLock=str(self.lock))
        value.update(changes); self.witnesses+=1
        path=self.root/f'witness-{self.witnesses}.json'; g.write_new(path,value)
        return path

    def run_prepare(self, apply=False, plan=None, witness=None):
        return x.prepare(self.plan if plan is None else plan, self.host, self.witness if witness is None else witness, apply)

    def apply(self):
        self.acl=[]
        def icacls(args, **kw):
            self.acl.append(args); return S(returncode=0)
        with patch.object(x.subprocess,'run',side_effect=icacls):
            return self.run_prepare(True)

    def refused(self, code, plan=None, witness=None, apply=False):
        with self.assertRaises(c.Refused) as caught:
            self.run_prepare(apply,plan,witness)
        self.assertEqual(str(caught.exception),code)

    def changed(self, edit):
        plan=copy.deepcopy(self.plan); edit(plan); return plan

    def set_dir(self, ordinal, label):
        return self.common/'GOAT Experiments'/'Exp 03 - 2026-10-10'/f'{ordinal:02d} - {label}'


class HelperTests(Base):
    def test_helpers_match_exp02_bytes_for_the_exp02_build(self):
        self.assertEqual(x.fresh_chart('GOAT V1.48','Experts\\GOAT Experiment\\GOAT V1.48.ex5'),prep.fresh_chart())
        self.assertEqual(x.chart_expert(c.EXPERT_RELATIVE),('GOAT V1.48','Experts\\GOAT Experiment\\GOAT V1.48.ex5'))
        self.assertEqual(x.bare_chart(),prep.bare_chart())
        self.assertEqual(x.fresh_common(3000109421,'Darwinex-Demo'),prep.fresh_common(3000109421))

    def test_bias_labels(self):
        self.assertEqual(x.bias_label(dict(mode=0,threshold=50,protocol=2)),'OFF')
        self.assertEqual(x.bias_label(dict(mode=2,threshold=50,protocol=2)),'ON / DEMO / 50%')
        self.assertEqual(x.bias_label(dict(mode=2,threshold=70,protocol=1)),'ON / LIVE / 70%')


class DryRunTests(Base):
    def test_dry_run_passes_and_writes_nothing(self):
        before=sorted(str(p) for p in self.root.rglob('*'))
        result=self.run_prepare()
        self.assertEqual(sorted(str(p) for p in self.root.rglob('*')),before)
        self.assertEqual(result['status'],'preflight_passed'); self.assertIs(result['tradingEnabled'],False)
        self.assertEqual(result['experiment'],'Exp 03'); self.assertIs(result['identicalSetBytesAcrossArms'],True)
        self.assertEqual([(a['terminal'],a['login'],a['aiLaunchHeader'],a['biasLabel']) for a in result['arms']],
                         [(9,3000200001,HEADERS[9],'OFF'),(10,3000200002,HEADERS[10],'ON / DEMO / 50%')])
        self.assertEqual([a['directory'] for a in result['arms']],[self.plan['arms'][0]['directory'],self.plan['arms'][1]['directory']])
        self.assertEqual([(m['index'],m['symbol'],m['name'],m['sha256']) for m in result['members']],
                         [(m['index'],m['symbol'],m['name'],m['source']['sha256']) for m in self.plan['members']])
        self.assertEqual([len(f) for f in result['files']],[11,11])
        sets=[{Path(p).name:h for p,h in f.items() if p.endswith('.set')} for f in result['files']]
        self.assertEqual(sets[0],sets[1])

    def test_arms_are_reported_in_terminal_order(self):
        plan=self.changed(lambda p:p['arms'].reverse())
        self.assertEqual([a['terminal'] for a in self.run_prepare(plan=plan)['arms']],[9,10])


class ApplyTests(Base):
    def test_apply_writes_every_file_once_with_identical_sets(self):
        written=[]; real=x.write_new
        def once(path,value):
            written.append(c.canonical(path)); return real(path,value)
        with patch.object(x,'write_new',side_effect=once):
            result=self.apply()
        self.assertEqual(result['status'],'prepared_inert_no_launch')
        self.assertEqual(len(written),len(set(written)))
        names=['installation-intent.json','terminal-09.json','terminal-10.json','portfolio-09.json','portfolio-10.json',
               'reconnect-manifest.json','preparation.json']
        expected={c.canonical(p) for f in result['files'] for p in f}|{c.canonical(self.output/n) for n in names}
        self.assertEqual(set(written),expected)
        for files in result['files']:
            for path,value in files.items(): self.assertEqual(digest(Path(path).read_bytes()),value)
        for member in self.plan['members']:
            source=Path(member['source']['path']).read_bytes()
            off=(self.set_dir(9,'Exp 03 - AI OFF')/member['name']).read_bytes()
            on=(self.set_dir(10,'Exp 03 - AI ON')/member['name']).read_bytes()
            self.assertEqual(off,source); self.assertEqual(on,source)
        for ordinal,arm in ((9,self.plan['arms'][0]),(10,self.plan['arms'][1])):
            directory=Path(arm['directory'])
            data=(self.common/'GOAT'/f'dashboard_state_{directory.name}.tsv').read_bytes()
            self.assertTrue(data.startswith(b'\xff\xfe'))
            text=data.decode('utf-16'); lines=text.split('\r\n')
            self.assertTrue(text.endswith('\r\n')); self.assertEqual(lines[0],HEADERS[ordinal]); self.assertEqual(len(lines),5)
            row=lines[1].split('\t')
            self.assertEqual(row,[str(self.set_dir(ordinal,arm['label'])/self.plan['members'][0]['name']),self.plan['members'][0]['name'],
                                  'USDJPY','Strategy 0','OFF','OFF' if ordinal==9 else 'ON / DEMO / 50%','Risk $500','0','0'])
            self.assertEqual((directory/'terminal64.exe').read_bytes(),self.blobs['terminal'])
            self.assertEqual((directory/'MQL5/Experts/GOAT Experiment/GOAT V1.49.ex5').read_bytes(),self.blobs['ea'])
            common=(directory/'config/common.ini').read_bytes().decode('utf-16')
            self.assertIn(f'Login={arm["login"]}\r\nServer=Darwinex-Demo\r\n',common); self.assertIn('[Experts]\r\nEnabled=0',common)
            self.assertNotIn('<expert>',(directory/'MQL5/Profiles/Charts/Default/chart01.chr').read_bytes().decode('utf-16'))
            chart=(self.output/f'dashboard-{ordinal:02d}.chr').read_bytes().decode('utf-16')
            self.assertIn('name=GOAT V1.49\r\npath=Experts\\GOAT Experiment\\GOAT V1.49.ex5\r\n',chart)
            self.assertIn('Mode_Operation=8\r\nDashboard_Resume_Saved=true\r\nMode_Bias=1\r\nBias_Protocol=2\r\nBias_threshold=50\r\n',chart)
            draft=g.read(self.output/f'portfolio-{ordinal:02d}.json')
            self.assertEqual((draft['aiMode'],draft['aiThreshold'],draft['aiProtocol'],draft['account']),
                             (arm['aiLaunch']['mode'],50,2,arm['login']))
            self.assertEqual([m['sha256'] for m in draft['members']],[m['source']['sha256'] for m in self.plan['members']])
            install=g.read(self.output/f'terminal-{ordinal:02d}.json')
            self.assertEqual(install['credentialRelativePath'],'GOAT/Credentials/api-bearer-exp03-fixture.token')
        self.assertFalse((self.common/'GOAT'/'Credentials').exists())
        rows=x.validate_manifest(g.read(self.output/'reconnect-manifest.json'))
        self.assertEqual([(r['terminal'],r['leverage'],r['buildId']) for r in rows],[(9,100,'V1.49-BETA17-43'),(10,100,'V1.49-BETA17-43')])
        for r in rows: c.verify_files(r,True)
        self.assertEqual(g.read(self.output/'preparation.json')['status'],'prepared_inert_no_launch')
        self.assertEqual([a[1] for a in self.acl],[self.plan['arms'][0]['directory'],self.plan['arms'][1]['directory']])
        self.assertFalse(self.lock.exists())
        with patch.object(x.subprocess,'run') as acl:
            self.refused('output_already_exists',apply=True); acl.assert_not_called()

    def test_acl_failure_stops_before_files_and_releases_lock(self):
        with patch.object(x.subprocess,'run',return_value=S(returncode=5)):
            self.refused('installation_acl_failed',apply=True)
        self.assertFalse((Path(self.plan['arms'][0]['directory'])/'terminal64.exe').exists())
        self.assertFalse((self.common/'GOAT').exists()); self.assertFalse(self.lock.exists())


class RefusalTests(Base):
    def test_source_hash_changed(self):
        self.set_member(1,SET_TEXT.format(i=1)+'Extra=1\n',rehash=False)
        self.refused('source_hash_changed')

    def test_ea_hash_mismatch(self):
        self.refused('ea_hash_mismatch',plan=self.changed(lambda p:p['ea'].update(sha256='a'*64)))

    def test_duplicate_terminal(self):
        def edit(p):
            p['arms'][1].update(terminal=9,directory=str(self.root/'VPS'/'09 - Exp 03 - AI ON'))
        self.refused('duplicate_terminal',plan=self.changed(edit))

    def test_duplicate_login(self):
        self.refused('duplicate_login',plan=self.changed(lambda p:p['arms'][1].update(login=3000200001)))

    def test_exp02_accounts_reserved(self):
        self.refused('exp02_account_reserved',plan=self.changed(lambda p:p['arms'][1].update(login=c.PAIR_ACCOUNTS[8])))

    def test_directory_label_mismatch(self):
        self.refused('arm_directory',plan=self.changed(lambda p:p['arms'][0].update(directory=str(self.root/'VPS'/'09 - Exp 03 - Control'))))
        self.refused('arm_directory',plan=self.changed(lambda p:p['arms'][0].update(directory=str(self.root/'VPS'/'9 - Exp 03 - AI OFF'))))

    def test_existing_directory(self):
        Path(self.plan['arms'][1]['directory']).mkdir()
        self.refused('new_directory_required')

    def test_ai_mode_display_only_refused(self):
        self.refused('ai_launch_mode',plan=self.changed(lambda p:p['arms'][1]['aiLaunch'].update(mode=1)))

    def test_threshold_bounds(self):
        for value in (0,101,'50',50.0,True):
            with self.subTest(value=value):
                self.refused('ai_launch_threshold',plan=self.changed(lambda p:p['arms'][1]['aiLaunch'].update(threshold=value)))

    def test_protocol_three(self):
        self.refused('ai_launch_protocol',plan=self.changed(lambda p:p['arms'][1]['aiLaunch'].update(protocol=3)))

    def test_mode_lots_mismatch(self):
        self.refused('mode_lots_mismatch',plan=self.changed(lambda p:p['policy'].update(Mode_Lots=1)))

    def test_risk_mismatch(self):
        self.refused('risk_mismatch',plan=self.changed(lambda p:p['policy'].update(Risk=250)))
        self.set_member(2,SET_TEXT.format(i=2).replace('Risk=500.0','Risk=500.0||100||10||1000||N'))
        self.refused('risk_mismatch')

    def test_mode_bias_pinned_by_policy(self):
        # A SET whose own AI is on would make the As Optimized arm filter entries on AI.
        self.set_member(1,SET_TEXT.format(i=1).replace('Mode_Bias=1','Mode_Bias=2'))
        self.refused('mode_bias_mismatch')

    def test_ai_off_arm_requires_bias_disabled_policy(self):
        self.refused('ai_off_requires_bias_disabled',plan=self.changed(lambda p:p['policy'].update(Mode_Bias=2)))

    def test_mode_operation_not_nine(self):
        self.set_member(2,SET_TEXT.format(i=2).replace('Mode_Operation=9','Mode_Operation=8'))
        self.refused('mode_operation_mismatch')

    def test_member_count_mismatch(self):
        self.refused('member_count',plan=self.changed(lambda p:p['policy'].update(memberCount=4)))
        self.refused('member_count',plan=self.changed(lambda p:p['members'].pop()))

    def test_member_index_order(self):
        def edit(p):
            p['members'][0]['index'],p['members'][1]['index']=1,0
        self.refused('member_schema',plan=self.changed(edit))

    def test_duplicate_set_key(self):
        self.set_member(0,SET_TEXT.format(i=0)+'Risk=500.0\n')
        self.refused('duplicate_set_input')

    def test_member_filename_and_labels(self):
        self.refused('member_filename',plan=self.changed(lambda p:p['members'][0].update(name='sub\\x.set')))
        self.refused('member_filename',plan=self.changed(lambda p:p['members'][0].update(name='x.chr')))
        self.refused('member_labels',plan=self.changed(lambda p:p['members'][0].update(strategyName='a\tb')))
        self.refused('duplicate_set_path',plan=self.changed(lambda p:p['members'][1].update(name=p['members'][0]['name'][:-4].upper()+'.set')))

    def test_utf8_set_accepted(self):
        member=self.plan['members'][0]; data=b'\xef\xbb\xbf'+SET_TEXT.format(i=0).encode()
        Path(member['source']['path']).write_bytes(data); member['source']['sha256']=digest(data)
        self.assertEqual(self.run_prepare()['status'],'preflight_passed')

    def test_namespaces_must_be_new(self):
        self.set_dir(10,'Exp 03 - AI ON').mkdir(parents=True)
        self.refused('set_namespace_exists')
        self.set_dir(10,'Exp 03 - AI ON').rmdir()
        (self.common/'GOAT'/'AgentPortfolio'/'09 - Exp 03 - AI OFF').mkdir(parents=True)
        self.refused('controller_namespace_exists')

    def test_protected_path_overlap(self):
        for path in (Path(self.plan['arms'][0]['directory'])/'terminal64.exe',self.root/'VPS'/'terminal64.exe'):
            with self.subTest(path=path):
                self.host.procs=self.live+[dict(pid=999,path=str(path),created='2026-10-10T01:00:00+00:00')]
                self.refused('protected_path_overlap',witness=self.write_witness(processes=self.host.procs,expectedCount=4))

    def test_witness_count_mismatch(self):
        self.refused('protected_count_mismatch',witness=self.write_witness(expectedCount=4))
        self.refused('protected_count_mismatch',witness=self.write_witness(expectedCount=0,processes=[]))

    def test_witness_expired(self):
        now=time.time()
        self.refused('protected_witness_expired',witness=self.write_witness(observedAtUtc=now-100,expiresAtUtc=now-1))
        self.refused('protected_witness_expired',witness=self.write_witness(observedAtUtc=now-1,expiresAtUtc=now+9*3600))

    def test_exp02_six_witness_refused(self):
        self.refused('protected_witness_schema',witness=self.write_witness(schema='goat-protected-six-v1'))

    def test_protected_process_changed(self):
        witness=self.write_witness()
        self.host.procs=[dict(p,pid=p['pid']+1) if i==0 else p for i,p in enumerate(self.live)]
        self.refused('protected_process_changed',witness=witness)

    def test_unsigned_terminal_refused(self):
        self.host.signature=dict(status='NotSigned',subject='')
        self.refused('terminal_signature')

    def test_non_demo_server_refused(self):
        self.refused('demo_server_required',plan=self.changed(lambda p:p['account'].update(server='Darwinex-Live')))

    def test_registered_build_must_keep_reviewed_hash(self):
        self.refused('registered_build_hash',plan=self.changed(lambda p:p['ea'].update(buildId=c.BUILD_ID)))

    def test_common_files_root(self):
        self.refused('common_files_root',plan=self.changed(lambda p:p.update(commonFiles=str(self.common.parent))))

    def test_unknown_plan_keys(self):
        cases=[('plan_schema',lambda p:p.update(extra=1)),('plan_schema',lambda p:p.pop('setNamespace')),
               ('plan_schema',lambda p:p.update(schema='goat-demo-pair-install-v1')),
               ('source_allowlist',lambda p:p['sources'].update(extra=p['sources']['ea'])),
               ('source_reference',lambda p:p['sources']['terminal'].update(extra=1)),
               ('ea_schema',lambda p:p['ea'].update(extra=1)),('account_policy',lambda p:p['account'].update(extra=1)),
               ('policy_schema',lambda p:p['policy'].update(extra=1)),('arm_schema',lambda p:p['arms'][0].update(extra=1)),
               ('ai_launch_schema',lambda p:p['arms'][1]['aiLaunch'].update(extra=1)),
               ('member_schema',lambda p:p['members'][2].update(extra=1)),
               ('source_reference',lambda p:p['members'][0]['source'].update(extra=1))]
        for code,edit in cases:
            with self.subTest(code=code):
                self.refused(code,plan=self.changed(edit))

    def test_credential_path_recorded_only_and_bounded(self):
        for value in ('../x.token','GOAT/Credentials/../../x.token','C:/GOAT/Credentials/x.token','GOAT/Other/x.token'):
            with self.subTest(value=value):
                self.refused('credential_path',plan=self.changed(lambda p:p['ea'].update(credentialRelativePath=value)))


class CliTests(Base):
    def test_refusal_reason_without_exception_text(self):
        output=io.StringIO()
        with patch.object(sys,'argv',['prepare','--plan','p','--protected-witness','w']),patch.object(x,'read',return_value={}),\
             patch.object(x,'WindowsHost',return_value=self.host),contextlib.redirect_stdout(output):
            self.assertEqual(x.main(),2)
        result=json.loads(output.getvalue())
        self.assertEqual((result['status'],result['reason'],result['stage']),('needs_review','plan_schema','validate_plan'))

    def test_os_error_diagnostic_does_not_expose_message(self):
        def fail(*args):
            args[4]['stage']='acquire_lifecycle_lock'
            raise FileExistsError(17,'SENSITIVE_EXCEPTION_MESSAGE','SENSITIVE_PATH')
        output=io.StringIO()
        with patch.object(sys,'argv',['prepare','--plan','p','--protected-witness','w','--apply']),patch.object(x,'read',return_value={}),\
             patch.object(x,'prepare',side_effect=fail),patch.object(x,'WindowsHost',return_value=self.host),contextlib.redirect_stdout(output):
            self.assertEqual(x.main(),2)
        result=json.loads(output.getvalue())
        self.assertEqual((result['stage'],result['exceptionType'],result['errno'],result['reason']),
                         ('acquire_lifecycle_lock','FileExistsError',17,'unexpected_error_inspect_retained_preparation'))
        self.assertNotIn('SENSITIVE',output.getvalue())


if __name__=='__main__':
    unittest.main()
