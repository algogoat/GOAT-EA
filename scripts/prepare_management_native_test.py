"""Generate an explicitly TESTER-ONLY integration build, never an admitted EA.

MT5 Tester cannot perform WebRequest or retain positions between separate runs.
This harness injects ONLY auth transport/identity, simulates sequence reinit inside
one native tester session, and uses native orders, storage and production exits.
Cold terminal restart with broker fills remains a separate demo release gate.
"""
from pathlib import Path
import argparse, json, shutil, hashlib
def read(p): return p.read_text(encoding='utf-8-sig')
def write(p,s): p.write_bytes(b'\xef\xbb\xbf'+s.replace('\r\n','\n').replace('\n','\r\n').encode())
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 shutil.copytree(a.source.parent,a.output)
 main=read(a.source)
 main=main.replace('g_GOATManager=(!test_context && Mode_Operation==Operation_Standard);','g_GOATManager=(Mode_Operation==Operation_Standard);')
 # Native tester never calls the broker HTTP authority. Production artifacts have no seam.
 boot=read(a.output/'GOATManagementBoot.mqh')
 boot=boot.replace('   if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD)) return true;\n','')
 boot=boot.replace('GOATBuildAuthenticatedRequestHeaders(headers)','GOATFixtureHeaders(headers)').replace('int status=WebRequest(','int status=GOATFixtureWebRequest(')
 declarations='''int g_fixtureStatus=-1;
string g_fixtureReply="";
bool GOATFixtureHeaders(string &headers) {headers="fixture";return true;}
int GOATFixtureWebRequest(string method,string url,string headers,int wait,const char &body[],char &result[],string &response_headers)
{StringToCharArray(g_fixtureReply,result,0,WHOLE_ARRAY,CP_UTF8);ArrayResize(result,ArraySize(result)-1);return g_fixtureStatus;}
'''
 write(a.output/'GOATManagementBoot.mqh',declarations+boot)
 recovery=read(a.output/'GOATSequenceRecovery.mqh')
 recovery=recovery.replace('!TerminalInfoInteger(TERMINAL_CONNECTED)','(!MQLInfoInteger(MQL_TESTER) && !TerminalInfoInteger(TERMINAL_CONNECTED))')
 recovery=recovery.replace('g_GOATManagerAccount<=0','(!MQLInfoInteger(MQL_TESTER) && g_GOATManagerAccount<=0)')
 write(a.output/'GOATSequenceRecovery.mqh',recovery)
 # Rename event entrypoints and all internal calls. Wrapper explicitly refuses live use.
 for event in ('OnInit','OnTick','OnTimer','OnDeinit','OnTester'):
  import re
  main=re.sub(r'\b'+event+r'\b','GOATNative_'+event,main)
 main+='\n'+read(Path(__file__).parent/'management_native_harness.mqh')
 write(a.output/a.source.name,main)
 manifest={'source':str(a.source),'sourceSha256':hashlib.sha256(a.source.read_bytes()).hexdigest(),'harness':str(a.output/a.source.name),'productionBinary':False,'testerOnly':True,'realColdRestart':False}
 (a.output/'native-test-manifest.json').write_text(json.dumps(manifest,indent=2))
 print(manifest)
if __name__=='__main__': main()
