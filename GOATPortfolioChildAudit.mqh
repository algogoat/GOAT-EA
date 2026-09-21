#ifndef GOAT_PORTFOLIO_CHILD_AUDIT_MQH
#define GOAT_PORTFOLIO_CHILD_AUDIT_MQH

// Explicit, inert-demo audit only. Include after DashboardDialog is defined.
// No logs, settings writes, template application, globals or child commands.
// ChartSaveTemplate's /Files/ route is documented in the MQL5 AlgoBook:
// https://www.mql5.com/en/book/applications/charts/charts_tpl
// A true result is a point-in-time input/path observation, not binary attestation
// or a durable promise that a user cannot subsequently change the chart inputs.

string GoatChildAuditTrim(string value)
{
   StringTrimLeft(value); StringTrimRight(value); return value;
}

bool GoatChildAuditIdentifier(const string value)
{
   if(StringLen(value)<1 || StringLen(value)>128) return false;
   for(int i=0;i<StringLen(value);i++)
   {
      ushort c=StringGetCharacter(value,i);
      if(!((c>='A' && c<='Z') || (c>='a' && c<='z') || c=='_' || (i>0 && c>='0' && c<='9'))) return false;
   }
   return true;
}

bool GoatChildAuditAdd(string &names[],string &values[],const string name,const string value)
{
   if(!GoatChildAuditIdentifier(name) || ArraySize(names)>=256 || StringLen(value)>4096) return false;
   for(int i=0;i<ArraySize(names);i++) if(names[i]==name) return false;
   int n=ArraySize(names); ArrayResize(names,n+1); ArrayResize(values,n+1);
   names[n]=name; values[n]=value; return true;
}

bool GoatChildAuditInputs(const string text,string &names[],string &values[])
{
   ArrayResize(names,0); ArrayResize(values,0);
   string audit_lines[]; int count=StringSplit(text,'\n',audit_lines);
   if(count<1 || count>4096 || StringLen(text)>1000000) return false;
   for(int i=0;i<count;i++)
   {
      string line=audit_lines[i]; int length=StringLen(line);
      if(length>0 && StringGetCharacter(line,length-1)=='\r') line=StringSubstr(line,0,length-1);
      string trimmed=GoatChildAuditTrim(line);
      if(trimmed=="" || StringSubstr(trimmed,0,1)==";") continue;
      // Native input-group headings are not input variables.
      if(StringFind(trimmed,"===")==0 && StringSubstr(trimmed,StringLen(trimmed)-1)=="=") continue;
      int split=StringFind(line,"=");
      if(split<1 || !GoatChildAuditAdd(names,values,GoatChildAuditTrim(StringSubstr(line,0,split)),StringSubstr(line,split+1))) return false;
   }
   return ArraySize(names)>0;
}

string GoatChildAuditExpertPath(string value)
{
   StringReplace(value,"/","\\");
   string root=TerminalInfoString(TERMINAL_DATA_PATH)+"\\MQL5\\";
   if(StringFind(value,root)==0) value=StringSubstr(value,StringLen(root));
   if(StringFind(value,"Experts\\")!=0 || StringFind(value,"..")>=0 || StringFind(value,":")>=0) return "";
   StringToLower(value); return value;
}

bool GoatChildAuditTemplate(const string body,const string expected_path,string &names[],string &values[])
{
   string expected=GoatChildAuditExpertPath(expected_path);
   if(expected=="" || StringLen(body)>4000000) return false;
   string audit_lines[],stack[],input_text="",expert_path="";
   int count=StringSplit(body,'\n',audit_lines),experts=0,inputs=0,paths=0;
   bool in_expert=false,in_inputs=false,chart_closed=false;
   if(count<1 || count>65536) return false;
   for(int i=0;i<count;i++)
   {
      string line=audit_lines[i]; int length=StringLen(line);
      if(length>0 && StringGetCharacter(line,length-1)=='\r') line=StringSubstr(line,0,length-1);
      string trimmed=GoatChildAuditTrim(line);
      if(trimmed=="") continue;
      int depth=ArraySize(stack);
      if(StringSubstr(trimmed,0,1)=="<")
      {
         if(StringSubstr(trimmed,StringLen(trimmed)-1)!=">") return false;
         bool closing=(StringSubstr(trimmed,1,1)=="/");
         string tag=StringSubstr(trimmed,(closing ? 2 : 1),StringLen(trimmed)-(closing ? 3 : 2));
         if(!GoatChildAuditIdentifier(tag)) return false;
         if(closing)
         {
            if(depth==0 || stack[depth-1]!=tag) return false;
            if(tag=="inputs" && in_expert) in_inputs=false;
            if(tag=="expert") in_expert=false;
            if(tag=="chart") chart_closed=true;
            ArrayResize(stack,depth-1);
         }
         else
         {
            if(chart_closed || depth>=64 || (depth==0 && tag!="chart") || (depth>0 && tag=="chart")) return false;
            if(tag=="expert")
            {
               if(depth!=1 || stack[0]!="chart" || ++experts!=1) return false;
               in_expert=true;
            }
            else if(in_expert)
            {
               if(tag!="inputs" || depth!=2 || ++inputs!=1) return false;
               in_inputs=true;
            }
            ArrayResize(stack,depth+1); stack[depth]=tag;
         }
         continue;
      }
      if(chart_closed || depth==0) return false;
      if(in_inputs) input_text+=line+"\n";
      else if(in_expert && StringFind(trimmed,"path=")==0)
      {
         if(++paths!=1) return false;
         expert_path=GoatChildAuditExpertPath(StringSubstr(trimmed,5));
      }
   }
   return chart_closed && ArraySize(stack)==0 && experts==1 && inputs==1 && paths==1
      && expert_path==expected && GoatChildAuditInputs(input_text,names,values);
}

// Canonical decimal text, not epsilon/rounded double equality. Exponents and
// unrecognized representations are refused unless the two values are identical.
string GoatChildAuditDecimal(string value)
{
   int length=StringLen(value); if(length<1 || length>128) return "";
   bool negative=false; int start=0,dot=-1,digits=0;
   if(StringSubstr(value,0,1)=="-" || StringSubstr(value,0,1)=="+")
   {negative=StringSubstr(value,0,1)=="-";start=1;}
   for(int i=start;i<length;i++)
   {
      ushort c=StringGetCharacter(value,i);
      if(c=='.'){if(dot>=0) return "";dot=i;}
      else if(c>='0' && c<='9') digits++;
      else return "";
   }
   if(digits==0) return "";
   string whole=StringSubstr(value,start,(dot<0 ? length : dot)-start);
   string fraction=(dot<0 ? "" : StringSubstr(value,dot+1));
   while(StringLen(whole)>0 && StringSubstr(whole,0,1)=="0") whole=StringSubstr(whole,1);
   while(StringLen(fraction)>0 && StringSubstr(fraction,StringLen(fraction)-1)=="0") fraction=StringSubstr(fraction,0,StringLen(fraction)-1);
   if(whole=="") whole="0";
   return (negative && (whole!="0" || fraction!="") ? "-" : "")+whole+(fraction!="" ? "."+fraction : "");
}

bool GoatChildAuditValue(const string name,const string expected,const string actual)
{
   if(expected==actual) return true;
   if(name=="EA_Desc" || name=="Active_Time_ASIA" || name=="Active_Time_EU" || name=="Active_Time_US" || name=="Studio_MonitorRunPath") return false;
   if(name=="Download_StartDate")
   {
      // Native serialization may add explicit midnight to a date-only input.
      string left=expected,right=actual;
      if(StringLen(left)==10) left+=" 00:00:00";
      if(StringLen(right)==10) right+=" 00:00:00";
      if(StringLen(left)==16) left+=":00";
      if(StringLen(right)==16) right+=":00";
      return StringLen(left)==19 && left==right;
   }
   string left=GoatChildAuditDecimal(expected),right=GoatChildAuditDecimal(actual);
   return left!="" && right!="" && left==right;
}

bool GoatChildAuditMaps(const string source,const int mode,const int threshold,const int protocol,const string template_body,const string expected_path)
{
   if(mode<0 || mode>2 || threshold<1 || threshold>100 || (protocol!=1 && protocol!=2)) return false;
   string names[],values[],actual_names[],actual_values[];
   string effective=GoatApplyAILaunchPolicy(source,mode,threshold,protocol);
   if(!GoatChildAuditInputs(effective,names,values) || !GoatChildAuditTemplate(template_body,expected_path,actual_names,actual_values)) return false;
   // The frozen export covers the strategy inputs. These live sinputs are
   // intentionally omitted by WriteSet and must remain at inert-monitor defaults.
   string omitted_names[3]={"Studio_ReadOnlyMonitor","Studio_MonitorRunPath","Dashboard_Resume_Saved"};
   string omitted_values[3]={"false","","false"};
   for(int n=0;n<3;n++)
   {
      bool found=false;
      for(int i=0;i<ArraySize(names);i++) if(names[i]==omitted_names[n])
      {if(values[i]!=omitted_values[n]) return false;found=true;}
      if(!found && !GoatChildAuditAdd(names,values,omitted_names[n],omitted_values[n])) return false;
   }
   if(ArraySize(names)!=ArraySize(actual_names)) return false;
   for(int i=0;i<ArraySize(names);i++)
   {
      bool found=false;
      for(int j=0;j<ArraySize(actual_names);j++) if(names[i]==actual_names[j])
      {if(!GoatChildAuditValue(names[i],values[i],actual_values[j])) return false;found=true;}
      if(!found) return false;
   }
   return true;
}

bool GoatChildAuditRead(const string path,const bool common,const string expected_sha256,string &body)
{
   body="";
   int h=FileOpen(path,FILE_READ|FILE_BIN|FILE_SHARE_READ|(common ? FILE_COMMON : 0));
   if(h==INVALID_HANDLE) return false;
   ulong size=FileSize(h); uchar bytes[],key[],digest[];
   if(size<1 || size>(ulong)(common ? 2000000 : 8000000)){FileClose(h);return false;}
   uint got=FileReadArray(h,bytes,0,(uint)size); FileClose(h);
   if(got!=size) return false;
   if(common)
   {
      if(StringLen(expected_sha256)!=64 || CryptEncode(CRYPT_HASH_SHA256,bytes,key,digest)!=32) return false;
      string actual="";for(int i=0;i<32;i++) actual+=StringFormat("%02x",digest[i]);
      if(actual!=expected_sha256) return false;
   }
   if(size>=2 && bytes[0]==255 && bytes[1]==254)
   {
      if(size%2!=0) return false;
      ushort units[]; int count=(int)size/2-1; ArrayResize(units,count);
      for(int i=0;i<count;i++)
      {units[i]=(ushort)(bytes[2+i*2]+256*bytes[3+i*2]);if(units[i]==0) return false;}
      body=ShortArrayToString(units,0,count);
   }
   else
   {
      int offset=(size>=3 && bytes[0]==239 && bytes[1]==187 && bytes[2]==191 ? 3 : 0);
      body=CharArrayToString(bytes,offset,(int)size-offset,CP_UTF8);
      uchar roundtrip[]; int n=StringToCharArray(body,roundtrip,0,WHOLE_ARRAY,CP_UTF8)-1;
      if(n!=(int)size-offset) return false;
      for(int i=0;i<n;i++) if(roundtrip[i]!=bytes[offset+i]) return false;
   }
   return body!="";
}

bool GoatPortfolioChildSettingsMatch(const int row,const string expected_sha256)
{
   if(Mode_Operation!=Operation_Dash || MQLInfoInteger(MQL_TESTER)
      || AccountInfoInteger(ACCOUNT_TRADE_MODE)!=ACCOUNT_TRADE_MODE_DEMO
      || TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || PositionsTotal()!=0 || OrdersTotal()!=0
      || row<0 || row>=ArraySize(DashboardDialog.g_sets)) return false;
   long cid=DashboardDialog.g_sets[row].cid;
   string symbol=DashboardDialog.g_sets[row].sym;
   if(cid<=0 || cid==ChartID() || ChartSymbol(cid)!=symbol || DashboardDialog.g_sets[row].magic<=0) return false;
   string relative=GoatDashboardCommonSetPath(DashboardDialog.g_sets[row].path),source="";
   if(relative=="" || !GoatChildAuditRead(relative,true,expected_sha256,source)) return false;
   string expected_path=MQLInfoString(MQL_PROGRAM_PATH);
   if(GoatChildAuditExpertPath(expected_path)=="") return false;
   // Generated digits only. No caller-controlled filename, traversal, DLL delete,
   // profile-template copy, recursive removal or cleanup of pre-existing files.
   static ulong serial=0; serial++;
   string filename="GOAT\\ChildAudit\\audit-"+IntegerToString(ChartID())+"-"+IntegerToString(cid)+"-"+IntegerToString((long)GetMicrosecondCount())+"-"+IntegerToString((long)serial)+".tpl";
   FolderCreate("GOAT"); FolderCreate("GOAT\\ChildAudit");
   if(FileIsExist(filename)) return false;
   bool saved=ChartSaveTemplate(cid,"\\Files\\"+filename);
   string snapshot="";
   bool matched=saved && GoatChildAuditRead(filename,false,"",snapshot)
      && GoatChildAuditMaps(source,DashboardDialog.m_ai_launch_mode,DashboardDialog.m_ai_launch_threshold,
                           DashboardDialog.m_ai_launch_protocol,snapshot,expected_path);
   // Even a failed save may leave a partial file. Only this freshly owned name
   // is eligible for removal; success requires confirmed removal of the snapshot.
   bool removed=(!FileIsExist(filename) ? !saved : FileDelete(filename));
   return matched && removed && !FileIsExist(filename)
      && DashboardDialog.g_sets[row].cid==cid && ChartSymbol(cid)==symbol;
}

// Pure fixtures only; never called by runtime initialization/polling. The parent
// can invoke this in an isolated native harness. No filesystem or chart actions.
bool GoatPortfolioChildAuditSelfTest(void)
{
   string source="; fixed export\nEA_Desc=Fixture\nRisk=500.0\nMode_Bias=1\n";
   string inputs="EA_Desc=Fixture\nRisk=500.000\nMode_Bias=1\nStudio_ReadOnlyMonitor=false\nStudio_MonitorRunPath=\nDashboard_Resume_Saved=false\n";
   string head="<chart>\n<expert>\npath=Experts\\GOAT Experiment\\GOAT V1.47.ex5\n<inputs>\n";
   string tail="</inputs>\n</expert>\n</chart>\n";
   string path="Experts\\GOAT Experiment\\GOAT V1.47.ex5";
   if(!GoatChildAuditMaps(source,0,50,2,head+inputs+tail,path)) return false;
   if(GoatChildAuditMaps(source,0,50,2,head+inputs+"Risk=500\n"+tail,path)) return false;
   if(GoatChildAuditMaps(source,0,50,2,head+inputs+"Unknown=1\n"+tail,path)) return false;
   if(GoatChildAuditMaps(source,0,50,2,head+inputs+tail,"Experts\\Other.ex5")) return false;
   if(GoatChildAuditMaps(source,0,50,2,head+inputs+"</inputs>\n</expert>\n",path)) return false;
   if(GoatChildAuditValue("Risk","500.0","500.00000000000001")) return false;
   if(GoatChildAuditValue("EA_Desc","001","1")) return false;
   if(GoatChildAuditValue("Active_Time_ASIA","01:30-11:00","01:30-12:00")) return false;
   if(!GoatChildAuditValue("Download_StartDate","2025.01.01","2025.01.01 00:00:00")) return false;
   string changed=inputs; StringReplace(changed,"Risk=500.000","Risk=501");
   if(GoatChildAuditMaps(source,0,50,2,head+changed+tail,path)) return false;
   string ai=GoatApplyAILaunchPolicy(inputs,2,50,2);
   if(!GoatChildAuditMaps(source,2,50,2,head+ai+tail,path)) return false;
   if(GoatChildAuditMaps(source,2,50,2,head+inputs+tail,path)) return false;
   return true;
}

#endif
