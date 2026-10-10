import json,tempfile,unittest
from pathlib import Path
import xml.etree.ElementTree as ET
from studio_optimization_inputs import explicit_optimization_inputs
from studio_input_schema import discover
from verify_native_reports import verify_pair,SS,OFFICE

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
  self.assertEqual(explicit_optimization_inputs(source,self.schema),source)
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
