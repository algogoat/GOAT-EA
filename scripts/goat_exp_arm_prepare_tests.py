"""Exp-arm preparation checks; no terminal, network or credential operations.

The EA sources are the repository's own retained binaries (candidate-builds/*, GOAT V1.48.ex5), read in
place and checked against the controller's real pinned-build table. The host is a fake: its powershell
answers the signature probe and the process inventory, and no arm terminal ever runs. The shared
lifecycle lock is redirected to the temp folder for every test.
"""
import contextlib
import copy
import hashlib
import io
import json
import os
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

EXP02_LOCK=x.LIFECYCLE_LOCK   # captured before any test redirects it
REPO=Path(x.__file__).resolve().parent.parent
B43=REPO/'candidate-builds'/'beta17-B43'/'GOAT V1.49.ex5'
B41=REPO/'candidate-builds'/'beta17-B41'/'GOAT V1.49.ex5'
V148=REPO/'GOAT V1.48.ex5'
B43_SHA='e630ee34cb04c26513f16860a927074ec745f3c62869d984260230a89fd4dc24'
SET_TEXT=('; frozen fixture\nMode_Operation=9\nEA_Desc=Strategy {i}\nMode_Lots=2\nRisk=500.0\nMode_Bias=1\n'
          'Bias_Protocol=1\nBias_threshold=60\nMode_Bias_Trades=0\nActive_Time_ASIA=01:30-11:00\n')
HEADERS={9:'#GOAT_AI_LAUNCH_V147_2\t0\t50\t2',10:'#GOAT_AI_LAUNCH_V147_2\t2\t50\t2'}
LOGINS={9:3000200001,10:3000200002}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def utf16(text):
    return text.replace('\n','\r\n').encode('utf-16')


class Host:
    """powershell -> signature JSON or the running-terminal inventory; per-arm processes -> none."""
    def __init__(self, procs, common, status='Valid', subject='CN=MetaQuotes Ltd., O=MetaQuotes Ltd.'):
        self.procs=procs; self.common=common; self.signature=dict(status=status,subject=subject)
    def powershell(self, script):
        return json.dumps(self.signature if 'Get-AuthenticodeSignature' in script else self.procs)
    def processes(self, row):
        return []
    def common_files(self):
        return self.common


class Base(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root=root=Path(tmp.name)
        self.lock=root/'lifecycle.lock'
        redirect=patch.object(x,'LIFECYCLE_LOCK',str(self.lock)); redirect.start(); self.addCleanup(redirect.stop)
        src=root/'src'; (src/'sets').mkdir(parents=True)
        blobs=dict(terminal=b'MZ fixture terminal',servers=b'fixture servers')
        sources={}
        for key,name in (('terminal','terminal64.exe'),('servers','servers.dat')):
            (src/name).write_bytes(blobs[key]); sources[key]=dict(path=str(src/name),sha256=digest(blobs[key]))
        self.blobs=blobs; sources['ea']=dict(path=str(B43),sha256=digest(B43.read_bytes()))
        self.common=root/'AppData'/'Roaming'/'MetaQuotes'/'Terminal'/'Common'/'Files'; self.common.mkdir(parents=True)
        (root/'VPS').mkdir(); self.output=root/'out'
        self.live=[dict(pid=100+i,path=str(root/'Live'/f'0{i+1} - Protected'/'terminal64.exe'),
                        created='2026-10-10T01:00:00.100000Z') for i in range(3)]
        self.host=Host(list(self.live),str(self.common))
        self.plan=dict(schema='goat-exp-arm-install-v1',experiment='Exp 03',commonFiles=str(self.common),
            outputDirectory=str(self.output),setNamespace='GOAT Experiments/Exp 03 - 2026-10-10',sources=sources,
            ea=dict(buildId='V1.49-BETA17-43',expertRelativePath='MQL5/Experts/GOAT Experiment/GOAT V1.49.ex5',
                    sha256=sources['ea']['sha256']),
            account=dict(server='Darwinex-Demo',currency='USD',leverage=100),
            policy=dict(Mode_Lots=2,Risk=500.0,Mode_Bias=1,memberCount=3),members=[],
            arms=[dict(terminal=9,login=LOGINS[9],directory=str(root/'VPS'/'09 - Exp 03 - AI OFF'),label='Exp 03 - AI OFF',
                       aiLaunch=dict(mode=0,threshold=50,protocol=2)),
                  dict(terminal=10,login=LOGINS[10],directory=str(root/'VPS'/'10 - Exp 03 - AI ON'),label='Exp 03 - AI ON',
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

    def use_ea(self, path, build_id):
        data=Path(path).read_bytes(); self.plan['sources']['ea']=dict(path=str(path),sha256=digest(data))
        self.plan['ea'].update(sha256=digest(data),buildId=build_id)

    def write_witness(self, **changes):
        value=dict(schema='goat-protected-terminals-v1',observedAtUtc=time.time()-1,expiresAtUtc=time.time()+600,
                   processes=self.live,expectedCount=len(self.live),lifecycleLock=str(self.lock))
        value.update(changes); self.witnesses+=1
        path=self.root/f'witness-{self.witnesses}.json'; g.write_new(path,value)
        return path

    def run_prepare(self, apply=False, plan=None, witness=None):
        data=plan if isinstance(plan,bytes) else json.dumps(self.plan if plan is None else plan).encode()
        return x.prepare(data, self.host, self.witness if witness is None else witness, apply)

    def apply(self):
        self.acl=[]
        def icacls(args, **kw):
            self.acl.append(args); return S(returncode=0)
        with patch.object(x.subprocess,'run',side_effect=icacls):
            return self.run_prepare(True)

    def refused(self, code, plan=None, witness=None, apply=False):
        with self.assertRaises(c.Refused) as caught:
            if apply:
                with patch.object(x.subprocess,'run',return_value=S(returncode=0)):
                    self.run_prepare(True,plan,witness)
            else:
                self.run_prepare(False,plan,witness)
        self.assertEqual(str(caught.exception),code)

    def changed(self, edit):
        plan=copy.deepcopy(self.plan); edit(plan); return plan

    def set_dir(self, ordinal, label):
        return self.common/'GOAT Experiments'/'Exp 03 - 2026-10-10'/f'{ordinal:02d} - {label}'

    def junction(self, link, target):
        try:
            import _winapi
            _winapi.CreateJunction(str(target),str(link))
        except (ImportError, AttributeError, OSError):
            self.skipTest('directory junctions are unavailable on this host')
        self.addCleanup(os.rmdir,link)


class HelperTests(Base):
    def test_helpers_match_exp02_bytes_for_the_exp02_build(self):
        self.assertEqual(x.fresh_chart('GOAT V1.48','Experts\\GOAT Experiment\\GOAT V1.48.ex5'),prep.fresh_chart())
        self.assertEqual(x.chart_expert(c.EXPERT_RELATIVE),('GOAT V1.48','Experts\\GOAT Experiment\\GOAT V1.48.ex5'))
        self.assertEqual(x.bare_chart(),prep.bare_chart())
        self.assertEqual(x.fresh_common(3000109421,'Darwinex-Demo'),prep.fresh_common(3000109421))

    def test_bias_labels(self):
        self.assertEqual(x.bias_label(dict(mode=0,threshold=50,protocol=2)),'OFF')
        self.assertEqual(x.bias_label(dict(mode=2,threshold=50,protocol=2)),'ON / DEMO / 50%')

    def test_b43_is_in_the_controller_pinned_table(self):
        table,table_sha=x.build_table()
        self.assertEqual(digest(B43.read_bytes()),B43_SHA)
        self.assertEqual(table.PINNED_BUILDS[B43_SHA],'V1.49-BETA17-43')
        self.assertNotIn(B43_SHA,table.PRE_B38_EXCLUDED)
        self.assertIn(digest(V148.read_bytes()),table.PRE_B38_EXCLUDED)
        self.assertEqual(table_sha,digest((REPO/'controller'/'studio_installed_build.py').read_bytes()))

    def test_lock_is_exp02_shared_lock(self):
        self.assertEqual(EXP02_LOCK,r'C:\GOAT Experiment\Installation Evidence\reconnect-support\reconnect.lock')

    def test_credential_path_is_per_login(self):
        self.assertEqual(x.credential_for('V1.49-BETA17-43',3000200001),'GOAT/Credentials/api-bearer-v149-3000200001.token')

    def test_same_sets_compares_both_arms_with_sources(self):
        a={'x.set':'1'*64}
        self.assertTrue(x.same_sets([dict(a),dict(a)],a))
        self.assertFalse(x.same_sets([dict(a),{'x.set':'2'*64}],a))
        self.assertFalse(x.same_sets([{'x.set':'2'*64}]*2,a))
        self.assertFalse(x.same_sets([dict(a)],a))

    def test_drive_letter_paths_only(self):
        for value in (r'C:\GOAT Experiment\09 - X',r'D:\a\_temp\x'):
            self.assertTrue(x.absolute(value),value)
        for value in (r'\\server\share\x',r'\\?\C:\x',r'\\.\C:\x','C:/x/y','C:\\',r'C:\x\\y',r'C:\x\..\y',r'C:\x\y.',r'relative\x'):
            self.assertFalse(x.absolute(value),value)


class DryRunTests(Base):
    def test_dry_run_passes_and_writes_nothing(self):
        before=sorted(str(p) for p in self.root.rglob('*'))
        result=self.run_prepare()
        self.assertEqual(sorted(str(p) for p in self.root.rglob('*')),before)
        self.assertEqual(result['status'],'preflight_passed'); self.assertIs(result['tradingEnabled'],False)
        self.assertEqual(result['experiment'],'Exp 03'); self.assertIs(result['identicalSetBytesAcrossArms'],True)
        self.assertEqual(result['identicalSetBytesBasis'],'assembled_bytes_vs_source_hashes')
        self.assertEqual((result['buildId'],result['eaSha256']),('V1.49-BETA17-43',B43_SHA))
        self.assertEqual([(a['terminal'],a['login'],a['aiLaunchHeader'],a['biasLabel']) for a in result['arms']],
                         [(9,LOGINS[9],HEADERS[9],'OFF'),(10,LOGINS[10],HEADERS[10],'ON / DEMO / 50%')])
        self.assertEqual([a['directory'] for a in result['arms']],[self.plan['arms'][0]['directory'],self.plan['arms'][1]['directory']])
        self.assertEqual([(m['index'],m['symbol'],m['name'],m['sha256']) for m in result['members']],
                         [(m['index'],m['symbol'],m['name'],m['source']['sha256']) for m in self.plan['members']])
        self.assertEqual([len(f) for f in result['files']],[11,11])
        sets=[{Path(p).name:h for p,h in f.items() if p.endswith('.set')} for f in result['files']]
        self.assertEqual(sets[0],sets[1])

    def test_receipt_hashes_and_unproven_binding(self):
        result=self.run_prepare()
        self.assertEqual(result['planSha256'],digest(json.dumps(self.plan).encode()))
        self.assertEqual(result['witnessSha256'],digest(self.witness.read_bytes()))
        self.assertEqual(result['toolSha256'],digest(Path(x.__file__).read_bytes()))
        self.assertEqual(result['buildTableSha256'],digest((REPO/'controller'/'studio_installed_build.py').read_bytes()))
        self.assertIn('NOT proven',result['chartMagicBinding']); self.assertIn('post-launch read-back',result['chartMagicBinding'])

    def test_credential_paths_derived_per_arm_login(self):
        result=self.run_prepare()
        paths=[a['credentialRelativePath'] for a in result['arms']]
        self.assertEqual(paths,[f'GOAT/Credentials/api-bearer-v149-{LOGINS[9]}.token',f'GOAT/Credentials/api-bearer-v149-{LOGINS[10]}.token'])
        self.assertNotEqual(paths[0],paths[1])

    def test_arms_are_reported_in_terminal_order(self):
        plan=self.changed(lambda p:p['arms'].reverse())
        self.assertEqual([a['terminal'] for a in self.run_prepare(plan=plan)['arms']],[9,10])


class ApplyTests(Base):
    def test_apply_writes_every_file_once_with_identical_sets(self):
        written=[]; real=x.write_new; locks=[]; real_lock=x.lifecycle_lock
        def once(path,value):
            written.append(c.canonical(path)); return real(path,value)
        def lock(witness):
            locks.append(witness['lifecycleLock']); return real_lock(witness)
        with patch.object(x,'write_new',side_effect=once),patch.object(x,'lifecycle_lock',side_effect=lock):
            result=self.apply()
        self.assertEqual(result['status'],'prepared_inert_no_launch'); self.assertEqual(locks,[str(self.lock)])
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
            self.assertEqual(digest((directory/'MQL5/Experts/GOAT Experiment/GOAT V1.49.ex5').read_bytes()),B43_SHA)
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
            self.assertEqual(install['credentialRelativePath'],f'GOAT/Credentials/api-bearer-v149-{arm["login"]}.token')
        self.assertFalse((self.common/'GOAT'/'Credentials').exists())
        table,_=x.build_table()
        rows=x.validate_manifest(g.read(self.output/'reconnect-manifest.json'),table)
        self.assertEqual([(r['terminal'],r['leverage'],r['buildId'],r['credentialRelativePath']) for r in rows],
                         [(n,100,'V1.49-BETA17-43',f'GOAT/Credentials/api-bearer-v149-{LOGINS[n]}.token') for n in (9,10)])
        for r in rows: c.verify_files(r,True)
        receipt=g.read(self.output/'preparation.json')
        self.assertEqual((receipt['status'],receipt['identicalSetBytesAcrossArms'],receipt['identicalSetBytesBasis']),
                         ('prepared_inert_no_launch',True,'installed_files_rehashed_both_arms'))
        self.assertEqual(receipt['planSha256'],g.read(self.output/'installation-intent.json')['planSha256'])
        self.assertEqual([a[1] for a in self.acl],[self.plan['arms'][0]['directory'],self.plan['arms'][1]['directory']])
        self.assertFalse(self.lock.exists())
        with patch.object(x.subprocess,'run') as acl:
            self.refused('output_already_exists',apply=True); acl.assert_not_called()

    def test_acl_failure_stops_before_files_and_releases_lock(self):
        with patch.object(x.subprocess,'run',return_value=S(returncode=5)),self.assertRaises(c.Refused) as caught:
            self.run_prepare(True)
        self.assertEqual(str(caught.exception),'installation_acl_failed')
        self.assertFalse((Path(self.plan['arms'][0]['directory'])/'terminal64.exe').exists())
        self.assertFalse((self.common/'GOAT').exists()); self.assertFalse(self.lock.exists())

    def test_installed_set_bytes_rehashed_across_both_arms(self):
        # Arm 09's SET changes after its own check passed: only the cross-arm re-hash can see it.
        real=c.verify_files; target=self.set_dir(9,'Exp 03 - AI OFF')/self.plan['members'][0]['name']
        def verify(row,closed=False):
            if row['terminal']==10: target.write_bytes(target.read_bytes()+b'x')
            return real(row,closed)
        with patch.object(x.conn,'verify_files',side_effect=verify):
            self.refused('installed_set_bytes_differ',apply=True)
        self.assertFalse((self.output/'preparation.json').exists()); self.assertFalse(self.lock.exists())

    def test_witness_change_inside_lock_refuses(self):
        real=x.checked_witness_n; calls=[]
        def witness(path,host,expected=None,now=None):
            calls.append(expected)
            if expected is not None: self.host.procs=self.host.procs+[dict(pid=999,path=str(self.root/'New'/'terminal64.exe'),
                                                                         created='2026-10-10T02:00:00+00:00')]
            return real(path,host,expected,now)
        with patch.object(x,'checked_witness_n',side_effect=witness):
            self.refused('protected_inventory_incomplete',apply=True)
        self.assertFalse(self.output.exists()); self.assertFalse(self.lock.exists())


class RefusalTests(Base):
    def test_source_hash_changed(self):
        self.set_member(1,SET_TEXT.format(i=1)+'Extra=1\n',rehash=False)
        self.refused('source_hash_changed')

    def test_ea_hash_mismatch(self):
        self.refused('ea_hash_mismatch',plan=self.changed(lambda p:p['ea'].update(sha256='a'*64)))

    def test_b43_build_id_with_another_pinned_binary(self):
        self.use_ea(B41,'V1.49-BETA17-43'); self.refused('ea_build_mismatch')

    def test_unpinned_binary(self):
        path=self.root/'src'/'GOAT V1.49.ex5'; path.write_bytes(b'unpinned fixture ex5')
        self.use_ea(path,'V1.49-BETA17-43'); self.refused('ea_build_not_pinned')

    def test_pre_b38_binary(self):
        self.use_ea(V148,'V1.48-SEQUENCE-EXPORT-1'); self.refused('ea_build_pre_b38')

    def test_pinned_build_without_verified_credential_pattern(self):
        self.use_ea(B41,'V1.49-BETA17-41'); self.refused('credential_pattern_unknown')

    def test_duplicate_terminal(self):
        def edit(p):
            p['arms'][1].update(terminal=9,directory=str(self.root/'VPS'/'09 - Exp 03 - AI ON'))
        self.refused('duplicate_terminal',plan=self.changed(edit))

    def test_duplicate_login(self):
        self.refused('duplicate_login',plan=self.changed(lambda p:p['arms'][1].update(login=LOGINS[9])))

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

    def test_protocol_must_be_demo_feed(self):
        for arm in (0,1):
            for value in (1,3,'2',True):
                with self.subTest(arm=arm,value=value):
                    self.refused('ai_launch_protocol',plan=self.changed(lambda p:p['arms'][arm]['aiLaunch'].update(protocol=value)))

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

    def test_running_terminal_missing_from_witness(self):
        self.host.procs=self.live+[dict(pid=998,path=str(self.root/'Other'/'07 - Unlisted'/'terminal64.exe'),
                                        created='2026-10-10T01:00:00+00:00')]
        self.refused('protected_inventory_incomplete')

    def test_arm_inside_unlisted_terminal_directory(self):
        # Running but unwitnessed: the inventory refuses. Present but stopped: the ancestor walk refuses.
        self.host.procs=self.live+[dict(pid=997,path=str(self.root/'VPS'/'terminal64.exe'),created='2026-10-10T01:00:00+00:00')]
        self.refused('protected_inventory_incomplete')
        self.host.procs=list(self.live); (self.root/'VPS'/'terminal64.exe').write_bytes(b'stopped terminal')
        self.refused('terminal_ancestor')

    def test_reparse_point_ancestor(self):
        link=self.root/'Link'; self.junction(link,self.root/'VPS')
        def edit(p):
            p['arms'][0]['directory']=str(link/'09 - Exp 03 - AI OFF')
        self.refused('reparse_ancestor',plan=self.changed(edit))

    def test_witness_count_mismatch(self):
        self.refused('protected_count_mismatch',witness=self.write_witness(expectedCount=4))
        self.refused('protected_count_mismatch',witness=self.write_witness(expectedCount=0,processes=[]))

    def test_witness_expired(self):
        now=time.time()
        self.refused('protected_witness_expired',witness=self.write_witness(observedAtUtc=now-100,expiresAtUtc=now-1))
        self.refused('protected_witness_expired',witness=self.write_witness(observedAtUtc=now-1,expiresAtUtc=now+9*3600))

    def test_lifecycle_lock_pinned_in_code(self):
        self.refused('lifecycle_lock_path_mismatch',witness=self.write_witness(lifecycleLock=str(self.root/'other.lock')))
        self.refused('lifecycle_lock_path_mismatch',witness=self.write_witness(lifecycleLock=str(self.lock).upper()))

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

    def test_common_files_must_be_the_exact_appdata_path(self):
        self.refused('common_files_root',plan=self.changed(lambda p:p.update(commonFiles=str(self.common).upper())))
        self.refused('common_files_root',plan=self.changed(lambda p:p.update(commonFiles=str(self.common.parent))))
        self.host.common=''
        self.refused('common_files_root')

    def test_drive_letter_paths_only(self):
        for bad in (r'\\server\share\out',r'\\?\C:\out',r'\\.\C:\out',str(self.output).replace('\\','/')):
            with self.subTest(bad=bad):
                self.refused('absolute_paths',plan=self.changed(lambda p:p.update(outputDirectory=bad)))
        self.refused('arm_directory',plan=self.changed(lambda p:p['arms'][0].update(directory=r'\\server\share\09 - Exp 03 - AI OFF')))
        self.refused('source_reference',plan=self.changed(lambda p:p['sources']['terminal'].update(path='\\\\?\\'+p['sources']['terminal']['path'])))

    def test_output_common_and_arm_folders_must_not_overlap(self):
        arm=self.plan['arms'][0]['directory']
        cases=[lambda p:p.update(outputDirectory=str(self.common/'out')),
               lambda p:p.update(outputDirectory=arm+'\\out'),
               lambda p:p['arms'][0].update(directory=str(self.common/'09 - Exp 03 - AI OFF'))]
        for index,edit in enumerate(cases):
            with self.subTest(case=index):
                self.refused('path_overlap',plan=self.changed(edit))

    def test_plan_bytes(self):
        self.refused('plan_json',plan=b'{not json')
        self.refused('duplicate_json_key',plan=b'{"schema":1,"schema":2}')
        self.refused('plan_size',plan=b'')

    def test_unknown_plan_keys(self):
        cases=[('plan_schema',lambda p:p.update(extra=1)),('plan_schema',lambda p:p.pop('setNamespace')),
               ('plan_schema',lambda p:p.update(schema='goat-demo-pair-install-v1')),
               ('source_allowlist',lambda p:p['sources'].update(extra=p['sources']['ea'])),
               ('source_reference',lambda p:p['sources']['terminal'].update(extra=1)),
               ('ea_schema',lambda p:p['ea'].update(extra=1)),
               ('ea_schema',lambda p:p['ea'].update(credentialRelativePath='GOAT/Credentials/shared.token')),
               ('account_policy',lambda p:p['account'].update(extra=1)),
               ('policy_schema',lambda p:p['policy'].update(extra=1)),('arm_schema',lambda p:p['arms'][0].update(extra=1)),
               ('ai_launch_schema',lambda p:p['arms'][1]['aiLaunch'].update(extra=1)),
               ('member_schema',lambda p:p['members'][2].update(extra=1)),
               ('source_reference',lambda p:p['members'][0]['source'].update(extra=1))]
        for code,edit in cases:
            with self.subTest(code=code):
                self.refused(code,plan=self.changed(edit))


class CliTests(Base):
    def run_main(self, argv):
        output=io.StringIO()
        with patch.object(sys,'argv',['prepare']+argv),patch.object(x,'ArmHost',return_value=self.host),contextlib.redirect_stdout(output):
            code=x.main()
        return code,output.getvalue()

    def test_dry_run_receipt_hashes_raw_plan_file(self):
        path=self.root/'plan.json'; data=json.dumps(self.plan,indent=1).encode(); path.write_bytes(data)
        code,text=self.run_main(['--plan',str(path),'--protected-witness',str(self.witness)])
        result=json.loads(text)
        self.assertEqual((code,result['status'],result['planSha256']),(0,'preflight_passed',digest(data)))

    def test_refusal_reason_without_exception_text(self):
        path=self.root/'plan.json'; path.write_bytes(b'{}')
        code,text=self.run_main(['--plan',str(path),'--protected-witness',str(self.witness)])
        result=json.loads(text)
        self.assertEqual((code,result['status'],result['reason'],result['stage']),(2,'needs_review','plan_schema','validate_plan'))

    def test_os_error_diagnostic_does_not_expose_message(self):
        def fail(*args):
            args[4]['stage']='acquire_lifecycle_lock'
            raise FileExistsError(17,'SENSITIVE_EXCEPTION_MESSAGE','SENSITIVE_PATH')
        path=self.root/'plan.json'; path.write_bytes(b'{}')
        with patch.object(x,'prepare',side_effect=fail):
            code,text=self.run_main(['--plan',str(path),'--protected-witness','w','--apply'])
        result=json.loads(text)
        self.assertEqual((code,result['stage'],result['exceptionType'],result['errno'],result['reason']),
                         (2,'acquire_lifecycle_lock','FileExistsError',17,'unexpected_error_inspect_retained_preparation'))
        self.assertNotIn('SENSITIVE',text)


if __name__=='__main__':
    unittest.main()
