#ifndef GOAT_STUDIO_NATIVE_MQH
#define GOAT_STUDIO_NATIVE_MQH
// Managed launch verification must preserve strings and complete optimizer tuples.
// Do not use the legacy export comparator: it discards ranges and coerces text.
bool GoatStudioINIEntries(const string ini,string &entries[],string &error)
  {
   ArrayResize(entries,0); error="";
   string ini_lines[],section="",keys[];
   int count=StringSplit(ini,'\n',ini_lines);
   for(int i=0;i<count;i++)
     {
      string line=ini_lines[i]; StringTrimLeft(line); StringTrimRight(line);
      if(line=="" || StringGetCharacter(line,0)==';') continue;
      if(StringGetCharacter(line,0)=='[')
        {
         if(StringLen(line)<3 || StringGetCharacter(line,StringLen(line)-1)!=']')
           {error="Malformed INI section";return false;}
         section=line;
         if(section!="[Tester]" && section!="[TesterInputs]")
           {error="Unexpected INI section: "+section;return false;}
         continue;
        }
      int separator=StringFind(line,"=");
      if(section=="" || separator<=0) {error="Malformed INI assignment";return false;}
      string key=StringSubstr(line,0,separator); StringTrimRight(key);
      string identity=section+"|"+key;
      for(int j=0;j<ArraySize(keys);j++)
         if(keys[j]==identity) {error="Duplicate INI input: "+identity;return false;}
      int n=ArraySize(entries); ArrayResize(entries,n+1); ArrayResize(keys,n+1);
      keys[n]=identity;
      // Full value is retained, including text, leading value spaces, ranges,
      // steps and flags. Only insignificant outer line whitespace is trimmed.
      entries[n]=identity+"="+StringSubstr(line,separator+1);
     }
   if(ArraySize(entries)==0) {error="Empty INI configuration";return false;}
   return true;
  }

bool GoatStudioINIEqual(const string wanted,const string observed,string &error)
  {
   string expected[],actual[];
   if(!GoatStudioINIEntries(wanted,expected,error) || !GoatStudioINIEntries(observed,actual,error)) return false;
   if(ArraySize(expected)!=ArraySize(actual)) {error="Tester setting count differs";return false;}
   for(int i=0;i<ArraySize(expected);i++)
     {
      bool found=false;
      for(int j=0;j<ArraySize(actual);j++) if(expected[i]==actual[j]) {found=true;break;}
      if(!found) {error="Tester setting mismatch: "+StringSubstr(expected[i],0,StringFind(expected[i],"="));return false;}
     }
   error="";return true;
  }
#endif
