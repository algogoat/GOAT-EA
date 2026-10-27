#ifndef GOAT_STUDIO_EXPORT_DATES_MQH
#define GOAT_STUDIO_EXPORT_DATES_MQH
#include "GOATStudioSettingValues.mqh"

string GoatStudioExportDateValue(const string ini,const string key)
  {
   string export_lines[],section="",value="#ABSENT#";
   int count=StringSplit(ini,'\n',export_lines);
   for(int i=0;i<count;i++)
     {
      string line=export_lines[i]; StringTrimLeft(line); StringTrimRight(line);
      if(line=="" || StringSubstr(line,0,1)==";") continue;
      if(StringSubstr(line,0,1)=="[") {section=line;continue;}
      if(section!="[TesterInputs]") continue;
      int split=StringFind(line,"="); if(split<1) continue;
      string name=StringSubstr(line,0,split); StringTrimLeft(name); StringTrimRight(name);
      if(name!=key) continue;
      if(value!="#ABSENT#") return "#DUPLICATE#";
      value=StringSubstr(line,split+1); StringTrimLeft(value); StringTrimRight(value);
     }
   return value;
  }

bool GoatStudioExportDatesEqual(const string wanted,const string observed,string &error)
  {
   string keys[]; ArrayResize(keys,2); keys[0]="Sequence_Export_Start"; keys[1]="Sequence_Export_End";
   string first=GoatStudioExportDateValue(wanted,keys[0]),last=GoatStudioExportDateValue(wanted,keys[1]);
   if(first=="#ABSENT#" && last=="#ABSENT#")
     {
      if(GoatStudioSettingValueEqual("true",GoatStudioExportDateValue(wanted,"Sequence_Export_Enabled"),"bool"))
        {error="Sequence export dates missing from enabled capture";return false;}
      return true;
     }
   for(int i=0;i<2;i++)
     {
      string expected=GoatStudioExportDateValue(wanted,keys[i]);
      string actual=GoatStudioExportDateValue(observed,keys[i]);
      if(expected=="#ABSENT#" || actual=="#ABSENT#" || expected=="#DUPLICATE#" || actual=="#DUPLICATE#"
         || StringFind(expected,"||Y")>=0 || StringFind(actual,"||Y")>=0
         || !GoatStudioSettingValueEqual(expected,actual,"datetime"))
        {error="Sequence export date mismatch: "+keys[i];return false;}
     }
   error="";return true;
  }
#endif
