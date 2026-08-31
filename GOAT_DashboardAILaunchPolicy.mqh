#ifndef GOAT_DASHBOARD_AI_LAUNCH_POLICY_MQH
#define GOAT_DASHBOARD_AI_LAUNCH_POLICY_MQH

// Dashboard-only policy. No EA inputs are added or renamed.
enum ENUM_GOAT_AI_LAUNCH_MODE
  {
   GOAT_AI_LAUNCH_AS_OPTIMIZED=0,
   GOAT_AI_LAUNCH_DISPLAY_ONLY,
   GOAT_AI_LAUNCH_ENTRY_FILTER
  };

int GoatNormalizeAILaunchMode(const int mode)
  {
   if(mode<GOAT_AI_LAUNCH_AS_OPTIMIZED || mode>GOAT_AI_LAUNCH_ENTRY_FILTER)
      return GOAT_AI_LAUNCH_AS_OPTIMIZED;
   return mode;
  }

string GoatAILaunchModeLabel(const int mode)
  {
   if(mode==GOAT_AI_LAUNCH_DISPLAY_ONLY) return "Display Only";
   if(mode==GOAT_AI_LAUNCH_ENTRY_FILTER) return "Entry Filter";
   return "As Optimized";
  }

bool GoatParseAILaunchThreshold(string raw,int &threshold)
  {
   StringTrimLeft(raw);
   StringTrimRight(raw);
   if(StringLen(raw)<1 || StringLen(raw)>3) return false;
   for(int i=0;i<StringLen(raw);++i)
      if(StringGetCharacter(raw,i)<'0' || StringGetCharacter(raw,i)>'9') return false;
   int value=(int)StringToInteger(raw);
   if(value<1 || value>100) return false;
   threshold=value;
   return true;
  }

string GoatAILaunchInputValue(const int mode,const int threshold,const string name,const string source)
  {
   int policy=GoatNormalizeAILaunchMode(mode);
   if(policy==GOAT_AI_LAUNCH_AS_OPTIMIZED) return source;
   if(name=="Mode_Bias") return(policy==GOAT_AI_LAUNCH_DISPLAY_ONLY ? "0" : "2");
   if(name=="Bias_threshold") return IntegerToString(threshold);
   // Calibrated feed; gate new sequences only. Never select AI closes/rescue.
   if(name=="Bias_Protocol") return "1";
   if(name=="Mode_Bias_Trades") return "0";
   return source;
  }

string GoatApplyAILaunchPolicy(const string source,const int mode,const int threshold)
  {
   if(GoatNormalizeAILaunchMode(mode)==GOAT_AI_LAUNCH_AS_OPTIMIZED) return source;
   string names[4]={"Mode_Bias","Bias_threshold","Bias_Protocol","Mode_Bias_Trades"};
   bool found[4]={false,false,false,false};
   string input_lines[];
   int count=StringSplit(source,'\n',input_lines);
   string result="";
   for(int i=0;i<count;++i)
     {
      string line=input_lines[i];
      int length=StringLen(line);
      if(length>0 && StringGetCharacter(line,length-1)=='\r')
         line=StringSubstr(line,0,length-1);
      if(i==count-1 && line=="") continue;
      int split=StringFind(line,"=");
      if(split>0)
        {
         string name=StringSubstr(line,0,split);
         string value=StringSubstr(line,split+1);
         for(int n=0;n<4;++n)
            if(name==names[n]) found[n]=true;
         line=name+"="+GoatAILaunchInputValue(mode,threshold,name,value);
        }
      result+=line+"\r\n";
     }
   // Older exports can omit inputs; explicit overrides must still be effective.
   for(int n=0;n<4;++n)
      if(!found[n]) result+=names[n]+"="+GoatAILaunchInputValue(mode,threshold,names[n],"")+"\r\n";
   return result;
  }

bool GoatAILaunchPolicySelfTest(void)
  {
   string source="Mode_Bias=1\r\nBias_threshold=60\r\nBias_Protocol=1\r\nMode_Bias_Trades=0\r\nMode_Bias_Exit=1\r\nMode_News=3\r\nNews_threshold=85\r\nRisk=100\r\n";
   string unchanged="Mode_Bias_Exit=1\r\nMode_News=3\r\nNews_threshold=85\r\nRisk=100\r\n";
   if(GoatApplyAILaunchPolicy(source,GOAT_AI_LAUNCH_AS_OPTIMIZED,75)!=source) return false;
   if(GoatApplyAILaunchPolicy(source,99,75)!=source) return false;
   if(GoatApplyAILaunchPolicy(source,GOAT_AI_LAUNCH_DISPLAY_ONLY,75)!=
      "Mode_Bias=0\r\nBias_threshold=75\r\nBias_Protocol=1\r\nMode_Bias_Trades=0\r\n"+unchanged) return false;
   if(GoatApplyAILaunchPolicy(source,GOAT_AI_LAUNCH_ENTRY_FILTER,75)!=
      "Mode_Bias=2\r\nBias_threshold=75\r\nBias_Protocol=1\r\nMode_Bias_Trades=0\r\n"+unchanged) return false;
   if(GoatApplyAILaunchPolicy("Risk=100\r\n",GOAT_AI_LAUNCH_ENTRY_FILTER,60)!=
      "Risk=100\r\nMode_Bias=2\r\nBias_threshold=60\r\nBias_Protocol=1\r\nMode_Bias_Trades=0\r\n") return false;
   int threshold=60;
   if(!GoatParseAILaunchThreshold(" 75 ",threshold) || threshold!=75) return false;
   if(!GoatParseAILaunchThreshold("1",threshold) || !GoatParseAILaunchThreshold("100",threshold)) return false;
   if(GoatParseAILaunchThreshold("",threshold) || GoatParseAILaunchThreshold("0",threshold) ||
      GoatParseAILaunchThreshold("101",threshold) || GoatParseAILaunchThreshold("60x",threshold) ||
      GoatParseAILaunchThreshold("60.5",threshold) || GoatParseAILaunchThreshold("-1",threshold)) return false;
   return true;
  }

#endif
