import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from studio_template_tools import build_set,validate_set

class TemplateToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'original.set'
        self.raw=('; Existing template header\r\n; === Entry ===\r\nEA_Desc=Original\r\nMode=1||0||1||1||N\r\n'
                  '; Keep this comment and blank line\r\n\r\nPeriod=10||10||5||20||Y\r\n; === Exit ===\r\nSize=1.5\r\n').encode('utf-16')
        self.source.write_bytes(self.raw)
        self.schema={'source_sha256':'a'*64,'inputs':{
            'EA_Desc':dict(type='string',optimizable=False),
            'Mode':dict(type='ModeEnum',optimizable=True,enum_choices={'Disabled':0,'Enabled':1}),
            'Period':dict(type='int',optimizable=True),
            'Size':dict(type='double',optimizable=True)}}
        self.policy=dict(header_sha256='a'*64,main_sha256='b'*64,coverage='indicator_mode_gates_only',rules=[dict(input='Period',controller='Mode',disabled=0)])
        self.spec=dict(ea_desc='Readable Candidate',changes={'Period':'15||10||5||25||Y'},rationale={'Period':'Test a wider declared indicator sampling range within development data.'},summary='Untested variant',entry_logic='Enabled mode uses the selected period.',ladder_exits='Exit settings unchanged; their interaction still needs source review.',intended_role='Research candidate pending broker-specific evidence.')

    def tearDown(self):self.tmp.cleanup()

    def build(self,output=None,spec=None,**kw):
        return build_set(self.source,output or self.root/'new.set',spec or self.spec,self.schema,self.policy,controller_version='test',ea_version='1.48',**kw)

    def test_preserves_source_encoding_layout_and_unchanged_values(self):
        result=self.build();out=Path(result['output']['path']).read_bytes()
        self.assertEqual(self.source.read_bytes(),self.raw);self.assertTrue(out.startswith(b'\xff\xfe'))
        before=self.raw.decode('utf-16').splitlines(keepends=True);after=out.decode('utf-16').splitlines(keepends=True)
        self.assertEqual(len(before),len(after))
        for old,new in zip(before,after):
            if not old.startswith(('EA_Desc=','Period=')):self.assertEqual(old,new)
        self.assertEqual(out.decode('utf-16').count('\r\n'),len(after))
        self.assertEqual(result['validation']['active_axes'],{'Period':4})

    def test_provenance_support_and_unique_variant_identity(self):
        one=self.build();two=self.build(self.root/'second.set')
        self.assertNotEqual(one['output']['ea_desc'],two['output']['ea_desc'])
        self.assertEqual(one['source']['sha256'],hashlib.sha256(self.raw).hexdigest())
        self.assertEqual(one['support_sha256'],hashlib.sha256(Path(one['support_path']).read_bytes()).hexdigest())
        receipt=json.loads(Path(one['receipt_path']).read_text())
        self.assertFalse(receipt['source_measurements_inherited']);self.assertTrue(receipt['matrix_registration_required'])
        self.assertEqual(receipt['status'],'untested_variant')
        self.assertIn('source-reference evidence only',Path(one['support_path']).read_text())

    def test_invalid_enum_is_rejected_before_any_output(self):
        spec=self.spec|{'changes':{'Mode':'2'},'rationale':{'Mode':'Unsupported mode must fail.'}}
        with self.assertRaisesRegex(ValueError,'Undeclared enum'):self.build(spec=spec)
        self.assertFalse((self.root/'new.set').exists())

    def test_inactive_range_is_rejected(self):
        spec=self.spec|{'changes':{'Mode':'0'},'rationale':{'Mode':'Disables the searched indicator.'}}
        with self.assertRaisesRegex(ValueError,'Inactive optimization axis'):self.build(spec=spec)

    def test_range_ladder_must_land_on_stop(self):
        spec=self.spec|{'changes':{'Period':'10||10||4||25||Y'}}
        with self.assertRaisesRegex(ValueError,'step ladder'):self.build(spec=spec)

    def test_unknown_input_or_multiline_replacement_rejected(self):
        for changes,reason in [({'Unknown':'1'},'Unknown input'),({'Period':'1\r\nSize=50'},'one bounded')]:
            spec=self.spec|{'changes':changes,'rationale':{k:'Must reject.' for k in changes}}
            with self.assertRaisesRegex(ValueError,reason):self.build(spec=spec)

    def test_requires_per_change_support_rationale(self):
        with self.assertRaisesRegex(ValueError,'own rationale'):self.build(spec=self.spec|{'rationale':{}})
        with self.assertRaisesRegex(ValueError,'Nonempty bounded'):self.build(spec=self.spec|{'entry_logic':''})

    def test_forbids_source_or_existing_output_and_sidecar_overwrite(self):
        with self.assertRaisesRegex(ValueError,'in-place'):self.build(self.source)
        target=self.root/'variant.set';target.with_suffix('.md').write_text('user note')
        with self.assertRaisesRegex(ValueError,'already exists'):self.build(target)
        self.assertEqual(target.with_suffix('.md').read_text(),'user note')
        target.write_bytes(b'user bytes')
        with self.assertRaisesRegex(ValueError,'already exists'):self.build(target)
        self.assertEqual(target.read_bytes(),b'user bytes')

    def test_publisher_catalog_is_immutable(self):
        with self.assertRaisesRegex(ValueError,'publisher catalog'):self.build(forbidden_roots=[self.root])

    def test_encoding_and_mixed_newlines_rejected(self):
        self.source.write_text(self.raw.decode('utf-16'),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'UTF-16 LE BOM'):validate_set(self.source,self.schema,self.policy)
        self.source.write_bytes(self.raw.decode('utf-16').replace('\r\n','\n',1).encode('utf-16'))
        with self.assertRaisesRegex(ValueError,'consistent CRLF'):validate_set(self.source,self.schema,self.policy)

    def test_fixed_export_is_distinguished_from_optimization_template(self):
        self.source.write_bytes(self.raw.decode('utf-16').replace('||Y','||N').encode('utf-16'))
        report=validate_set(self.source,self.schema,self.policy)
        self.assertEqual(report['kind'],'fixed_settings');self.assertFalse(report['execution_ready'])
        with self.assertRaisesRegex(ValueError,'No enabled'):validate_set(self.source,self.schema,self.policy,require_optimization=True)

    def test_read_only_validation_returns_exact_scope_and_axes(self):
        report=validate_set(self.source,self.schema,self.policy,require_optimization=True)
        self.assertEqual(report['cartesian_combinations'],3)
        self.assertEqual(report['dependency_audit']['checked_axes'],['Period'])
        self.assertFalse(report['execution_ready']);self.assertEqual(self.source.read_bytes(),self.raw)

if __name__=='__main__':unittest.main()
