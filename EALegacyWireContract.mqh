#ifndef GOAT_EA_LEGACY_WIRE_CONTRACT_MQH
#define GOAT_EA_LEGACY_WIRE_CONTRACT_MQH

#define EA_LEGACY_VALIDITY_MS 3900000
#define EA_LEGACY_JSON_MAX_DEPTH 32

struct SEALegacyBiasRow
  {
   string asset;
   long   scan_timestamp_ms;
   long   valid_until_ms;
   double score;
  };

struct SEALegacyBiasResponse
  {
   bool             available;
   string           reason;
   long             server_time_ms;
   long             authoritative_now_ms;
   SEALegacyBiasRow rows[];
  };

void EAResetLegacyBiasResponse(SEALegacyBiasResponse &response)
  {
   response.available=false;
   response.reason="UNINITIALIZED";
   response.server_time_ms=0;
   response.authoritative_now_ms=0;
   ArrayResize(response.rows,0);
  }

bool EAIsJsonWhitespace(const ushort ch)
  {
   return ch==0x20 || ch==0x09 || ch==0x0A || ch==0x0D;
  }

int EAHexDigit(const ushort ch)
  {
   if(ch>='0' && ch<='9') return (int)(ch-'0');
   if(ch>='a' && ch<='f') return 10+(int)(ch-'a');
   if(ch>='A' && ch<='F') return 10+(int)(ch-'A');
   return -1;
  }

bool EAParseFixedDigits(const string value,const int offset,const int count,int &number)
  {
   if(offset<0 || count<=0 || offset+count>StringLen(value)) return false;
   number=0;
   for(int i=0;i<count;i++)
     {
      ushort ch=StringGetCharacter(value,offset+i);
      if(ch<'0' || ch>'9') return false;
      number=number*10+(int)(ch-'0');
     }
   return true;
  }

bool EAParseCanonicalUtcMs(const string value,const bool require_milliseconds,long &milliseconds)
  {
   milliseconds=0;
   int length=StringLen(value);
   bool has_fraction=(length>=22 && length<=24);
   if(require_milliseconds)
     {
      if(length!=24) return false;
     }
   else if(length!=20 && !has_fraction) return false;

   if(StringGetCharacter(value,4)!='-' ||
      StringGetCharacter(value,7)!='-' ||
      StringGetCharacter(value,10)!='T' ||
      StringGetCharacter(value,13)!=':' ||
      StringGetCharacter(value,16)!=':' ||
      StringGetCharacter(value,length-1)!='Z') return false;
   if(has_fraction && StringGetCharacter(value,19)!='.') return false;

   int year,month,day,hour,minute,second;
   if(!EAParseFixedDigits(value,0,4,year) ||
      !EAParseFixedDigits(value,5,2,month) ||
      !EAParseFixedDigits(value,8,2,day) ||
      !EAParseFixedDigits(value,11,2,hour) ||
      !EAParseFixedDigits(value,14,2,minute) ||
      !EAParseFixedDigits(value,17,2,second)) return false;
   if(year<1970 || year>3000 ||
      month<1 || month>12 ||
      day<1 || day>31 ||
      hour<0 || hour>23 ||
      minute<0 || minute>59 ||
      second<0 || second>59) return false;

   int fraction_ms=0;
   if(has_fraction)
     {
      int fraction_digits=length-21;
      int fraction_value=0;
      if(!EAParseFixedDigits(value,20,fraction_digits,fraction_value)) return false;
      if(fraction_digits==1) fraction_ms=fraction_value*100;
      else if(fraction_digits==2) fraction_ms=fraction_value*10;
      else fraction_ms=fraction_value;
     }

   MqlDateTime parts;
   ZeroMemory(parts);
   parts.year=year;
   parts.mon=month;
   parts.day=day;
   parts.hour=hour;
   parts.min=minute;
   parts.sec=second;
   datetime seconds_since_epoch=StructToTime(parts);
   if(seconds_since_epoch<=0) return false;

   MqlDateTime round_trip;
   ZeroMemory(round_trip);
   if(!TimeToStruct(seconds_since_epoch,round_trip)) return false;
   if(round_trip.year!=year ||
      round_trip.mon!=month ||
      round_trip.day!=day ||
      round_trip.hour!=hour ||
      round_trip.min!=minute ||
      round_trip.sec!=second) return false;

   milliseconds=((long)seconds_since_epoch)*1000+(long)fraction_ms;
   return milliseconds>0;
  }

bool EAParsePackedBias(const string packed,double &score,long &valid_until_ms)
  {
   score=0.0;
   valid_until_ms=0;
   int separator=StringFind(packed," ");
   if(separator<=0 || StringFind(packed," ",separator+1)>=0) return false;

   string score_text=StringSubstr(packed,0,separator);
   string valid_until=StringSubstr(packed,separator+1);
   int length=StringLen(score_text);
   int cursor=0;
   if(length>0 && StringGetCharacter(score_text,0)=='-') cursor=1;
   int integer_start=cursor;
   while(cursor<length)
     {
      ushort ch=StringGetCharacter(score_text,cursor);
      if(ch<'0' || ch>'9') break;
      cursor++;
     }
   int integer_digits=cursor-integer_start;
   if(integer_digits<1 || integer_digits>3) return false;
   if(integer_digits>1 && StringGetCharacter(score_text,integer_start)=='0') return false;
   if(cursor>=length || StringGetCharacter(score_text,cursor)!='.') return false;
   cursor++;
   if(length-cursor!=4) return false;
   for(int i=cursor;i<length;i++)
     {
      ushort digit=StringGetCharacter(score_text,i);
      if(digit<'0' || digit>'9') return false;
     }

   score=StringToDouble(score_text);
   if(!MathIsValidNumber(score) || score<-100.0 || score>100.0) return false;
   if(score==0.0) score=0.0;
   return EAParseCanonicalUtcMs(valid_until,true,valid_until_ms);
  }

class CEALegacyJsonParser
  {
private:
   string m_json;
   int    m_pos;
   int    m_length;
   string m_error;

   void SkipWhitespace()
     {
      while(m_pos<m_length && EAIsJsonWhitespace(StringGetCharacter(m_json,m_pos))) m_pos++;
     }

   bool Fail(const string reason)
     {
      if(m_error=="") m_error=reason;
      return false;
     }

   bool Consume(const ushort expected)
     {
      SkipWhitespace();
      if(m_pos>=m_length || StringGetCharacter(m_json,m_pos)!=expected) return false;
      m_pos++;
      return true;
     }

   bool ParseString(string &value)
     {
      value="";
      SkipWhitespace();
      if(m_pos>=m_length || StringGetCharacter(m_json,m_pos)!='"') return false;
      m_pos++;
      while(m_pos<m_length)
        {
         ushort ch=StringGetCharacter(m_json,m_pos++);
         if(ch=='"') return true;
         if(ch<0x20) return false;
         if(ch!='\\')
           {
            value+=ShortToString(ch);
            continue;
           }

         if(m_pos>=m_length) return false;
         ushort escaped=StringGetCharacter(m_json,m_pos++);
         if(escaped=='"' || escaped=='\\' || escaped=='/')
           {
            value+=ShortToString(escaped);
            continue;
           }
         if(escaped=='b') { value+=ShortToString(0x08); continue; }
         if(escaped=='f') { value+=ShortToString(0x0C); continue; }
         if(escaped=='n') { value+=ShortToString(0x0A); continue; }
         if(escaped=='r') { value+=ShortToString(0x0D); continue; }
         if(escaped=='t') { value+=ShortToString(0x09); continue; }
         if(escaped!='u' || m_pos+4>m_length) return false;

         int code=0;
         for(int i=0;i<4;i++)
           {
            int hex=EAHexDigit(StringGetCharacter(m_json,m_pos+i));
            if(hex<0) return false;
            code=code*16+hex;
           }
         m_pos+=4;
         if(code>=0xD800 && code<=0xDBFF)
           {
            if(m_pos+6>m_length ||
               StringGetCharacter(m_json,m_pos)!='\\' ||
               StringGetCharacter(m_json,m_pos+1)!='u') return false;
            int low=0;
            for(int j=0;j<4;j++)
              {
               int low_hex=EAHexDigit(StringGetCharacter(m_json,m_pos+2+j));
               if(low_hex<0) return false;
               low=low*16+low_hex;
              }
            if(low<0xDC00 || low>0xDFFF) return false;
            value+=ShortToString((ushort)code);
            value+=ShortToString((ushort)low);
            m_pos+=6;
            continue;
           }
         if(code>=0xDC00 && code<=0xDFFF) return false;
         value+=ShortToString((ushort)code);
        }
      return false;
     }

   bool SkipNumber()
     {
      SkipWhitespace();
      int start=m_pos;
      if(m_pos<m_length && StringGetCharacter(m_json,m_pos)=='-') m_pos++;
      if(m_pos>=m_length) { m_pos=start; return false; }

      ushort first=StringGetCharacter(m_json,m_pos);
      if(first=='0') m_pos++;
      else if(first>='1' && first<='9')
        {
         m_pos++;
         while(m_pos<m_length)
           {
            ushort digit=StringGetCharacter(m_json,m_pos);
            if(digit<'0' || digit>'9') break;
            m_pos++;
           }
        }
      else { m_pos=start; return false; }

      if(m_pos<m_length && StringGetCharacter(m_json,m_pos)=='.')
        {
         m_pos++;
         int fraction_start=m_pos;
         while(m_pos<m_length)
           {
            ushort digit=StringGetCharacter(m_json,m_pos);
            if(digit<'0' || digit>'9') break;
            m_pos++;
           }
         if(m_pos==fraction_start) { m_pos=start; return false; }
        }

      if(m_pos<m_length)
        {
         ushort exponent=StringGetCharacter(m_json,m_pos);
         if(exponent=='e' || exponent=='E')
           {
            m_pos++;
            if(m_pos<m_length)
              {
               ushort sign=StringGetCharacter(m_json,m_pos);
               if(sign=='+' || sign=='-') m_pos++;
              }
            int exponent_start=m_pos;
            while(m_pos<m_length)
              {
               ushort digit=StringGetCharacter(m_json,m_pos);
               if(digit<'0' || digit>'9') break;
               m_pos++;
              }
            if(m_pos==exponent_start) { m_pos=start; return false; }
           }
        }
      return true;
     }

   bool SkipLiteral(const string literal)
     {
      SkipWhitespace();
      int length=StringLen(literal);
      if(m_pos+length>m_length || StringSubstr(m_json,m_pos,length)!=literal) return false;
      m_pos+=length;
      return true;
     }

   bool SkipObject(const int depth)
     {
      if(!Consume('{')) return false;
      SkipWhitespace();
      if(Consume('}')) return true;
      while(true)
        {
         string key;
         if(!ParseString(key) || !Consume(':') || !SkipValue(depth+1)) return false;
         SkipWhitespace();
         if(Consume('}')) return true;
         if(!Consume(',')) return false;
        }
     }

   bool SkipArray(const int depth)
     {
      if(!Consume('[')) return false;
      SkipWhitespace();
      if(Consume(']')) return true;
      while(true)
        {
         if(!SkipValue(depth+1)) return false;
         SkipWhitespace();
         if(Consume(']')) return true;
         if(!Consume(',')) return false;
        }
     }

   bool SkipValue(const int depth)
     {
      if(depth>EA_LEGACY_JSON_MAX_DEPTH) return false;
      SkipWhitespace();
      if(m_pos>=m_length) return false;
      ushort ch=StringGetCharacter(m_json,m_pos);
      if(ch=='"')
        {
         string ignored;
         return ParseString(ignored);
        }
      if(ch=='{') return SkipObject(depth);
      if(ch=='[') return SkipArray(depth);
      if(ch=='t') return SkipLiteral("true");
      if(ch=='f') return SkipLiteral("false");
      if(ch=='n') return SkipLiteral("null");
      return SkipNumber();
     }

   bool ParseRow(SEALegacyBiasRow &row)
     {
      row.asset="";
      row.scan_timestamp_ms=0;
      row.valid_until_ms=0;
      row.score=0.0;
      bool asset_seen=false;
      bool timestamp_seen=false;
      bool sentiment_seen=false;

      if(!Consume('{')) return Fail("ROW_INVALID");
      SkipWhitespace();
      if(Consume('}')) return Fail("ROW_INVALID");
      while(true)
        {
         string key;
         if(!ParseString(key) || !Consume(':')) return Fail("ROW_INVALID");
         if(key=="asset")
           {
            if(asset_seen || !ParseString(row.asset)) return Fail("ROW_ASSET_INVALID");
            asset_seen=true;
           }
         else if(key=="timestamp")
           {
            string timestamp;
            if(timestamp_seen || !ParseString(timestamp) ||
               !EAParseCanonicalUtcMs(timestamp,false,row.scan_timestamp_ms))
               return Fail("ROW_TIMESTAMP_INVALID");
            timestamp_seen=true;
           }
         else if(key=="sentiment")
           {
            string packed;
            if(sentiment_seen || !ParseString(packed) ||
               !EAParsePackedBias(packed,row.score,row.valid_until_ms))
               return Fail("ROW_SENTIMENT_INVALID");
            sentiment_seen=true;
           }
         else if(!SkipValue(1)) return Fail("ROW_INVALID");

         SkipWhitespace();
         if(Consume('}')) break;
         if(!Consume(',')) return Fail("ROW_INVALID");
        }
      if(!asset_seen || !timestamp_seen || !sentiment_seen) return Fail("ROW_REQUIRED_FIELD_MISSING");
      return true;
     }

   bool ParseRows(SEALegacyBiasRow &rows[])
     {
      ArrayResize(rows,0);
      if(!Consume('[')) return Fail("DATA_NOT_ARRAY");
      SkipWhitespace();
      if(Consume(']')) return true;
      while(true)
        {
         int size=ArraySize(rows);
         ArrayResize(rows,size+1);
         if(!ParseRow(rows[size])) return false;
         SkipWhitespace();
         if(Consume(']')) return true;
         if(!Consume(',')) return Fail("DATA_INVALID");
        }
     }

public:
   void Init(const string json)
     {
      m_json=json;
      m_pos=0;
      m_length=StringLen(json);
      m_error="";
     }

   string Error() const
     {
      return m_error=="" ? "BODY_JSON_INVALID" : m_error;
     }

   bool ParseEnvelope(string &status,string &server_time,SEALegacyBiasRow &rows[])
     {
      status="";
      server_time="";
      ArrayResize(rows,0);
      bool status_seen=false;
      bool server_time_seen=false;
      bool data_seen=false;

      if(!Consume('{')) return Fail("ENVELOPE_INVALID");
      SkipWhitespace();
      if(Consume('}')) return Fail("ENVELOPE_INVALID");
      while(true)
        {
         string key;
         if(!ParseString(key) || !Consume(':')) return Fail("ENVELOPE_INVALID");
         if(key=="status")
           {
            if(status_seen || !ParseString(status)) return Fail("ENVELOPE_STATUS_INVALID");
            status_seen=true;
           }
         else if(key=="server_time")
           {
            if(server_time_seen || !ParseString(server_time)) return Fail("SERVER_TIME_INVALID");
            server_time_seen=true;
           }
         else if(key=="data")
           {
            if(data_seen || !ParseRows(rows)) return Fail("DATA_INVALID");
            data_seen=true;
           }
         else if(!SkipValue(1)) return Fail("ENVELOPE_INVALID");

         SkipWhitespace();
         if(Consume('}')) break;
         if(!Consume(',')) return Fail("ENVELOPE_INVALID");
        }
      SkipWhitespace();
      if(m_pos!=m_length) return Fail("BODY_JSON_INVALID");
      if(!status_seen || !server_time_seen || !data_seen) return Fail("ENVELOPE_REQUIRED_FIELD_MISSING");
      return true;
     }
  };

bool EAEvaluateLegacyBiasResponse(const string json,
                                  const string requested_asset,
                                  const long request_elapsed_ms,
                                  SEALegacyBiasResponse &response)
  {
   EAResetLegacyBiasResponse(response);
   if(request_elapsed_ms<0)
     {
      response.reason="REQUEST_DURATION_INVALID";
      return false;
     }
   if(requested_asset=="")
     {
      response.reason="REQUESTED_ASSET_INVALID";
      return false;
     }

   CEALegacyJsonParser parser;
   parser.Init(json);
   string status;
   string server_time;
   if(!parser.ParseEnvelope(status,server_time,response.rows))
     {
      response.reason=parser.Error();
      ArrayResize(response.rows,0);
      return false;
     }
   if(status!="success")
     {
      response.reason="ENVELOPE_STATUS_NOT_SUCCESS";
      ArrayResize(response.rows,0);
      return false;
     }
   if(!EAParseCanonicalUtcMs(server_time,false,response.server_time_ms))
     {
      response.reason="SERVER_TIME_INVALID";
      ArrayResize(response.rows,0);
      return false;
     }
   if(response.server_time_ms>LONG_MAX-request_elapsed_ms)
     {
      response.reason="AUTHORITATIVE_TIME_OVERFLOW";
      ArrayResize(response.rows,0);
      return false;
     }
   response.authoritative_now_ms=response.server_time_ms+request_elapsed_ms;
   int count=ArraySize(response.rows);
   if(count<=0)
     {
      response.reason="DATA_EMPTY";
      return false;
     }

   long previous_scan_ms=-1;
   for(int i=0;i<count;i++)
     {
      if(response.rows[i].asset!=requested_asset)
        {
         response.reason="ROW_ASSET_MISMATCH";
         ArrayResize(response.rows,0);
         return false;
        }
      if(response.rows[i].scan_timestamp_ms<=previous_scan_ms)
        {
         response.reason="ROWS_NOT_STRICTLY_ASCENDING";
         ArrayResize(response.rows,0);
         return false;
        }
      if(response.rows[i].valid_until_ms-response.rows[i].scan_timestamp_ms!=EA_LEGACY_VALIDITY_MS)
        {
         response.reason="ROW_VALIDITY_WINDOW_INVALID";
         ArrayResize(response.rows,0);
         return false;
        }
      if(response.rows[i].scan_timestamp_ms>response.authoritative_now_ms)
        {
         response.reason="ROW_FROM_FUTURE";
         ArrayResize(response.rows,0);
         return false;
        }
      previous_scan_ms=response.rows[i].scan_timestamp_ms;
     }

   if(response.rows[count-1].valid_until_ms<=response.authoritative_now_ms)
     {
      response.reason="VALID_UNTIL_EXPIRED";
      ArrayResize(response.rows,0);
      return false;
     }
   response.available=true;
   response.reason="";
   return true;
  }

#endif
