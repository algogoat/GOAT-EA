#ifndef GOAT_STUDIO_SETTING_COMPARE_MQH
#define GOAT_STUDIO_SETTING_COMPARE_MQH
#include "GOATStudioSettingTypes.mqh"
#include "GOATStudioSettingValues.mqh"

string GoatStudioTesterType(const string key)
  {
   if(StringFind("|Expert|Symbol|Period|Currency|Report|","|"+key+"|")>=0) return "string";
   if(StringFind("|FromDate|ToDate|ForwardDate|","|"+key+"|")>=0) return "datetime";
   if(key=="Deposit") return "double";
   if(StringFind("|Model|Optimization|OptimizationCriterion|ForwardMode|ExecutionMode|Leverage|UseLocal|UseRemote|UseCloud|Visual|ReplaceReport|ShutdownTerminal|ProfitInPips|","|"+key+"|")>=0) return "int";
   return "";
  }

#ifdef GOAT_TERMINAL_ISOLATION_V149
bool GoatStudioRunNonceValue(const string value)
  {
   // Internal per-run fitness key (INV-BATCH-01): a non-negative integer, never an
   // optimized axis. OnTesterInit replaces it for every run; no strategy reads it.
   string parts[];StringSplit(value,'|',parts);
   int count=ArraySize(parts);
   if(count!=1 && !(count==9 && parts[1]=="" && parts[3]=="" && parts[5]=="" && parts[7]=="" && parts[8]=="N")) return false;
   for(int p=0;p<(count==1 ? 1 : 7);p+=2)
     {
      if(StringLen(parts[p])<1 || StringLen(parts[p])>19) return false;
      for(int i=0;i<StringLen(parts[p]);i++)
        {ushort c=StringGetCharacter(parts[p],i);if(c<'0' || c>'9') return false;}
     }
   return true;
  }
#endif

bool GoatStudioFixedInternal(const string identity,const string value)
  {
   // These are research defaults, not arbitrary tolerated native additions.
   if(identity=="[Tester]|ProfitInPips") return GoatStudioSettingValueEqual("0",value,"int");
#ifdef GOAT_TERMINAL_ISOLATION_V149
   if(identity=="[TesterInputs]|GOAT_FitnessRunNonce") return GoatStudioRunNonceValue(value);
#endif
   if(StringFind("|Sequence_Export_Enabled|Dashboard_Resume_Saved|Studio_ReadOnlyMonitor|","|"+StringSubstr(identity,15)+"|")>=0
      && StringSubstr(identity,0,15)=="[TesterInputs]|") return value=="false" || value=="0";
   if(identity=="[TesterInputs]|Sequence_Export_Id" || identity=="[TesterInputs]|Studio_MonitorRunPath") return value=="";
   if(identity=="[TesterInputs]|Sequence_Export_Start" || identity=="[TesterInputs]|Sequence_Export_End") return value=="0";
   if(identity=="[TesterInputs]|Sequence_Export_Model") return value=="4";
   return false;
  }

bool GoatStudioConfigOnly(const string identity,const string value)
  {
   // Clipboard omits these startup/native-control fields. The dispatch path
   // independently verifies native worker policy and hashed run controls.
   if(identity=="[Tester]|UseLocal") return value=="1";
   if(identity=="[Tester]|UseRemote" || identity=="[Tester]|UseCloud"
      || identity=="[Tester]|Visual" || identity=="[Tester]|ReplaceReport"
      || identity=="[Tester]|ShutdownTerminal") return value=="0";
   if(identity=="[Tester]|Report") return StringLen(value)>0;
   return false;
  }

bool GoatStudioSemanticINIEqual(const string wanted,const string observed,string &error)
  {
   string expected[],actual[];
   if(!GoatStudioINIEntries(wanted,expected,error) || !GoatStudioINIEntries(observed,actual,error)) return false;
   bool optimization=false,testing=false;
   for(int i=0;i<ArraySize(expected);i++)
      {
       if(expected[i]=="[Tester]|Optimization=1" || expected[i]=="[Tester]|Optimization=2") optimization=true;
       if(expected[i]=="[Tester]|Optimization=0") testing=true;
      }
   // Visual mode is unavailable during optimization. Single-test visual state
   // needs its own native capability and is deliberately outside this route.
   if(!optimization && !testing) {error="Unsupported mode: [Tester]|Optimization";return false;}
   for(int i=0;i<ArraySize(expected);i++)
     {
      int split=StringFind(expected[i],"=");string identity=StringSubstr(expected[i],0,split),value=StringSubstr(expected[i],split+1);
      bool tester=StringSubstr(identity,0,9)=="[Tester]|";
      string key=StringSubstr(identity,tester ? 9 : 15);
      string type=tester ? GoatStudioTesterType(key) : GoatStudioSettingType(key);
      if(type=="") {error="Unsupported setting: "+identity;return false;}
      int matched=-1;
      for(int j=0;j<ArraySize(actual);j++)
        {if(StringSubstr(actual[j],0,StringFind(actual[j],"="))==identity) {matched=j;break;}}
      if(matched<0)
        {
         if(GoatStudioConfigOnly(identity,value) && (identity!="[Tester]|Visual" || optimization)) continue;
         error="Missing setting: "+identity;return false;
        }
      string seen=StringSubstr(actual[matched],StringFind(actual[matched],"=")+1);
      if(tester && (StringFind(value,"||")>=0 || StringFind(seen,"||")>=0))
        {error="Malformed tester scalar: "+identity;return false;}
      if(!tester && type!="string" && !GoatStudioSettingOptimizable(key)
         && (StringFind(value,"||Y")>=0 || StringFind(seen,"||Y")>=0))
        {error="Non-optimizable input: "+identity;return false;}
      if(!GoatStudioSettingValueEqual(value,seen,type)) {error="Setting mismatch: "+identity;return false;}
     }
   for(int j=0;j<ArraySize(actual);j++)
     {
      int split=StringFind(actual[j],"=");string identity=StringSubstr(actual[j],0,split);
      bool found=false;
      for(int i=0;i<ArraySize(expected);i++)
        {if(StringSubstr(expected[i],0,StringFind(expected[i],"="))==identity) {found=true;break;}}
      if(!found && !GoatStudioFixedInternal(identity,StringSubstr(actual[j],split+1)))
        {error="Unexpected setting: "+identity;return false;}
     }
   error="";return true;
  }
#endif