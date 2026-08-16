#ifndef GOAT_AI_WIRE_V2_MQH
#define GOAT_AI_WIRE_V2_MQH

#define GOAT_AI_WIRE_V2_EXPECTED_ERA "sol-control-tower-rebuild-2026-07-v54"
#define GOAT_AI_WIRE_V2_EXPECTED_MANIFEST "2a2456b360c4d15d85ba7212f23e37e6890c4f5a7c7edcc816bfef73da06d628"
#ifndef GOAT_AI_WIRE_V2_RELEASE_ADMITTED_POINTER
#define GOAT_AI_WIRE_V2_RELEASE_ADMITTED_POINTER 0
#endif

// GOAT AI Control Tower wire-v2 client.
// The client is deliberately forward-only: selecting v2 never falls back to the
// legacy packed-score endpoint, cached neutral, or workstation/broker wall time.

enum ENUM_GOAT_AI_BIAS_PROTOCOL
  {
   BiasProtocol_LegacyRecorded = 0, // Explicit legacy live/history compatibility
   BiasProtocol_ControlTowerV2 = 1  // Strict /api/ea/bias/v2
  };

input group "==========GOAT AI CONTROL TOWER==========               ";
input ENUM_GOAT_AI_BIAS_PROTOCOL Bias_Protocol = BiasProtocol_ControlTowerV2; // Live bias protocol
input double Bias_V2_Win_Payoff_R = 1.00;                                     // Expected win payoff (R)
input double Bias_V2_Loss_Payoff_R = 1.00;                                    // Expected loss magnitude (R)
input double Bias_V2_Round_Trip_Cost_R = 0.02;                                // Spread/slippage/fees (R)
input double Bias_V2_Min_Expected_R = 0.00;                                   // Minimum expected edge (R)

enum ENUM_GOAT_JSON_TOKEN_TYPE
  {
   GOAT_JSON_OBJECT = 1,
   GOAT_JSON_ARRAY = 2,
   GOAT_JSON_STRING = 3,
   GOAT_JSON_NUMBER = 4,
   GOAT_JSON_TRUE = 5,
   GOAT_JSON_FALSE = 6,
   GOAT_JSON_NULL = 7
  };

struct SGOATJsonToken
  {
   int  type;
   int  start;
   int  end;
   int  parent;
   bool is_key;
  };

struct SGOATAIWireV2State
  {
   bool   verified;
   bool   directive_available;
   bool   actionable;
   int    signed_probability_percent;
   double calibrated_probability;
   double probability_cutoff;
   string availability;
   string direction;
   string reason_code;
   string published_at;
   string valid_until;
   string read_at;
   string era;
   string manifest_sha256;
   string release_attempt_id;
   string scan_id;
   string checksum;
   ulong  request_duration_ms;
  };

bool GOATJsonParseValue(const string json,int &pos,const int parent,const int depth,SGOATJsonToken &tokens[],int &token_index);

bool GOATIsJsonWhitespace(const ushort c)
  {
   return(c==32 || c==9 || c==10 || c==13);
  }

void GOATSkipJsonWhitespace(const string json,int &pos)
  {
   int total=StringLen(json);
   while(pos<total && GOATIsJsonWhitespace(StringGetCharacter(json,pos))) pos++;
  }

bool GOATIsHexCharacter(const ushort c)
  {
   return((c>='0' && c<='9') || (c>='a' && c<='f') || (c>='A' && c<='F'));
  }

bool GOATJsonAppendToken(SGOATJsonToken &tokens[],const int type,const int start,const int parent,const bool is_key,int &index)
  {
   int total=ArraySize(tokens);
   if(total>=2048) return false;
   if(ArrayResize(tokens,total+1)!=total+1) return false;
   tokens[total].type=type;
   tokens[total].start=start;
   tokens[total].end=-1;
   tokens[total].parent=parent;
   tokens[total].is_key=is_key;
   index=total;
   return true;
  }

bool GOATJsonParseStringToken(const string json,int &pos,const int parent,const bool is_key,SGOATJsonToken &tokens[],int &token_index)
  {
   int total=StringLen(json);
   int start=pos;
   if(pos>=total || StringGetCharacter(json,pos)!='"') return false;
   if(!GOATJsonAppendToken(tokens,GOAT_JSON_STRING,start,parent,is_key,token_index)) return false;
   pos++;
   while(pos<total)
     {
      ushort c=StringGetCharacter(json,pos);
      if(c=='"')
        {
         pos++;
         tokens[token_index].end=pos;
         return true;
        }
      if(c<32) return false;
      if(c=='\\')
        {
         pos++;
         if(pos>=total) return false;
         ushort escaped=StringGetCharacter(json,pos);
         if(escaped=='u')
           {
            if(pos+4>=total) return false;
            for(int i=1;i<=4;i++)
               if(!GOATIsHexCharacter(StringGetCharacter(json,pos+i))) return false;
            pos+=5;
            continue;
           }
         if(escaped!='"' && escaped!='\\' && escaped!='/' && escaped!='b'
            && escaped!='f' && escaped!='n' && escaped!='r' && escaped!='t') return false;
        }
      pos++;
     }
   return false;
  }

bool GOATJsonParseNumberToken(const string json,int &pos,const int parent,SGOATJsonToken &tokens[],int &token_index)
  {
   int total=StringLen(json);
   int start=pos;
   if(pos<total && StringGetCharacter(json,pos)=='-') pos++;
   if(pos>=total) return false;
   ushort c=StringGetCharacter(json,pos);
   if(c=='0') pos++;
   else
     {
      if(c<'1' || c>'9') return false;
      while(pos<total)
        {
         c=StringGetCharacter(json,pos);
         if(c<'0' || c>'9') break;
         pos++;
        }
     }
   if(pos<total && StringGetCharacter(json,pos)=='.')
     {
      pos++;
      int fraction_start=pos;
      while(pos<total)
        {
         c=StringGetCharacter(json,pos);
         if(c<'0' || c>'9') break;
         pos++;
        }
      if(pos==fraction_start) return false;
     }
   if(pos<total && (StringGetCharacter(json,pos)=='e' || StringGetCharacter(json,pos)=='E'))
     {
      pos++;
      if(pos<total && (StringGetCharacter(json,pos)=='+' || StringGetCharacter(json,pos)=='-')) pos++;
      int exponent_start=pos;
      while(pos<total)
        {
         c=StringGetCharacter(json,pos);
         if(c<'0' || c>'9') break;
         pos++;
        }
      if(pos==exponent_start) return false;
     }
   if(!GOATJsonAppendToken(tokens,GOAT_JSON_NUMBER,start,parent,false,token_index)) return false;
   tokens[token_index].end=pos;
   return true;
  }

bool GOATJsonParseLiteralToken(const string json,int &pos,const int parent,const string literal,const int type,SGOATJsonToken &tokens[],int &token_index)
  {
   int length=StringLen(literal);
   if(StringSubstr(json,pos,length)!=literal) return false;
   int start=pos;
   pos+=length;
   if(!GOATJsonAppendToken(tokens,type,start,parent,false,token_index)) return false;
   tokens[token_index].end=pos;
   return true;
  }

bool GOATJsonParseObjectToken(const string json,int &pos,const int parent,const int depth,SGOATJsonToken &tokens[],int &token_index)
  {
   int total=StringLen(json);
   int object_index=-1;
   if(!GOATJsonAppendToken(tokens,GOAT_JSON_OBJECT,pos,parent,false,object_index)) return false;
   token_index=object_index;
   pos++;
   GOATSkipJsonWhitespace(json,pos);
   if(pos<total && StringGetCharacter(json,pos)=='}')
     {
      pos++;
      tokens[object_index].end=pos;
      return true;
     }
   while(pos<total)
     {
      int key_index=-1;
      if(!GOATJsonParseStringToken(json,pos,object_index,true,tokens,key_index)) return false;
      GOATSkipJsonWhitespace(json,pos);
      if(pos>=total || StringGetCharacter(json,pos)!=':') return false;
      pos++;
      GOATSkipJsonWhitespace(json,pos);
      int value_index=-1;
      if(!GOATJsonParseValue(json,pos,object_index,depth+1,tokens,value_index)) return false;
      GOATSkipJsonWhitespace(json,pos);
      if(pos>=total) return false;
      ushort c=StringGetCharacter(json,pos);
      if(c=='}')
        {
         pos++;
         tokens[object_index].end=pos;
         return true;
        }
      if(c!=',') return false;
      pos++;
      GOATSkipJsonWhitespace(json,pos);
     }
   return false;
  }

bool GOATJsonParseArrayToken(const string json,int &pos,const int parent,const int depth,SGOATJsonToken &tokens[],int &token_index)
  {
   int total=StringLen(json);
   int array_index=-1;
   if(!GOATJsonAppendToken(tokens,GOAT_JSON_ARRAY,pos,parent,false,array_index)) return false;
   token_index=array_index;
   pos++;
   GOATSkipJsonWhitespace(json,pos);
   if(pos<total && StringGetCharacter(json,pos)==']')
     {
      pos++;
      tokens[array_index].end=pos;
      return true;
     }
   while(pos<total)
     {
      int value_index=-1;
      if(!GOATJsonParseValue(json,pos,array_index,depth+1,tokens,value_index)) return false;
      GOATSkipJsonWhitespace(json,pos);
      if(pos>=total) return false;
      ushort c=StringGetCharacter(json,pos);
      if(c==']')
        {
         pos++;
         tokens[array_index].end=pos;
         return true;
        }
      if(c!=',') return false;
      pos++;
      GOATSkipJsonWhitespace(json,pos);
     }
   return false;
  }

bool GOATJsonParseValue(const string json,int &pos,const int parent,const int depth,SGOATJsonToken &tokens[],int &token_index)
  {
   if(depth>32) return false;
   GOATSkipJsonWhitespace(json,pos);
   if(pos>=StringLen(json)) return false;
   ushort c=StringGetCharacter(json,pos);
   if(c=='{') return GOATJsonParseObjectToken(json,pos,parent,depth,tokens,token_index);
   if(c=='[') return GOATJsonParseArrayToken(json,pos,parent,depth,tokens,token_index);
   if(c=='"') return GOATJsonParseStringToken(json,pos,parent,false,tokens,token_index);
   if(c=='t') return GOATJsonParseLiteralToken(json,pos,parent,"true",GOAT_JSON_TRUE,tokens,token_index);
   if(c=='f') return GOATJsonParseLiteralToken(json,pos,parent,"false",GOAT_JSON_FALSE,tokens,token_index);
   if(c=='n') return GOATJsonParseLiteralToken(json,pos,parent,"null",GOAT_JSON_NULL,tokens,token_index);
   return GOATJsonParseNumberToken(json,pos,parent,tokens,token_index);
  }

bool GOATJsonParse(const string json,SGOATJsonToken &tokens[])
  {
   ArrayResize(tokens,0);
   int length=StringLen(json);
   if(length<2 || length>131072) return false;
   int pos=0;
   int root=-1;
   if(!GOATJsonParseValue(json,pos,-1,0,tokens,root) || root!=0) return false;
   GOATSkipJsonWhitespace(json,pos);
   return(pos==length && tokens[0].type==GOAT_JSON_OBJECT);
  }

bool GOATJsonStringValue(const string json,const SGOATJsonToken &token,string &value)
  {
   value="";
   if(token.type!=GOAT_JSON_STRING || token.end-token.start<2) return false;
   string raw=StringSubstr(json,token.start+1,token.end-token.start-2);
   int total=StringLen(raw);
   for(int i=0;i<total;i++)
     {
      ushort c=StringGetCharacter(raw,i);
      if(c!='\\')
        {
         value+=ShortToString(c);
         continue;
        }
      i++;
      if(i>=total) return false;
      ushort escaped=StringGetCharacter(raw,i);
      if(escaped=='"' || escaped=='\\' || escaped=='/') value+=ShortToString(escaped);
      else if(escaped=='b') value+=ShortToString(8);
      else if(escaped=='f') value+=ShortToString(12);
      else if(escaped=='n') value+=ShortToString(10);
      else if(escaped=='r') value+=ShortToString(13);
      else if(escaped=='t') value+=ShortToString(9);
      else return false; // Contract identifiers and field names are canonical ASCII.
     }
   return true;
  }

int GOATJsonFindField(const string json,SGOATJsonToken &tokens[],const int object_index,const string name)
  {
   if(object_index<0 || object_index>=ArraySize(tokens) || tokens[object_index].type!=GOAT_JSON_OBJECT) return -1;
   for(int i=object_index+1;i<ArraySize(tokens);i++)
     {
      if(tokens[i].parent!=object_index || !tokens[i].is_key) continue;
      string key="";
      if(!GOATJsonStringValue(json,tokens[i],key)) return -1;
      if(key==name && i+1<ArraySize(tokens) && tokens[i+1].parent==object_index && !tokens[i+1].is_key) return i+1;
     }
   return -1;
  }

bool GOATJsonExactFields(const string json,SGOATJsonToken &tokens[],const int object_index,string &expected[])
  {
   if(object_index<0 || object_index>=ArraySize(tokens) || tokens[object_index].type!=GOAT_JSON_OBJECT) return false;
   int found=0;
   for(int i=object_index+1;i<ArraySize(tokens);i++)
     {
      if(tokens[i].parent!=object_index || !tokens[i].is_key) continue;
      string key="";
      if(!GOATJsonStringValue(json,tokens[i],key)) return false;
      bool matched=false;
      for(int j=0;j<ArraySize(expected);j++)
        {
         if(expected[j]==key) {matched=true; break;}
        }
      if(!matched) return false;
      found++;
     }
   return(found==ArraySize(expected));
  }

bool GOATJsonCanonicalize(const string json,SGOATJsonToken &tokens[],const int token_index,string &output,const bool omit_checksum)
  {
   output="";
   if(token_index<0 || token_index>=ArraySize(tokens)) return false;
   SGOATJsonToken token=tokens[token_index];
   if(token.type!=GOAT_JSON_OBJECT && token.type!=GOAT_JSON_ARRAY)
     {
      output=StringSubstr(json,token.start,token.end-token.start);
      return true;
     }
   if(token.type==GOAT_JSON_ARRAY)
     {
      output="[";
      bool first=true;
      for(int i=token_index+1;i<ArraySize(tokens);i++)
        {
         if(tokens[i].parent!=token_index || tokens[i].is_key) continue;
         string nested="";
         if(!GOATJsonCanonicalize(json,tokens,i,nested,false)) return false;
         if(!first) output+=",";
         output+=nested;
         first=false;
        }
      output+="]";
      return true;
     }

   int key_indices[];
   string keys[];
   ArrayResize(key_indices,0);
   ArrayResize(keys,0);
   for(int i=token_index+1;i<ArraySize(tokens);i++)
     {
      if(tokens[i].parent!=token_index || !tokens[i].is_key) continue;
      string key="";
      if(!GOATJsonStringValue(json,tokens[i],key)) return false;
      if(omit_checksum && key=="checksum") continue;
      int n=ArraySize(keys);
      if(ArrayResize(keys,n+1)!=n+1 || ArrayResize(key_indices,n+1)!=n+1) return false;
      keys[n]=key;
      key_indices[n]=i;
     }
   for(int i=1;i<ArraySize(keys);i++)
     {
      string key=keys[i];
      int index=key_indices[i];
      int j=i-1;
      while(j>=0 && StringCompare(keys[j],key)>0)
        {
         keys[j+1]=keys[j];
         key_indices[j+1]=key_indices[j];
         j--;
        }
      keys[j+1]=key;
      key_indices[j+1]=index;
     }
   output="{";
   for(int i=0;i<ArraySize(keys);i++)
     {
      int key_index=key_indices[i];
      if(key_index+1>=ArraySize(tokens) || tokens[key_index+1].parent!=token_index) return false;
      string nested="";
      if(!GOATJsonCanonicalize(json,tokens,key_index+1,nested,false)) return false;
      if(i>0) output+=",";
      output+=StringSubstr(json,tokens[key_index].start,tokens[key_index].end-tokens[key_index].start)+":"+nested;
     }
   output+="}";
   return true;
  }

bool GOATSha256Utf8(const string value,string &hex)
  {
   hex="";
   uchar bytes[];
   uchar key[];
   uchar digest[];
   ArrayResize(key,0);
   int copied=StringToCharArray(value,bytes,0,WHOLE_ARRAY,CP_UTF8);
   if(copied<=0) return false;
   if(bytes[copied-1]==0) ArrayResize(bytes,copied-1);
   if(CryptEncode(CRYPT_HASH_SHA256,bytes,key,digest)!=32) return false;
   for(int i=0;i<ArraySize(digest);i++) hex+=StringFormat("%02x",(int)digest[i]);
   return(StringLen(hex)==64);
  }

bool GOATIsLowerHex(const string value,const int length)
  {
   if(StringLen(value)!=length) return false;
   for(int i=0;i<length;i++)
     {
      ushort c=StringGetCharacter(value,i);
      if(!((c>='0' && c<='9') || (c>='a' && c<='f'))) return false;
     }
   return true;
  }

bool GOATIsSafeId(const string value,const int minimum,const int maximum)
  {
   int total=StringLen(value);
   if(total<minimum || total>maximum) return false;
   for(int i=0;i<total;i++)
     {
      ushort c=StringGetCharacter(value,i);
       if(!((c>='A' && c<='Z') || (c>='a' && c<='z') || (c>='0' && c<='9') || c=='-' || c=='_' || c=='.' || c==':')) return false;
     }
   return true;
  }

bool GOATIsEraId(const string value)
  {
   int total=StringLen(value);
   if(total<1 || total>128) return false;
   ushort first=StringGetCharacter(value,0);
   if(!((first>='a' && first<='z') || (first>='0' && first<='9'))) return false;
   for(int i=1;i<total;i++)
     {
      ushort c=StringGetCharacter(value,i);
      if(!((c>='a' && c<='z') || (c>='0' && c<='9') || c=='.' || c=='_' || c==':' || c=='-')) return false;
     }
   return true;
  }

bool GOATWireV2AcceptsPointer(const string era,const string manifest)
  {
   if(GOAT_AI_WIRE_V2_RELEASE_ADMITTED_POINTER==1) return true;
   return(era==GOAT_AI_WIRE_V2_EXPECTED_ERA && manifest==GOAT_AI_WIRE_V2_EXPECTED_MANIFEST);
  }

bool GOATIsReasonCode(const string value)
  {
   int total=StringLen(value);
   if(total<3 || total>96) return false;
   for(int i=0;i<total;i++)
     {
      ushort c=StringGetCharacter(value,i);
      if(!((c>='A' && c<='Z') || (c>='0' && c<='9') || c=='_')) return false;
     }
   return true;
  }

bool GOATJsonGetString(const string json,SGOATJsonToken &tokens[],const int object_index,const string field,string &value)
  {
   int index=GOATJsonFindField(json,tokens,object_index,field);
   if(index<0) return false;
   return GOATJsonStringValue(json,tokens[index],value);
  }

bool GOATJsonGetNumber(const string json,SGOATJsonToken &tokens[],const int object_index,const string field,double &value)
  {
   int index=GOATJsonFindField(json,tokens,object_index,field);
   if(index<0 || tokens[index].type!=GOAT_JSON_NUMBER) return false;
   string raw=StringSubstr(json,tokens[index].start,tokens[index].end-tokens[index].start);
   value=StringToDouble(raw);
   return MathIsValidNumber(value);
  }

bool GOATJsonGetInteger(const string json,SGOATJsonToken &tokens[],const int object_index,const string field,long &value)
  {
   int index=GOATJsonFindField(json,tokens,object_index,field);
   if(index<0 || tokens[index].type!=GOAT_JSON_NUMBER) return false;
   string raw=StringSubstr(json,tokens[index].start,tokens[index].end-tokens[index].start);
   if(StringFind(raw,".")>=0 || StringFind(raw,"e")>=0 || StringFind(raw,"E")>=0) return false;
   value=StringToInteger(raw);
   return true;
  }

bool GOATJsonIsNull(const string json,SGOATJsonToken &tokens[],const int object_index,const string field)
  {
   int index=GOATJsonFindField(json,tokens,object_index,field);
   return(index>=0 && tokens[index].type==GOAT_JSON_NULL);
  }

bool GOATJsonGetBoolean(const string json,SGOATJsonToken &tokens[],const int object_index,const string field,bool &value)
  {
   int index=GOATJsonFindField(json,tokens,object_index,field);
   if(index<0 || (tokens[index].type!=GOAT_JSON_TRUE && tokens[index].type!=GOAT_JSON_FALSE)) return false;
   value=(tokens[index].type==GOAT_JSON_TRUE);
   return true;
  }

bool GOATIsLeapYear(const int year)
  {
   return((year%4==0 && year%100!=0) || year%400==0);
  }

long GOATDaysFromCivil(int year,const int month,const int day)
  {
   year-=(month<=2 ? 1 : 0);
   int era=(year>=0 ? year : year-399)/400;
   int yoe=year-era*400;
   int shifted_month=month+(month>2 ? -3 : 9);
   int doy=(153*shifted_month+2)/5+day-1;
   int doe=yoe*365+yoe/4-yoe/100+doy;
   return((long)era*146097+(long)doe-719468);
  }

bool GOATParseCanonicalIsoMs(const string value,long &epoch_ms)
  {
   epoch_ms=0;
   if(StringLen(value)!=24
      || StringSubstr(value,4,1)!="-"
      || StringSubstr(value,7,1)!="-"
      || StringSubstr(value,10,1)!="T"
      || StringSubstr(value,13,1)!=":"
      || StringSubstr(value,16,1)!=":"
      || StringSubstr(value,19,1)!="."
      || StringSubstr(value,23,1)!="Z") return false;
   int digit_positions[]={0,1,2,3,5,6,8,9,11,12,14,15,17,18,20,21,22};
   for(int i=0;i<ArraySize(digit_positions);i++)
     {
      ushort c=StringGetCharacter(value,digit_positions[i]);
      if(c<'0' || c>'9') return false;
     }
   int year=(int)StringToInteger(StringSubstr(value,0,4));
   int month=(int)StringToInteger(StringSubstr(value,5,2));
   int day=(int)StringToInteger(StringSubstr(value,8,2));
   int hour=(int)StringToInteger(StringSubstr(value,11,2));
   int minute=(int)StringToInteger(StringSubstr(value,14,2));
   int second=(int)StringToInteger(StringSubstr(value,17,2));
   int millisecond=(int)StringToInteger(StringSubstr(value,20,3));
   if(year<1970 || year>9999 || month<1 || month>12 || hour<0 || hour>23
      || minute<0 || minute>59 || second<0 || second>59) return false;
   int month_days[]={31,28,31,30,31,30,31,31,30,31,30,31};
   if(month==2 && GOATIsLeapYear(year)) month_days[1]=29;
   if(day<1 || day>month_days[month-1]) return false;
   epoch_ms=GOATDaysFromCivil(year,month,day)*86400000L
            +(long)hour*3600000L+(long)minute*60000L+(long)second*1000L+millisecond;
   return true;
  }

void GOATResetWireV2State(SGOATAIWireV2State &state,const string reason)
  {
   state.verified=false;
   state.directive_available=false;
   state.actionable=false;
   state.signed_probability_percent=0;
   state.calibrated_probability=0.0;
   state.probability_cutoff=0.0;
   state.availability="UNAVAILABLE";
   state.direction="";
   state.reason_code=reason;
   state.published_at="";
   state.valid_until="";
   state.read_at="";
   state.era="";
   state.manifest_sha256="";
   state.release_attempt_id="";
   state.scan_id="";
   state.checksum="";
   state.request_duration_ms=0;
  }

bool GOATAppendWireV2SetFile(const string file_name)
  {
   int handle=FileOpen(file_name,FILE_CSV|FILE_READ|FILE_WRITE|FILE_COMMON,"\t");
   if(handle==INVALID_HANDLE) return false;
   if(!FileSeek(handle,0,SEEK_END))
     {
      FileClose(handle);
      return false;
     }
   bool written=true;
   if(FileWrite(handle,"; ==========GOAT AI CONTROL TOWER==========")==0) written=false;
   if(FileWrite(handle,"Bias_Protocol="+(string)Bias_Protocol)==0) written=false;
   if(FileWrite(handle,"Bias_V2_Win_Payoff_R="+DoubleToString(Bias_V2_Win_Payoff_R,8))==0) written=false;
   if(FileWrite(handle,"Bias_V2_Loss_Payoff_R="+DoubleToString(Bias_V2_Loss_Payoff_R,8))==0) written=false;
   if(FileWrite(handle,"Bias_V2_Round_Trip_Cost_R="+DoubleToString(Bias_V2_Round_Trip_Cost_R,8))==0) written=false;
   if(FileWrite(handle,"Bias_V2_Min_Expected_R="+DoubleToString(Bias_V2_Min_Expected_R,8))==0) written=false;
   FileFlush(handle);
   FileClose(handle);
   return written;
  }

bool GOATWireV2AuthoritativeNow(const long read_at_ms,const ulong verified_tick,const ulong now_tick,long &authoritative_now)
  {
   authoritative_now=0;
   if(now_tick<verified_tick) return false;
   authoritative_now=read_at_ms+(long)(now_tick-verified_tick);
   return(authoritative_now>=read_at_ms);
  }

class CGOATAIWireV2
  {
   private:
   SGOATAIWireV2State m_state;
   ulong              m_last_attempt_tick;
   ulong              m_verified_tick;
   long               m_read_at_ms;
   long               m_valid_until_ms;

   bool ParseAndVerify(const string json,const string expected_asset,const ulong request_duration_ms,SGOATAIWireV2State &state);
   bool Refresh(const string asset);

   public:
   CGOATAIWireV2()
     {
      GOATResetWireV2State(m_state,"NOT_FETCHED");
      m_last_attempt_tick=0;
      m_verified_tick=0;
      m_read_at_ms=0;
      m_valid_until_ms=0;
     }

   void Reset()
     {
      GOATResetWireV2State(m_state,"NOT_FETCHED");
      m_last_attempt_tick=0;
      m_verified_tick=0;
      m_read_at_ms=0;
      m_valid_until_ms=0;
     }

   bool SelfTest()
     {
      string test_json="{\"v\":2,\"validUntil\":\"2026-07-15T10:05:00.000Z\","
                       +"\"score\":0.72,\"scanId\":\"decision-a\",\"direction\":\"BULLISH\","
                       +"\"checksum\":\"ignored\"}";
      string expected="{\"direction\":\"BULLISH\",\"scanId\":\"decision-a\",\"score\":0.72,"
                      +"\"v\":2,\"validUntil\":\"2026-07-15T10:05:00.000Z\"}";
      SGOATJsonToken tokens[];
      string canonical="";
      string digest="";
      if(!GOATJsonParse(test_json,tokens)
         || !GOATJsonCanonicalize(test_json,tokens,0,canonical,true)
         || canonical!=expected
         || !GOATSha256Utf8(canonical,digest)
         || digest!="417c13ca1081d63aa7c75add0345d9c1247a6d9771d871a9aa7e6287f9754b27") return false;
      string mql5_vector="{\"asset\":\"EURUSD\",\"context\":{\"beliefId\":\"belief-eurusd-a\","
                         +"\"era\":\"sol-control-tower-rebuild-2026-07-v50\",\"executionOverlay\":null,"
                         +"\"expressionHorizonMinutes\":65,\"manifestSha256\":\"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\","
                         +"\"noBackfill\":true,\"scanId\":\"scan-eurusd-a\",\"sourceDecisionId\":\"decision-eurusd-a\","
                         +"\"sourceDirection\":\"BULLISH\",\"sourceProbability\":0.72,\"stackAlignment\":null,"
                         +"\"thesisHorizonMinutes\":240,\"tradeLocation\":null,"
                         +"\"underwritingWakeCompletedAt\":\"2026-07-27T11:55:00.000Z\",\"version\":\"ea-wire-v2-context-v1\"},"
                         +"\"gating\":{\"availability\":\"WITHHELD\",\"calibratedProbability\":null,\"calibration\":null,"
                         +"\"direction\":null,\"probabilityMeaning\":\"PROBABILITY_SELECTED_DIRECTION_RESOLVES_OVER_THESIS_HORIZON\","
                         +"\"reasonCode\":\"CALIBRATION_ARTIFACT_UNAVAILABLE\",\"wakeRequired\":false},"
                         +"\"publishedAt\":\"2026-07-27T12:00:00.000Z\",\"v\":2,"
                         +"\"validUntil\":\"2026-07-27T13:05:00.000Z\",\"wireContract\":\"ea-wire-v2-calibrated-probability-v1\"}";
      if(!GOATSha256Utf8(mql5_vector,digest)
         || digest!="bb3296d130dbb9460ab9f7df60ae443a34a29c792b29952c0e0cd4dc97ac9eda") return false;

      long adversarial_now=0;
      if(!GOATWireV2AuthoritativeNow(1000000L,500,999,adversarial_now) || adversarial_now!=1000499L
         || !GOATWireV2AuthoritativeNow(1000000L,500,1499,adversarial_now) || adversarial_now!=1000999L
         || !GOATWireV2AuthoritativeNow(1000000L,500,1500,adversarial_now) || adversarial_now!=1001000L
         || GOATWireV2AuthoritativeNow(1000000L,500,499,adversarial_now)) return false;

      string response="{\"status\":\"success\",\"data\":{\"v\":2,"
                      +"\"wireContract\":\"ea-wire-v2-calibrated-probability-v1\",\"asset\":\"EURUSD\","
                      +"\"publishedAt\":\"2026-07-30T12:00:00.000Z\",\"validUntil\":\"2026-07-30T13:05:00.000Z\","
                      +"\"gating\":{\"availability\":\"WITHHELD\",\"direction\":null,\"calibratedProbability\":null,"
                      +"\"probabilityMeaning\":\"PROBABILITY_SELECTED_DIRECTION_RESOLVES_OVER_THESIS_HORIZON\","
                      +"\"calibration\":null,\"reasonCode\":\"CALIBRATION_ARTIFACT_UNAVAILABLE\",\"wakeRequired\":false},"
                      +"\"context\":{\"version\":\"ea-wire-v2-context-v1\",\"thesisHorizonMinutes\":240,"
                      +"\"expressionHorizonMinutes\":65,\"sourceDirection\":\"BULLISH\",\"sourceProbability\":0.72,"
                      +"\"sourceDecisionId\":\"decision-eurusd-v54\",\"scanId\":\"scan-eurusd-v54\","
                      +"\"beliefId\":\"belief-eurusd-v54\",\"underwritingWakeCompletedAt\":\"2026-07-30T11:55:00.000Z\","
                      +"\"era\":\"sol-control-tower-rebuild-2026-07-v54\","
                      +"\"manifestSha256\":\"2a2456b360c4d15d85ba7212f23e37e6890c4f5a7c7edcc816bfef73da06d628\","
                      +"\"tradeLocation\":null,\"executionOverlay\":null,\"stackAlignment\":null,\"noBackfill\":true},"
                      +"\"checksum\":\"8f7f04401edaa982d7ade41c8547ee92f9b6f0e7d82e57371ebc9d4116bed2e3\"},"
                      +"\"meta\":{\"routeVersion\":\"ea-wire-v2-route-v1\","
                      +"\"wireContract\":\"ea-wire-v2-calibrated-probability-v1\",\"asset\":\"EURUSD\",\"revision\":1,"
                      +"\"currentRecordHash\":\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\","
                      +"\"readAt\":\"2026-07-30T12:00:01.000Z\",\"era\":\"sol-control-tower-rebuild-2026-07-v54\","
                      +"\"manifestSha256\":\"2a2456b360c4d15d85ba7212f23e37e6890c4f5a7c7edcc816bfef73da06d628\","
                      +"\"releaseAttemptId\":\"release-v1-cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc\"}}";
      SGOATAIWireV2State parsed;
      return(ParseAndVerify(response,"EURUSD",10,parsed)
             && parsed.verified
             && !parsed.directive_available
              && parsed.reason_code=="CALIBRATION_ARTIFACT_UNAVAILABLE"
              && GOATIsEraId(parsed.era)
              && !GOATIsEraId("INVALID ERA")
              && GOATIsSafeId("decision-registry:EURUSD:sample",1,256)
              && !GOATIsSafeId("decision/registry",1,256)
              && parsed.checksum=="8f7f04401edaa982d7ade41c8547ee92f9b6f0e7d82e57371ebc9d4116bed2e3");
     }

   bool GetState(string asset,SGOATAIWireV2State &state)
     {
      asset=ConvertToGOATsymbol(asset);
      ulong now_tick=GetTickCount64();
      ulong refresh_ms=(ulong)MathMax(1,Bias_RegenerateMinutes)*60000;
      bool refresh=(m_last_attempt_tick==0 || now_tick<m_last_attempt_tick || now_tick-m_last_attempt_tick>=refresh_ms);
      if(m_state.verified)
        {
         if(now_tick<m_verified_tick) refresh=true;
         else
           {
            long authoritative_now=0;
            if(!GOATWireV2AuthoritativeNow(m_read_at_ms,m_verified_tick,now_tick,authoritative_now)
               || authoritative_now>=m_valid_until_ms) refresh=true;
           }
        }
      if(refresh) Refresh(asset);
      state=m_state;
      double payoff_cutoff=(Bias_V2_Loss_Payoff_R+Bias_V2_Round_Trip_Cost_R+Bias_V2_Min_Expected_R)
                           /(Bias_V2_Win_Payoff_R+Bias_V2_Loss_Payoff_R);
      double configured_cutoff=MathMax(0.0,MathMin(100.0,(double)Bias_threshold))/100.0;
      state.probability_cutoff=MathMax(payoff_cutoff,configured_cutoff);
      state.actionable=(state.verified
                        && state.directive_available
                        && (state.direction=="BULLISH" || state.direction=="BEARISH")
                        && state.calibrated_probability>=state.probability_cutoff);
      if(state.directive_available)
        {
         int probability_percent=(int)MathRound(state.calibrated_probability*100.0);
         if(state.direction=="BULLISH") state.signed_probability_percent=probability_percent;
         else if(state.direction=="BEARISH") state.signed_probability_percent=-probability_percent;
         else state.signed_probability_percent=0;
        }
      m_state.probability_cutoff=state.probability_cutoff;
      m_state.actionable=state.actionable;
      m_state.signed_probability_percent=state.signed_probability_percent;
      return state.verified;
     }

   string DisplayLine(SGOATAIWireV2State &state)
     {
      if(!state.verified) return "Control Tower unavailable: "+state.reason_code;
      if(!state.directive_available) return "Control Tower WITHHELD: "+state.reason_code;
      return "Control Tower "+state.direction+" "
             +DoubleToString(state.calibrated_probability*100.0,1)+"% (cutoff "
             +DoubleToString(state.probability_cutoff*100.0,1)+"%)";
     }
  };

bool CGOATAIWireV2::Refresh(const string asset)
  {
   GOATResetWireV2State(m_state,"REQUEST_FAILED");
   m_read_at_ms=0;
   m_valid_until_ms=0;
   m_verified_tick=0;
   ulong started=GetTickCount64();
   m_last_attempt_tick=started;
   if(MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD))
     {
      m_state.reason_code="LIVE_WIRE_UNAVAILABLE_IN_TESTER";
      return false;
     }

   string url=URL_API+"/api/ea/bias/v2?asset="+asset+"&id="+(string)AccountInfoInteger(ACCOUNT_LOGIN);
   char request_body[];
   char result[];
   ArrayResize(request_body,0);
   string result_headers="";
   string api_headers="";
   if(!GOATBuildAuthenticatedRequestHeaders(api_headers))
     {
      m_state.reason_code="AUTH_TOKEN_UNAVAILABLE";
      Print("GOAT AI wire v2 unavailable: AUTH_TOKEN_UNAVAILABLE.");
      return false;
     }
   ResetLastError();
   int response=WebRequest("GET",url,api_headers,timeout*3,request_body,result,result_headers);
   ulong finished=GetTickCount64();
   m_last_attempt_tick=finished;
   ulong duration=(finished>=started ? finished-started : 0);
   m_state.request_duration_ms=duration;
   if(response==-1)
     {
      m_state.reason_code="WEBREQUEST_FAILED";
      PrintFormat("GOAT AI wire v2 unavailable: WEBREQUEST_FAILED (%d).",GetLastError());
      return false;
     }
   if(response!=200)
     {
      m_state.reason_code="HTTP_NON_200";
      PrintFormat("GOAT AI wire v2 unavailable: HTTP_NON_200 (%d).",response);
      return false;
     }
   string json=CharArrayToString(result,0,-1,CP_UTF8);
   SGOATAIWireV2State parsed;
   if(!ParseAndVerify(json,asset,duration,parsed))
     {
      m_state.reason_code="RESPONSE_INVALID";
      Print("GOAT AI wire v2 unavailable: RESPONSE_INVALID.");
      return false;
     }
   m_state=parsed;
   m_verified_tick=started;
   if(!GOATParseCanonicalIsoMs(m_state.read_at,m_read_at_ms)
      || !GOATParseCanonicalIsoMs(m_state.valid_until,m_valid_until_ms))
     {
      GOATResetWireV2State(m_state,"RESPONSE_TIME_INVALID");
      return false;
     }
   PrintFormat("GOAT AI wire v2 verified: availability=%s reason=%s era=%s manifest=%s duration_ms=%I64u.",
               m_state.availability,
               (m_state.reason_code=="" ? "NONE" : m_state.reason_code),
               m_state.era,
               m_state.manifest_sha256,
               m_state.request_duration_ms);
   return true;
  }

bool CGOATAIWireV2::ParseAndVerify(const string json,const string expected_asset,const ulong request_duration_ms,SGOATAIWireV2State &state)
  {
   GOATResetWireV2State(state,"RESPONSE_INVALID");
   SGOATJsonToken tokens[];
   if(!GOATJsonParse(json,tokens)) return false;

   string root_fields[]={"status","data","meta"};
   if(!GOATJsonExactFields(json,tokens,0,root_fields)) return false;
   string status="";
   if(!GOATJsonGetString(json,tokens,0,"status",status) || status!="success") return false;
   int data_index=GOATJsonFindField(json,tokens,0,"data");
   int meta_index=GOATJsonFindField(json,tokens,0,"meta");
   if(data_index<0 || meta_index<0 || tokens[data_index].type!=GOAT_JSON_OBJECT || tokens[meta_index].type!=GOAT_JSON_OBJECT) return false;

   string wire_fields[]={"v","wireContract","asset","publishedAt","validUntil","gating","context","checksum"};
   string gating_fields[]={"availability","direction","calibratedProbability","probabilityMeaning","calibration","reasonCode","wakeRequired"};
   string context_fields[]={"version","thesisHorizonMinutes","expressionHorizonMinutes","sourceDirection","sourceProbability","sourceDecisionId","scanId","beliefId","underwritingWakeCompletedAt","era","manifestSha256","tradeLocation","executionOverlay","stackAlignment","noBackfill"};
   string meta_fields[]={"routeVersion","wireContract","asset","revision","currentRecordHash","readAt","era","manifestSha256","releaseAttemptId"};
   if(!GOATJsonExactFields(json,tokens,data_index,wire_fields)
      || !GOATJsonExactFields(json,tokens,meta_index,meta_fields)) return false;
   int gating_index=GOATJsonFindField(json,tokens,data_index,"gating");
   int context_index=GOATJsonFindField(json,tokens,data_index,"context");
   if(gating_index<0 || context_index<0
      || !GOATJsonExactFields(json,tokens,gating_index,gating_fields)
      || !GOATJsonExactFields(json,tokens,context_index,context_fields)) return false;

   long version=0,revision=0,thesis_minutes=0,expression_minutes=0;
   string wire_contract="",asset="",published_at="",valid_until="",checksum="";
   string availability="",direction="",probability_meaning="",reason_code="";
   string context_version="",source_direction="",source_decision_id="",scan_id="",belief_id="",wake_completed_at="",era="",manifest="";
   string route_version="",meta_wire_contract="",meta_asset="",record_hash="",read_at="",meta_era="",meta_manifest="",release_attempt="";
   double calibrated_probability=0.0,source_probability=0.0;
   bool wake_required=false,no_backfill=false;
   if(!GOATJsonGetInteger(json,tokens,data_index,"v",version) || version!=2
      || !GOATJsonGetString(json,tokens,data_index,"wireContract",wire_contract)
      || wire_contract!="ea-wire-v2-calibrated-probability-v1"
      || !GOATJsonGetString(json,tokens,data_index,"asset",asset) || asset!=expected_asset
      || !GOATJsonGetString(json,tokens,data_index,"publishedAt",published_at)
      || !GOATJsonGetString(json,tokens,data_index,"validUntil",valid_until)
      || !GOATJsonGetString(json,tokens,data_index,"checksum",checksum) || !GOATIsLowerHex(checksum,64)
      || !GOATJsonGetString(json,tokens,gating_index,"availability",availability)
      || !GOATJsonGetString(json,tokens,gating_index,"probabilityMeaning",probability_meaning)
      || probability_meaning!="PROBABILITY_SELECTED_DIRECTION_RESOLVES_OVER_THESIS_HORIZON"
      || !GOATJsonGetBoolean(json,tokens,gating_index,"wakeRequired",wake_required)
      || !GOATJsonGetString(json,tokens,context_index,"version",context_version)
      || context_version!="ea-wire-v2-context-v1"
      || !GOATJsonGetInteger(json,tokens,context_index,"thesisHorizonMinutes",thesis_minutes) || thesis_minutes!=240
      || !GOATJsonGetInteger(json,tokens,context_index,"expressionHorizonMinutes",expression_minutes) || expression_minutes!=65
      || !GOATJsonGetString(json,tokens,context_index,"sourceDirection",source_direction)
      || !GOATJsonGetNumber(json,tokens,context_index,"sourceProbability",source_probability)
      || source_probability<0.0 || source_probability>1.0
      || !GOATJsonGetString(json,tokens,context_index,"sourceDecisionId",source_decision_id) || !GOATIsSafeId(source_decision_id,1,256)
      || !GOATJsonGetString(json,tokens,context_index,"scanId",scan_id) || !GOATIsSafeId(scan_id,1,256)
      || !GOATJsonGetString(json,tokens,context_index,"beliefId",belief_id) || !GOATIsSafeId(belief_id,1,256)
      || !GOATJsonGetString(json,tokens,context_index,"underwritingWakeCompletedAt",wake_completed_at)
      || !GOATJsonGetString(json,tokens,context_index,"era",era) || !GOATIsEraId(era)
      || !GOATJsonGetString(json,tokens,context_index,"manifestSha256",manifest)
      || !GOATIsLowerHex(manifest,64)
      || !GOATWireV2AcceptsPointer(era,manifest)
      || !GOATJsonGetBoolean(json,tokens,context_index,"noBackfill",no_backfill) || !no_backfill
      || !GOATJsonGetString(json,tokens,meta_index,"routeVersion",route_version) || route_version!="ea-wire-v2-route-v1"
      || !GOATJsonGetString(json,tokens,meta_index,"wireContract",meta_wire_contract) || meta_wire_contract!=wire_contract
      || !GOATJsonGetString(json,tokens,meta_index,"asset",meta_asset) || meta_asset!=asset
      || !GOATJsonGetInteger(json,tokens,meta_index,"revision",revision) || revision<1
      || !GOATJsonGetString(json,tokens,meta_index,"currentRecordHash",record_hash) || !GOATIsLowerHex(record_hash,64)
      || !GOATJsonGetString(json,tokens,meta_index,"readAt",read_at)
      || !GOATJsonGetString(json,tokens,meta_index,"era",meta_era) || meta_era!=era
      || !GOATJsonGetString(json,tokens,meta_index,"manifestSha256",meta_manifest) || meta_manifest!=manifest
      || !GOATJsonGetString(json,tokens,meta_index,"releaseAttemptId",release_attempt)
      || StringSubstr(release_attempt,0,11)!="release-v1-" || !GOATIsLowerHex(StringSubstr(release_attempt,11),64)) return false;
   if(source_direction!="BULLISH" && source_direction!="NEUTRAL" && source_direction!="BEARISH") return false;

   int trade_location_index=GOATJsonFindField(json,tokens,context_index,"tradeLocation");
   int execution_overlay_index=GOATJsonFindField(json,tokens,context_index,"executionOverlay");
   int stack_alignment_index=GOATJsonFindField(json,tokens,context_index,"stackAlignment");
   if(trade_location_index<0 || execution_overlay_index<0 || stack_alignment_index<0) return false;
   if(!((tokens[trade_location_index].type==GOAT_JSON_OBJECT) || (tokens[trade_location_index].type==GOAT_JSON_NULL))
      || !((tokens[execution_overlay_index].type==GOAT_JSON_OBJECT) || (tokens[execution_overlay_index].type==GOAT_JSON_NULL))
      || !((tokens[stack_alignment_index].type==GOAT_JSON_OBJECT) || (tokens[stack_alignment_index].type==GOAT_JSON_NULL))) return false;

   if(availability=="AVAILABLE")
     {
      string calibration_fields[]={"artifactId","artifactHash","fitEra","forwardTestEra","applicableEra","method","fitSampleSize","forwardTestSampleSize","minimumDirectionSampleSize"};
      long fit_sample=0,forward_sample=0,direction_sample=0;
      string artifact_id="",artifact_hash="",fit_era="",forward_era="",applicable_era="",method="";
      int calibration_index=GOATJsonFindField(json,tokens,gating_index,"calibration");
      if(!GOATJsonGetString(json,tokens,gating_index,"direction",direction)
         || direction!=source_direction
         || (direction!="BULLISH" && direction!="NEUTRAL" && direction!="BEARISH")
         || !GOATJsonGetNumber(json,tokens,gating_index,"calibratedProbability",calibrated_probability)
         || calibrated_probability<0.0 || calibrated_probability>1.0
         || !GOATJsonIsNull(json,tokens,gating_index,"reasonCode")
         || calibration_index<0 || !GOATJsonExactFields(json,tokens,calibration_index,calibration_fields)
         || !GOATJsonGetString(json,tokens,calibration_index,"artifactId",artifact_id) || !GOATIsSafeId(artifact_id,1,256)
         || !GOATJsonGetString(json,tokens,calibration_index,"artifactHash",artifact_hash) || !GOATIsLowerHex(artifact_hash,64)
         || !GOATJsonGetString(json,tokens,calibration_index,"fitEra",fit_era) || fit_era==era
         || !GOATJsonGetString(json,tokens,calibration_index,"forwardTestEra",forward_era) || forward_era!=era
         || !GOATJsonGetString(json,tokens,calibration_index,"applicableEra",applicable_era) || applicable_era!=era
         || !GOATJsonGetString(json,tokens,calibration_index,"method",method) || method!="ISOTONIC_PAVA_V1"
         || !GOATJsonGetInteger(json,tokens,calibration_index,"fitSampleSize",fit_sample) || fit_sample<100
         || !GOATJsonGetInteger(json,tokens,calibration_index,"forwardTestSampleSize",forward_sample) || forward_sample<100
         || !GOATJsonGetInteger(json,tokens,calibration_index,"minimumDirectionSampleSize",direction_sample) || direction_sample<20) return false;
      reason_code="";
     }
   else if(availability=="WITHHELD")
     {
      if(!GOATJsonIsNull(json,tokens,gating_index,"direction")
         || !GOATJsonIsNull(json,tokens,gating_index,"calibratedProbability")
         || !GOATJsonIsNull(json,tokens,gating_index,"calibration")
         || !GOATJsonGetString(json,tokens,gating_index,"reasonCode",reason_code)
         || !GOATIsReasonCode(reason_code)) return false;
      direction="";
      calibrated_probability=0.0;
     }
   else return false;

   long published_ms=0,valid_until_ms=0,read_at_ms=0,wake_completed_ms=0;
   if(!GOATParseCanonicalIsoMs(published_at,published_ms)
      || !GOATParseCanonicalIsoMs(valid_until,valid_until_ms)
      || !GOATParseCanonicalIsoMs(read_at,read_at_ms)
      || !GOATParseCanonicalIsoMs(wake_completed_at,wake_completed_ms)
      || valid_until_ms-published_ms!=3900000L
      || wake_completed_ms>published_ms
      || published_ms>read_at_ms
      || read_at_ms+(long)request_duration_ms>=valid_until_ms) return false;

   string canonical="";
   string calculated_checksum="";
   if(!GOATJsonCanonicalize(json,tokens,data_index,canonical,true)
      || !GOATSha256Utf8(canonical,calculated_checksum)
      || calculated_checksum!=checksum) return false;

   state.verified=true;
   state.directive_available=(availability=="AVAILABLE");
   state.actionable=false;
   state.signed_probability_percent=0;
   state.calibrated_probability=calibrated_probability;
   state.probability_cutoff=0.0;
   state.availability=availability;
   state.direction=direction;
   state.reason_code=(availability=="WITHHELD" ? reason_code : "");
   state.published_at=published_at;
   state.valid_until=valid_until;
   state.read_at=read_at;
   state.era=era;
   state.manifest_sha256=manifest;
   state.release_attempt_id=release_attempt;
   state.scan_id=scan_id;
   state.checksum=checksum;
   state.request_duration_ms=request_duration_ms;
   return true;
  }

CGOATAIWireV2 GOATBiasWireV2;

#endif
