#ifndef GOAT_OPTIMIZATION_INPUTS_MQH
#define GOAT_OPTIMIZATION_INPUTS_MQH
#include "GOATStudioSettingTypes.mqh"
// Native config only: keep the source SET, chosen values and Y ladders intact.
string GoatStudioExplicitOptimizationInputs(const string source)
  {
   string input_lines[],result="";
   int count=StringSplit(source,'\n',input_lines);
   for(int i=0;i<count;i++)
     {
      string line=input_lines[i];StringTrimRight(line);
      int eq=StringFind(line,"=");
      if(eq>0)
        {
         string key=StringSubstr(line,0,eq),value=StringSubstr(line,eq+1);
         if(GoatStudioSettingOptimizable(key) && GoatStudioSettingType(key)!="string" && StringFind(value,"||")<0)
            line=key+"="+value+"||"+value+"||0||"+value+"||N";
        }
      if(i<count-1 || line!="") result+=line+"\r\n";
     }
   // B50:begin b50-explicit
   // B50 (A0, GOAT-EA#269 P1): a SET written before B50 omits the B50 axes, and MT5 keeps the optimize flag and range of an
   // omitted input from the tester profile of the terminal. Each one the SET omits is written at its default, fixed (N).
   string b50_names[];StringSplit(GoatStudioOptimizationNames(),'|',b50_names);
   for(int n=0;n<ArraySize(b50_names);n++)
     {
      string b50_default=GoatStudioAppendedDefault(b50_names[n]);
      if(b50_default=="" || StringFind("\n"+source,"\n"+b50_names[n]+"=")>=0) continue;
      result+=b50_names[n]+"="+b50_default+"||"+b50_default+"||0||"+b50_default+"||N\r\n";
     }
   // B50:end b50-explicit
   return result;
  }

// Called only from OnTesterInit, before queue acceptance or tester passes.
// Every typed optimizable input must be present; no stale native flag is ignored.
bool GoatStudioVerifyOptimizationInputs(const string source,const string description,string &error)
  {
   error="";
   string input_lines[],keys[],values[],names[];
   int count=StringSplit(source,'\n',input_lines);
   for(int i=0;i<count;i++)
     {
      string line=input_lines[i];StringTrimLeft(line);StringTrimRight(line);
      if(line=="" || StringSubstr(line,0,1)==";") continue;
      int eq=StringFind(line,"=");if(eq<=0) {error="Malformed selected member inputs";return false;}
      string key=StringSubstr(line,0,eq);
      for(int j=0;j<ArraySize(keys);j++) if(keys[j]==key) {error="Duplicate selected input: "+key;return false;}
      int n=ArraySize(keys);ArrayResize(keys,n+1);ArrayResize(values,n+1);
      keys[n]=key;values[n]=StringSubstr(line,eq+1);
     }
   int identity=-1;
   for(int i=0;i<ArraySize(keys);i++) if(keys[i]=="EA_Desc") identity=i;
   if(identity<0 || values[identity]!=description) {error="Selected member description mismatch";return false;}
   StringSplit(GoatStudioOptimizationNames(),'|',names);
   for(int i=0;i<ArraySize(names);i++)
     {
      string name=names[i];if(name=="") continue;
      int found=-1;
      for(int j=0;j<ArraySize(keys);j++) if(keys[j]==name) found=j;
      if(found<0 && GoatStudioAppendedDefault(name)=="") {error="Missing selected input: "+name;return false;} // B50 (A0, GOAT-EA#269 P1): a B50 axis may be omitted
      string encoded=(found>=0 ? values[found] : GoatStudioAppendedDefault(name)+"||"+GoatStudioAppendedDefault(name)+"||0||"+GoatStudioAppendedDefault(name)+"||N"),parts[];StringReplace(encoded,"||","\n"); // B50: an omitted one is its default, fixed
      int size=StringSplit(encoded,'\n',parts);
      if((size!=1 && size!=5) || (size==5 && parts[4]!="Y" && parts[4]!="N"))
        {error="Invalid selected input tuple: "+name;return false;}
      bool wanted=size==5 && parts[4]=="Y",enabled=false;
      for(int j=0;j<ArraySize(parts);j++) {if(parts[j]=="false") parts[j]="0";else if(parts[j]=="true") parts[j]="1";}
      string kind=GoatStudioSettingType(name);
      if(kind=="double")
        {
         double dv=0,ds=0,dstep=0,dstop=0;
         if(!ParameterGetRange(name,enabled,dv,ds,dstep,dstop) || enabled!=wanted || dv!=StringToDouble(parts[0])
            || (wanted && (ds!=StringToDouble(parts[1]) || dstep!=StringToDouble(parts[2]) || dstop!=StringToDouble(parts[3]))))
           {error="Native optimization flag/value/range differs: "+name;return false;}
        }
      else
        {
         long lv=0,ls=0,lstep=0,lstop=0;
         if(!ParameterGetRange(name,enabled,lv,ls,lstep,lstop) || enabled!=wanted || lv!=StringToInteger(parts[0])
            || (wanted && (ls!=StringToInteger(parts[1]) || lstep!=StringToInteger(parts[2]) || lstop!=StringToInteger(parts[3]))))
           {error="Native optimization flag/value/range differs: "+name;return false;}
        }
     }
   return true;
  }
#endif
