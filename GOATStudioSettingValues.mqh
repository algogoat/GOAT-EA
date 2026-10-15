#ifndef GOAT_STUDIO_SETTING_VALUES_MQH
#define GOAT_STUDIO_SETTING_VALUES_MQH
// Exact decimal normalization without floating-point tolerance or text coercion.
string GoatStudioDecimal(const string value,const bool integer=false)
  {
   int n=StringLen(value),p=0,sign=1,exponent=0,fraction=0; string digits="";
   if(n==0 || n>128) return "#INVALID#";
   if(StringSubstr(value,p,1)=="-" || StringSubstr(value,p,1)=="+")
     {if(StringSubstr(value,p,1)=="-") sign=-1;p++;}
   bool point=false,seen=false;
   while(p<n)
     {
      ushort c=StringGetCharacter(value,p);
      if(c=='.' && !point) {point=true;p++;continue;}
      if(c<'0' || c>'9') break;
      digits+=StringSubstr(value,p,1); if(point) fraction++; seen=true;p++;
     }
   if(!seen) return "#INVALID#";
   if(p<n && (StringSubstr(value,p,1)=="e" || StringSubstr(value,p,1)=="E"))
     {
      p++; int direction=1;
      if(StringSubstr(value,p,1)=="-" || StringSubstr(value,p,1)=="+")
        {if(StringSubstr(value,p,1)=="-") direction=-1;p++;}
      int start=p;
      while(p<n)
        {
         ushort c=StringGetCharacter(value,p);
         if(c<'0' || c>'9' || exponent>308) return "#INVALID#";
         exponent=exponent*10+(int)(c-'0');p++;
        }
      if(p==start || exponent>308) return "#INVALID#";
      exponent*=direction;
     }
   if(p!=n) return "#INVALID#";
   exponent-=fraction;
   while(StringLen(digits)>1 && StringSubstr(digits,0,1)=="0") digits=StringSubstr(digits,1);
   if(digits=="0") return "0e0";
   while(StringLen(digits)>1 && StringSubstr(digits,StringLen(digits)-1)=="0")
     {digits=StringSubstr(digits,0,StringLen(digits)-1);exponent++;}
   if(integer && exponent<0) return "#INVALID#";
   return (sign<0 ? "-" : "")+digits+"e"+(string)exponent;
  }

string GoatStudioCanonical(const string value,const string type)
  {
   if(type=="bool")
     {
      if(value=="true" || value=="1") return "true";
      if(value=="false" || value=="0") return "false";
      return "#INVALID#";
     }
   if(type=="double" || type=="int") return GoatStudioDecimal(value,type=="int");
   if(type=="datetime")
     {
      // Accept canonical MT5 calendar text or an unsigned integral epoch.
      if(StringFind(value,".")<0)
        {
         int size=StringLen(value);
         if(size==0 || size>12) return "#INVALID#";
         for(int i=0;i<size;i++)
           {ushort c=StringGetCharacter(value,i);if(c<'0' || c>'9') return "#INVALID#";}
         long stamp=StringToInteger(value);
         if(stamp>32535215999) return "#INVALID#";
         return (string)stamp;
        }
      datetime stamp=StringToTime(value);
      string rendered=TimeToString(stamp,TIME_DATE|TIME_SECONDS);
      int length=StringLen(value);
      if((length!=10 && length!=16 && length!=19) || StringSubstr(rendered,0,length)!=value) return "#INVALID#";
      // Date/minute-only forms must mean exactly midnight / zero seconds.
      if(length==10 && StringSubstr(rendered,10)!=" 00:00:00") return "#INVALID#";
      if(length==16 && StringSubstr(rendered,16)!=":00") return "#INVALID#";
      return (string)(long)stamp;
     }
   return "#INVALID#";
  }

bool GoatStudioSettingValueEqual(const string wanted,const string observed,const string type)
  {
   if(type=="string") return wanted==observed; // Literal || is never a tuple.
   string a=wanted,b=observed,left[],right[];
   StringReplace(a,"||","\n");StringReplace(b,"||","\n");
   int na=StringSplit(a,'\n',left),nb=StringSplit(b,'\n',right);
   if((na!=1 && na!=5) || (nb!=1 && nb!=5)) return false;
   bool active_a=na==5 && left[4]=="Y",active_b=nb==5 && right[4]=="Y";
   if((na==5 && left[4]!="Y" && left[4]!="N") || (nb==5 && right[4]!="Y" && right[4]!="N") || active_a!=active_b) return false;
   string first=GoatStudioCanonical(left[0],type),second=GoatStudioCanonical(right[0],type);
   if(first=="#INVALID#" || first!=second) return false;
   // Inactive tuple geometry does not participate in MT5 execution. Still
   // validate its syntax; never discard an active axis or its start/step/stop.
   for(int i=1;i<4;i++)
     {
      string range_type=type=="datetime" || type=="bool" ? "int" : type;
      string x=na==5 ? left[i] : "0",y=nb==5 ? right[i] : "0";
      if(type=="bool") {if(x=="false") x="0";if(x=="true") x="1";if(y=="false") y="0";if(y=="true") y="1";}
      x=GoatStudioCanonical(x,range_type);y=GoatStudioCanonical(y,range_type);
      if(x=="#INVALID#" || y=="#INVALID#" || (active_a && x!=y)) return false;
     }
   return true;
  }
#endif