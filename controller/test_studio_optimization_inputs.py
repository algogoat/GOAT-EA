import json,tempfile,unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from studio_optimization_inputs import explicit_optimization_inputs, verify_explicit_inputs
from studio_input_schema import discover
from verify_native_reports import verify_pair,SS,OFFICE

B50_EXPLICIT=('Single_SL_ATR=0.0||0.0||0||0.0||N\r\nSingle_TP_ATR=0.0||0.0||0||0.0||N\r\nSingle_TP_R=0.0||0.0||0||0.0||N\r\n'
 'Single_Exit_Opposite=false||false||0||false||N\r\nSingle_Time_Stop_Bars=0||0||0||0||N\r\nSingle_Time_Stop_TF=0||0||0||0||N\r\n'
 'Rollover_Block_Minutes=0||0||0||0||N\r\n')

class OptimizationInputsTests(unittest.TestCase):
 def setUp(self):
  self.repo=Path(__file__).resolve().parent.parent
  self.schema=json.loads((self.repo/'controller/contracts/v149/inputs.json').read_text())
 def test_actual_header_numeric_input_coverage_excludes_string_and_sinput(self):
  native=discover((self.repo/'GOAT_Inputs_Definitions.mqh').read_bytes(),self.schema['defines'])
  self.assertEqual({k for k,v in native['inputs'].items() if v['declaration']=='input' and v['type']!='string'},{k for k,v in self.schema['inputs'].items() if v['optimizable']})
 def test_consecutive_native_configs_reset_bare_flags_preserving_frozen_source(self):
  first='EA_Desc=first\r\nRSI_Period=7||5||2||9||Y\r\nEMA_Period=10\r\n'
  second='EA_Desc=second\r\nRSI_Period=9\r\nEMA_Period=10||8||2||12||Y\r\n'
  state={}
  def load(text):
   for line in text.splitlines():
    k,v=line.split('=',1);p=v.split('||')
    old=state.get(k,dict(enabled=False,value=None))
    state[k]=dict(value=p[0],enabled=(p[4]=='Y' if len(p)==5 else old['enabled']))
  load(first);load(second);self.assertTrue(state['RSI_Period']['enabled'])
  rendered=explicit_optimization_inputs(second,self.schema);load(rendered)
  self.assertFalse(state['RSI_Period']['enabled']);self.assertTrue(state['EMA_Period']['enabled']);self.assertEqual(state['RSI_Period']['value'],'9')
  self.assertIn('RSI_Period=9\r\n',second);self.assertEqual(explicit_optimization_inputs(rendered,self.schema),rendered)
 def test_strings_metadata_sinput_and_existing_tuples_unchanged(self):
  source='; architecture\r\nEA_Desc=text||Y\r\nMode_Operation=9\r\nDownload_StartDate=2024.12.26\r\nRSI_Period=9||0||1||20||N\r\nGrid_Size=-4||-5||1||-3||Y\r\n'
  self.assertEqual(explicit_optimization_inputs(source,self.schema),source)   # partial text: nothing appended (B50)
 def test_a_b49a_pool_set_gets_the_b50_axes_explicitly_at_their_defaults(self):
  # B50 (A0, GOAT-EA#269 P1): a real pool SET written before B50 (the r8 USDCHF member). Its native inputs gain one
  # fixed line per B50 axis, the same lines the EA writes (scripts/test_optimization_axis_isolation.cjs), so no stale
  # flag of the terminal's tester profile becomes an axis; the SET's own axes keep their tuples.
  from studio_strategy_settings import read_values
  path=self.repo/'controller/fixtures/oosc/r8/deploy/R1696f82a0d700d5c7279/USDCHF/GOAT V1.49 USDCHF,M1_Trds=198_Prf=1990_DD=415_PF=3.82_SR=8.73_ARF=0.295.set'
  text=path.read_bytes().decode('utf-16')
  self.assertNotIn('Single_SL_ATR',text)
  native=explicit_optimization_inputs(text,self.schema)
  self.assertTrue(native.endswith(B50_EXPLICIT))
  self.assertEqual(explicit_optimization_inputs(native,self.schema),native,'idempotent')
  values=read_values(native.encode('utf-16'))
  axes={k for k,v in read_values(path.read_bytes()).items() if k in self.schema['inputs'] and v.endswith('||Y')}
  self.assertEqual(verify_explicit_inputs(values,self.schema,axes),values)
  for name in ('Single_SL_ATR','Single_Time_Stop_TF','Rollover_Block_Minutes'):
   self.assertTrue(values[name].endswith('||N'))
  # A SET that carries a B50 axis keeps its own tuple, with no second line.
  own=text.replace('\r\nEA_Desc=','\r\nSingle_SL_ATR=1.0||0.5||0.5||2.0||Y\r\nEA_Desc=',1)
  rendered=explicit_optimization_inputs(own,self.schema)
  self.assertEqual(rendered.count('\nSingle_SL_ATR='),1);self.assertIn('Single_SL_ATR=1.0||0.5||0.5||2.0||Y',rendered)
 def report(self,path,forward,extra=None):
  root=ET.Element('{'+SS+'}Workbook');props=ET.SubElement(root,'{'+OFFICE+'}DocumentProperties');ET.SubElement(props,'{'+OFFICE+'}Title').text='fixture'
  table=ET.SubElement(ET.SubElement(root,'{'+SS+'}Worksheet'),'{'+SS+'}Table')
  keys=['Pass','Forward Result' if forward else 'Result','Profit','Trades','RSI_Period']+list(extra or {})
  records=[keys]+[[str(i),'0.8',str(50+i*20),str(10+i),'7',*[(extra[k][i]) for k in extra or {}]] for i in range(2)]
  for record in records:
   row=ET.SubElement(table,'{'+SS+'}Row')
   for value in record:ET.SubElement(ET.SubElement(row,'{'+SS+'}Cell'),'{'+SS+'}Data').text=value
  ET.ElementTree(root).write(path,encoding='utf-8',xml_declaration=True)
 def test_native_extra_varying_axis_refuses_even_when_back_forward_match(self):
  with tempfile.TemporaryDirectory() as directory:
   back=Path(directory)/'back.xml';fwd=Path(directory)/'forward.xml'
   for p,forward in [(back,False),(fwd,True)]:self.report(p,forward,{'EMA_Period':['8','12']})
   before=back.read_bytes()
   with self.assertRaisesRegex(ValueError,'Unexpected varying native input axis: EMA_Period'):verify_pair(back,fwd,'fixture',['RSI_Period'])
   self.assertEqual(back.read_bytes(),before)
 def test_native_performance_stats_and_constant_nonaxes_remain_valid(self):
  with tempfile.TemporaryDirectory() as directory:
   back=Path(directory)/'back.xml';fwd=Path(directory)/'forward.xml'
   for p,forward in [(back,False),(fwd,True)]:self.report(p,forward,{'Sharpe Ratio':['1.2','2.1'],'Expected Payoff':['4','5'],'Fixed_Mode':['3','3'],'Comment':['same','same']})
   self.assertEqual(verify_pair(back,fwd,'fixture',['RSI_Period'])['paired_rows'],2)
if __name__=='__main__':unittest.main()
