//+------------------------------------------------------------------+
//| GOATDeployProfileWriter.mqh                                      |
//| B44 dashboard Deploy All (P-beta25-D5-dashboard-deploy-all):     |
//| the pure-string core of the MQL deploy-profile writer.           |
//+------------------------------------------------------------------+
// The MQL twin of controller/studio_deploy_profile.py (profile-staged-v1). It must produce the
// same bytes as the Python writer for every chart of a GOAT-Deploy-<id16> profile and for the
// dashboard state TSV: controller/contracts/profile-fixtures/g2 and g4 are the goldens, and
// scripts/test_profile_writer_goldens.cjs runs THIS source against them after a syntax-only
// conversion. Design: docs/operations/B44-DEPLOY-ALL-DESIGN.md.
//
// Pure core only: no file, chart, terminal, DLL or trade call. It turns SET bytes into chart
// bytes, or refuses with the Python writer's refusal code. The native shell (sandbox staging,
// create-only copy into Profiles\Charts, readback) and the dashboard wiring are B44.1 work.
//
// Source rules that keep the offline conversion honest (the harness checks them):
// no division, no StringFormat, no implicit numeric-to-string conversion, every narrowing
// cast is masked first, char literals only against StringGetCharacter results, and every
// local and parameter starts with pw_.
#ifndef GOAT_DEPLOY_PROFILE_WRITER_MQH
#define GOAT_DEPLOY_PROFILE_WRITER_MQH

#define GOAT_PW_PROFILE_PREFIX "GOAT-Deploy-"
#define GOAT_PW_PROFILE_FORMAT "profile-staged-v1"
#define GOAT_PW_EXPERT_MODE "5"
#define GOAT_PW_NONCE_INPUT "Studio_MonitorRunPath"
#define GOAT_PW_NONCE_PREFIX "deploy="
#define GOAT_PW_STATE_HEADER "#GOAT_AI_LAUNCH_V147_2"
#define GOAT_PW_MAX_INPUT_LINES 4096
#define GOAT_PW_MAX_MEMBERS 100
#define GOAT_PW_DASHBOARD_SLOT 1
// Refusal codes: the Python writer's, plus the two cases where Python raises a plain decode
// or value error without a code of its own.
#define GOAT_PW_PERIOD_REFUSED "SET_PERIOD_UNSUPPORTED"
#define GOAT_PW_LINE_REFUSED "SET_LINE_UNSUPPORTED"
#define GOAT_PW_SET_EMPTY "SET_NO_INPUTS"
#define GOAT_PW_NONCE_REFUSED "SET_RUN_PATH_UNSUPPORTED"
#define GOAT_PW_ENCODING_REFUSED "SET_ENCODING_UNSUPPORTED"
#define GOAT_PW_VALUE_REFUSED "PROFILE_VALUE_UNSUPPORTED"

string g_goat_pw_refusal="";
string g_goat_pw_detail="";

bool GoatProfileWriterRefuse(const string pw_code,const string pw_detail)
{
   g_goat_pw_refusal=pw_code;
   g_goat_pw_detail=pw_detail;
   return false;
}

string GoatProfileWriterRefusal()
{
   return g_goat_pw_refusal;
}

string GoatProfileWriterDetail()
{
   return g_goat_pw_detail;
}

void GoatProfileWriterClear()
{
   g_goat_pw_refusal="";
   g_goat_pw_detail="";
}

void GoatProfileWriterPushLine(string &pw_lines[],const string pw_line)
{
   int pw_n=ArraySize(pw_lines);
   ArrayResize(pw_lines,pw_n+1);
   pw_lines[pw_n]=pw_line;
}

// ------------------------------------------------------------------ decode_set
// A SET starting FF FE is UTF-16LE; anything else is UTF-8 with at most one leading BOM.
// Both decoders are strict, like Python's: an odd UTF-16 length, an unpaired surrogate, or any
// ill-formed UTF-8 (Unicode table 3-7) is refused. A NUL is refused after a complete decode.
bool GoatProfileWriterDecodeSet(const uchar &pw_raw[],ushort &pw_units[])
{
   int pw_size=ArraySize(pw_raw);
   int pw_count=0;
   ArrayResize(pw_units,0);
   if(pw_size>=2 && pw_raw[0]==0xFF && pw_raw[1]==0xFE)
   {
      if(((pw_size-2)&1)!=0) return GoatProfileWriterRefuse(GOAT_PW_ENCODING_REFUSED,"odd UTF-16 length");
      ArrayResize(pw_units,(pw_size-2)>>1);
      for(int pw_i=2;pw_i<pw_size;pw_i+=2)
      {
         int pw_unit=pw_raw[pw_i] | (pw_raw[pw_i+1]<<8);
         pw_units[pw_count]=(ushort)(pw_unit & 0xFFFF);
         pw_count++;
      }
   }
   else
   {
      int pw_at=0;
      if(pw_size>=3 && pw_raw[0]==0xEF && pw_raw[1]==0xBB && pw_raw[2]==0xBF) pw_at=3;
      ArrayResize(pw_units,pw_size);
      while(pw_at<pw_size)
      {
         int pw_b0=pw_raw[pw_at];
         int pw_need=0,pw_low=0x80,pw_high=0xBF,pw_cp=0;
         if(pw_b0<0x80) { pw_need=0; pw_cp=pw_b0; }
         else if(pw_b0>=0xC2 && pw_b0<=0xDF) { pw_need=1; pw_cp=pw_b0 & 0x1F; }
         else if(pw_b0==0xE0) { pw_need=2; pw_low=0xA0; pw_cp=pw_b0 & 0x0F; }
         else if((pw_b0>=0xE1 && pw_b0<=0xEC) || pw_b0==0xEE || pw_b0==0xEF) { pw_need=2; pw_cp=pw_b0 & 0x0F; }
         else if(pw_b0==0xED) { pw_need=2; pw_high=0x9F; pw_cp=pw_b0 & 0x0F; }
         else if(pw_b0==0xF0) { pw_need=3; pw_low=0x90; pw_cp=pw_b0 & 0x07; }
         else if(pw_b0>=0xF1 && pw_b0<=0xF3) { pw_need=3; pw_cp=pw_b0 & 0x07; }
         else if(pw_b0==0xF4) { pw_need=3; pw_high=0x8F; pw_cp=pw_b0 & 0x07; }
         else return GoatProfileWriterRefuse(GOAT_PW_ENCODING_REFUSED,"ill-formed UTF-8");
         if(pw_at+pw_need>=pw_size && pw_need>0) return GoatProfileWriterRefuse(GOAT_PW_ENCODING_REFUSED,"truncated UTF-8");
         for(int pw_k=1;pw_k<=pw_need;pw_k++)
         {
            int pw_next=pw_raw[pw_at+pw_k];
            int pw_min=(pw_k==1 ? pw_low : 0x80);
            int pw_max=(pw_k==1 ? pw_high : 0xBF);
            if(pw_next<pw_min || pw_next>pw_max) return GoatProfileWriterRefuse(GOAT_PW_ENCODING_REFUSED,"ill-formed UTF-8");
            pw_cp=(pw_cp<<6) | (pw_next & 0x3F);
         }
         pw_at+=pw_need+1;
         if(pw_cp>=0x10000)
         {
            int pw_rest=pw_cp-0x10000;
            pw_units[pw_count]=(ushort)(0xD800 + ((pw_rest>>10) & 0x3FF));
            pw_count++;
            pw_units[pw_count]=(ushort)(0xDC00 + (pw_rest & 0x3FF));
            pw_count++;
         }
         else
         {
            pw_units[pw_count]=(ushort)(pw_cp & 0xFFFF);
            pw_count++;
         }
      }
      ArrayResize(pw_units,pw_count);
   }
   bool pw_nul=false;
   for(int pw_j=0;pw_j<pw_count;pw_j++)
   {
      int pw_u=pw_units[pw_j];
      if(pw_u==0) pw_nul=true;
      if(pw_u>=0xD800 && pw_u<=0xDBFF)
      {
         if(pw_j+1>=pw_count) return GoatProfileWriterRefuse(GOAT_PW_ENCODING_REFUSED,"unpaired UTF-16 surrogate");
         int pw_v=pw_units[pw_j+1];
         if(pw_v<0xDC00 || pw_v>0xDFFF) return GoatProfileWriterRefuse(GOAT_PW_ENCODING_REFUSED,"unpaired UTF-16 surrogate");
         pw_j++;
      }
      else if(pw_u>=0xDC00 && pw_u<=0xDFFF) return GoatProfileWriterRefuse(GOAT_PW_ENCODING_REFUSED,"unpaired UTF-16 surrogate");
   }
   if(pw_nul) return GoatProfileWriterRefuse(GOAT_PW_LINE_REFUSED,"a NUL character");
   return true;
}

// ------------------------------------------------------------------ set_input_lines
// Python str.isspace() for a unit that survives the control-character refusal.
bool GoatProfileWriterIsSpace(const int pw_u)
{
   return pw_u==0x20 || pw_u==0xA0 || pw_u==0x1680 || (pw_u>=0x2000 && pw_u<=0x200A) || pw_u==0x202F
          || pw_u==0x205F || pw_u==0x3000 || (pw_u>=0x09 && pw_u<=0x0D) || (pw_u>=0x1C && pw_u<=0x1F)
          || pw_u==0x85 || pw_u==0x2028 || pw_u==0x2029;
}

// Unicode category Cc, Zl or Zp, other than tab.
bool GoatProfileWriterIsBreakOrControl(const int pw_u)
{
   return (pw_u<0x20 && pw_u!=0x09) || (pw_u>=0x7F && pw_u<=0x9F) || pw_u==0x2028 || pw_u==0x2029;
}

// BuildTemplate's input lines: split on CRLF or LF, refuse what two readers could split
// differently, trim spaces/tabs/CR/LF, keep a line with a key before its first '='.
bool GoatProfileWriterSetInputLines(const uchar &pw_raw[],string &pw_lines[])
{
   ArrayResize(pw_lines,0);
   ushort pw_units[];
   if(!GoatProfileWriterDecodeSet(pw_raw,pw_units)) return false;
   int pw_count=ArraySize(pw_units);
   int pw_pieces=1;
   for(int pw_i=0;pw_i<pw_count;pw_i++) if(pw_units[pw_i]==0x0A) pw_pieces++;
   if(pw_pieces>GOAT_PW_MAX_INPUT_LINES+1) return GoatProfileWriterRefuse(GOAT_PW_LINE_REFUSED,"more than 4096 lines");
   int pw_start=0;
   for(int pw_at=0;pw_at<=pw_count;pw_at++)
   {
      if(pw_at<pw_count && pw_units[pw_at]!=0x0A) continue;
      int pw_end=pw_at;
      if(pw_at<pw_count && pw_end>pw_start && pw_units[pw_end-1]==0x0D) pw_end--;
      for(int pw_c=pw_start;pw_c<pw_end;pw_c++)
         if(GoatProfileWriterIsBreakOrControl(pw_units[pw_c]))
            return GoatProfileWriterRefuse(GOAT_PW_LINE_REFUSED,"a control character or a Unicode line or paragraph separator");
      int pw_a=pw_start,pw_b=pw_end;
      while(pw_a<pw_b && (pw_units[pw_a]==0x20 || pw_units[pw_a]==0x09)) pw_a++;
      while(pw_b>pw_a && (pw_units[pw_b-1]==0x20 || pw_units[pw_b-1]==0x09)) pw_b--;
      pw_start=pw_at+1;
      // B44 condition 2 (goatai#2350 6127809765): the export stamp ("; EXPORT: blind=... ranked=... sr=...") is provenance,
      // not an input: dropped, so a stamped B44 SET deploys byte for byte as its unstamped B43 twin (studio_deploy_profile too).
      if(pw_b-pw_a>=9 && ShortArrayToString(pw_units,pw_a,9)=="; EXPORT:") continue;
      int pw_eq=-1;
      for(int pw_e=pw_a;pw_e<pw_b && pw_eq<0;pw_e++) if(pw_units[pw_e]=='=') pw_eq=pw_e;
      if(pw_a>=pw_b || pw_eq<=pw_a) continue;
      if(GoatProfileWriterIsSpace(pw_units[pw_a]) || GoatProfileWriterIsSpace(pw_units[pw_b-1]))
         return GoatProfileWriterRefuse(GOAT_PW_LINE_REFUSED,"whitespace other than spaces and tabs around the line");
      for(int pw_g=pw_a;pw_g<pw_b;pw_g++)
         if(pw_units[pw_g]=='<' || pw_units[pw_g]=='>')
            return GoatProfileWriterRefuse(GOAT_PW_LINE_REFUSED,"a control character or < or > in an input line");
      GoatProfileWriterPushLine(pw_lines,ShortArrayToString(pw_units,pw_a,pw_b-pw_a));
   }
   if(ArraySize(pw_lines)==0)
      return GoatProfileWriterRefuse(GOAT_PW_SET_EMPTY,"the SET has no readable inputs, and a chart is never started on EA defaults");
   return true;
}

// ------------------------------------------------------------------ AI launch policy
bool GoatProfileWriterIsAIName(const string pw_name)
{
   return pw_name=="Mode_Bias" || pw_name=="Bias_threshold" || pw_name=="Bias_Protocol" || pw_name=="Mode_Bias_Trades";
}

// GoatAILaunchInputValue.
string GoatProfileWriterAIValue(const int pw_mode,const int pw_threshold,const string pw_name,const string pw_source,const int pw_protocol)
{
   if(pw_mode!=1 && pw_mode!=2) return pw_source;
   if(pw_name=="Mode_Bias") return (pw_mode==1 ? "0" : "2");
   if(pw_name=="Bias_threshold") return IntegerToString(pw_threshold);
   if(pw_name=="Bias_Protocol") return (pw_protocol==2 ? "2" : "1");
   if(pw_name=="Mode_Bias_Trades") return "0";
   return pw_source;
}

// GoatApplyAILaunchPolicy: the four AI inputs are replaced in place, then any missing ones are
// appended in the order Mode_Bias, Bias_threshold, Bias_Protocol, Mode_Bias_Trades.
void GoatProfileWriterApplyAIPolicy(string &pw_lines[],const int pw_mode,const int pw_threshold,const int pw_protocol)
{
   if(pw_mode!=1 && pw_mode!=2) return;
   string pw_found="|";
   int pw_n=ArraySize(pw_lines);
   for(int pw_i=0;pw_i<pw_n;pw_i++)
   {
      int pw_split=StringFind(pw_lines[pw_i],"=");
      if(pw_split<=0) continue;
      string pw_name=StringSubstr(pw_lines[pw_i],0,pw_split);
      string pw_value=(pw_split+1<StringLen(pw_lines[pw_i]) ? StringSubstr(pw_lines[pw_i],pw_split+1) : "");
      if(GoatProfileWriterIsAIName(pw_name)) pw_found+=pw_name+"|";
      pw_lines[pw_i]=pw_name+"="+GoatProfileWriterAIValue(pw_mode,pw_threshold,pw_name,pw_value,pw_protocol);
   }
   string pw_order[]={"Mode_Bias","Bias_threshold","Bias_Protocol","Mode_Bias_Trades"};
   for(int pw_k=0;pw_k<4;pw_k++)
      if(StringFind(pw_found,"|"+pw_order[pw_k]+"|")<0)
         GoatProfileWriterPushLine(pw_lines,pw_order[pw_k]+"="+GoatProfileWriterAIValue(pw_mode,pw_threshold,pw_order[pw_k],"",pw_protocol));
}

// ------------------------------------------------------------------ deployment nonce
bool GoatProfileWriterIsDeploymentId(const string pw_id)
{
   if(StringLen(pw_id)!=32) return false;
   for(int pw_i=0;pw_i<32;pw_i++)
   {
      int pw_c=StringGetCharacter(pw_id,pw_i);
      if(!((pw_c>='0' && pw_c<='9') || (pw_c>='a' && pw_c<='f'))) return false;
   }
   return true;
}

// A SET line naming Studio_MonitorRunPath with its "" default is replaced in place by
// Studio_MonitorRunPath=deploy=<deploymentId>; otherwise that line is appended last.
bool GoatProfileWriterWithNonce(string &pw_lines[],const string pw_deployment_id)
{
   if(!GoatProfileWriterIsDeploymentId(pw_deployment_id))
      return GoatProfileWriterRefuse(GOAT_PW_VALUE_REFUSED,"invalid deployment ID for the deploy nonce");
   string pw_nonce=GOAT_PW_NONCE_INPUT+"="+GOAT_PW_NONCE_PREFIX+pw_deployment_id;
   int pw_n=ArraySize(pw_lines),pw_found=-1,pw_hits=0;
   bool pw_bad=false;
   for(int pw_i=0;pw_i<pw_n;pw_i++)
   {
      int pw_split=StringFind(pw_lines[pw_i],"=");
      if(pw_split<=0 || StringSubstr(pw_lines[pw_i],0,pw_split)!=GOAT_PW_NONCE_INPUT) continue;
      pw_hits++;
      if(pw_found<0) pw_found=pw_i;
      if(pw_lines[pw_i]!=GOAT_PW_NONCE_INPUT+"=") pw_bad=true;
   }
   if(pw_hits>1 || pw_bad)
      return GoatProfileWriterRefuse(GOAT_PW_NONCE_REFUSED,"This member sets Studio_MonitorRunPath, which only a Studio monitor uses; export it again without it.");
   if(pw_found>=0) pw_lines[pw_found]=pw_nonce;
   else GoatProfileWriterPushLine(pw_lines,pw_nonce);
   return true;
}

// The staged child's inputs: SET lines, AI policy, then the nonce.
bool GoatProfileWriterChildInputLines(const uchar &pw_raw[],const int pw_ai_mode,const int pw_ai_threshold,const int pw_ai_protocol,
                                      const string pw_deployment_id,string &pw_lines[])
{
   if(!GoatProfileWriterSetInputLines(pw_raw,pw_lines)) return false;
   GoatProfileWriterApplyAIPolicy(pw_lines,pw_ai_mode,pw_ai_threshold,pw_ai_protocol);
   return GoatProfileWriterWithNonce(pw_lines,pw_deployment_id);
}

// ------------------------------------------------------------------ period, symbol, expert
// The whole token after the first comma of the SET name, up to the first character that is not
// A-Z or 0-9. Only M1, M5, H1, H4 and D1 deploy; "" after a refusal.
string GoatProfileWriterPeriodToken(const string pw_file_name)
{
   int pw_comma=StringFind(pw_file_name,",");
   int pw_len=StringLen(pw_file_name);
   string pw_token="";
   if(pw_comma>=0)
   {
      int pw_end=pw_comma+1;
      while(pw_end<pw_len)
      {
         int pw_c=StringGetCharacter(pw_file_name,pw_end);
         if(!((pw_c>='A' && pw_c<='Z') || (pw_c>='0' && pw_c<='9'))) break;
         pw_end++;
      }
      if(pw_end>pw_comma+1) pw_token=StringSubstr(pw_file_name,pw_comma+1,pw_end-pw_comma-1);
   }
   if(pw_token=="M1" || pw_token=="M5" || pw_token=="H1" || pw_token=="H4" || pw_token=="D1") return pw_token;
   GoatProfileWriterRefuse(GOAT_PW_PERIOD_REFUSED,"This portfolio has a timeframe the app can't deploy yet ("+(pw_token=="" ? "none" : pw_token)
                           +"): "+pw_file_name+". The app deploys M1, M5, H1, H4 and D1.");
   return "";
}

// MT5 stores a chart period as (unit, count): 0 = minutes, 1 = hours; a day is 24 hours.
int GoatProfileWriterPeriodUnit(const string pw_token)
{
   return (pw_token=="H1" || pw_token=="H4" || pw_token=="D1") ? 1 : 0;
}

int GoatProfileWriterPeriodCount(const string pw_token)
{
   if(pw_token=="M1" || pw_token=="H1") return 1;
   if(pw_token=="M5") return 5;
   if(pw_token=="H4") return 4;
   if(pw_token=="D1") return 24;
   return 0;
}

bool GoatProfileWriterSymbolOk(const string pw_symbol)
{
   int pw_len=StringLen(pw_symbol);
   if(pw_len<1 || pw_len>64) return false;
   for(int pw_i=0;pw_i<pw_len;pw_i++)
   {
      int pw_c=StringGetCharacter(pw_symbol,pw_i);
      if(!((pw_c>='A' && pw_c<='Z') || (pw_c>='a' && pw_c<='z') || (pw_c>='0' && pw_c<='9')
           || pw_c=='_' || pw_c=='.' || pw_c=='#' || pw_c=='-')) return false;
   }
   return true;
}

// The EA path relative to MQL5\Experts, in canonical form only: non-empty segments split by a
// single backslash, no "." or ".." segment, no drive, no '/', and a .ex5 file name with a stem.
// For every path it accepts, PureWindowsPath leaves the text unchanged, so the bytes agree.
bool GoatProfileWriterExpertOk(const string pw_ea)
{
   int pw_len=StringLen(pw_ea);
   if(pw_len<5) return false;
   int pw_seg=0;
   for(int pw_i=0;pw_i<=pw_len;pw_i++)
   {
      int pw_c=(pw_i<pw_len ? StringGetCharacter(pw_ea,pw_i) : '\\');
      if(pw_c=='/' || pw_c==':' || pw_c=='<' || pw_c=='>' || pw_c=='=' || pw_c<0x20) return false;
      if(pw_c!='\\') continue;
      int pw_size=pw_i-pw_seg;
      if(pw_size==0) return false;
      if(pw_size==1 && StringGetCharacter(pw_ea,pw_seg)=='.') return false;
      if(pw_size==2 && StringGetCharacter(pw_ea,pw_seg)=='.' && StringGetCharacter(pw_ea,pw_seg+1)=='.') return false;
      if(pw_i<pw_len) pw_seg=pw_i+1;
   }
   // After the loop pw_seg is the start of the file name; it needs a stem before ".ex5".
   if(pw_len-pw_seg<5) return false;
   int pw_dot=StringGetCharacter(pw_ea,pw_len-4);
   int pw_ext_e=StringGetCharacter(pw_ea,pw_len-3);
   int pw_ext_x=StringGetCharacter(pw_ea,pw_len-2);
   int pw_ext_five=StringGetCharacter(pw_ea,pw_len-1);
   return pw_dot=='.' && (pw_ext_e=='e' || pw_ext_e=='E') && (pw_ext_x=='x' || pw_ext_x=='X') && pw_ext_five=='5';
}

// (name, path) as MT5 stores them: the file stem, and Experts\ plus the relative path.
string GoatProfileWriterExpertName(const string pw_ea)
{
   int pw_len=StringLen(pw_ea);
   int pw_name_start=0;
   for(int pw_j=pw_len-1;pw_j>=0;pw_j--)
      if(StringGetCharacter(pw_ea,pw_j)=='\\') { pw_name_start=pw_j+1; break; }
   return StringSubstr(pw_ea,pw_name_start,pw_len-4-pw_name_start);
}

string GoatProfileWriterExpertPath(const string pw_ea)
{
   return "Experts\\"+pw_ea;
}

// ------------------------------------------------------------------ chart text and bytes
// The chart frame of studio_deploy_profile.chart_text_lines: no id=, no objects, no order.wnd.
string GoatProfileWriterChartText(const string pw_symbol,const string pw_token,const string pw_ea,const string &pw_inputs[])
{
   if(!GoatProfileWriterSymbolOk(pw_symbol))
   {
      GoatProfileWriterRefuse(GOAT_PW_VALUE_REFUSED,"unsupported chart symbol: "+pw_symbol);
      return "";
   }
   if(!GoatProfileWriterExpertOk(pw_ea))
   {
      GoatProfileWriterRefuse(GOAT_PW_VALUE_REFUSED,"unsupported EA path for a deploy profile: "+pw_ea);
      return "";
   }
   int pw_n=ArraySize(pw_inputs);
   for(int pw_i=0;pw_i<pw_n;pw_i++)
   {
      bool pw_ok=StringFind(pw_inputs[pw_i],"=")>0;
      int pw_len=StringLen(pw_inputs[pw_i]);
      for(int pw_k=0;pw_k<pw_len && pw_ok;pw_k++)
      {
         int pw_c=StringGetCharacter(pw_inputs[pw_i],pw_k);
         if(pw_c==0x0D || pw_c==0x0A || pw_c=='<' || pw_c=='>' || pw_c==0) pw_ok=false;
      }
      if(!pw_ok)
      {
         GoatProfileWriterRefuse(GOAT_PW_LINE_REFUSED,pw_inputs[pw_i]);
         return "";
      }
   }
   string pw_crlf="\r\n";
   string pw_text="<chart>"+pw_crlf+"symbol="+pw_symbol+pw_crlf
                  +"period_type="+IntegerToString(GoatProfileWriterPeriodUnit(pw_token))+pw_crlf
                  +"period_size="+IntegerToString(GoatProfileWriterPeriodCount(pw_token))+pw_crlf
                  +"scale=8"+pw_crlf+"mode=1"+pw_crlf+"grid=0"+pw_crlf+"scroll=1"+pw_crlf+"one_click=0"+pw_crlf
                  +"windows_total=1"+pw_crlf
                  +"<expert>"+pw_crlf+"name="+GoatProfileWriterExpertName(pw_ea)+pw_crlf
                  +"path="+GoatProfileWriterExpertPath(pw_ea)+pw_crlf
                  +"expertmode="+GOAT_PW_EXPERT_MODE+pw_crlf+"<inputs>"+pw_crlf;
   for(int pw_j=0;pw_j<pw_n;pw_j++) pw_text+=pw_inputs[pw_j]+pw_crlf;
   pw_text+="</inputs>"+pw_crlf+"</expert>"+pw_crlf
            +"<window>"+pw_crlf+"height=100.000000"+pw_crlf+"objects=0"+pw_crlf
            +"<indicator>"+pw_crlf+"name=Main"+pw_crlf+"path="+pw_crlf+"apply=1"+pw_crlf+"show_data=1"+pw_crlf
            +"</indicator>"+pw_crlf+"</window>"+pw_crlf+"</chart>"+pw_crlf;
   return pw_text;
}

// MT5's own chart encoding: UTF-16LE with a BOM. The text already ends every line in CRLF.
void GoatProfileWriterEncodeUtf16(const string pw_text,uchar &pw_out[])
{
   int pw_len=StringLen(pw_text);
   ArrayResize(pw_out,2+pw_len*2);
   pw_out[0]=0xFF;
   pw_out[1]=0xFE;
   for(int pw_i=0;pw_i<pw_len;pw_i++)
   {
      int pw_u=StringGetCharacter(pw_text,pw_i);
      pw_out[2+pw_i*2]=(uchar)(pw_u & 0xFF);
      pw_out[3+pw_i*2]=(uchar)((pw_u>>8) & 0xFF);
   }
}

// chart01.chr: the Portfolio Dashboard on M1, on member 0's symbol, with beta.24's six PRESET values.
bool GoatProfileWriterDashboardChart(const string pw_symbol,const string pw_ea,uchar &pw_out[])
{
   GoatProfileWriterClear();
   ArrayResize(pw_out,0);
   string pw_inputs[]={"Mode_Operation=8","Dashboard_Resume_Saved=true","Mode_Bias=1","Bias_Protocol=2","Bias_threshold=50","EA_Desc=GOAT Dashboard"};
   string pw_text=GoatProfileWriterChartText(pw_symbol,"M1",pw_ea,pw_inputs);
   if(pw_text=="") return false;
   GoatProfileWriterEncodeUtf16(pw_text,pw_out);
   return true;
}

// chart02.chr onwards: one child per member, in plan order. Refusals follow the Python order:
// the period, then the SET, then the symbol, then the EA path.
bool GoatProfileWriterChildChart(const string pw_file_name,const string pw_symbol,const uchar &pw_raw[],const string pw_ea,
                                 const int pw_ai_mode,const int pw_ai_threshold,const int pw_ai_protocol,
                                 const string pw_deployment_id,uchar &pw_out[])
{
   GoatProfileWriterClear();
   ArrayResize(pw_out,0);
   string pw_token=GoatProfileWriterPeriodToken(pw_file_name);
   if(pw_token=="") return false;
   string pw_lines[];
   if(!GoatProfileWriterChildInputLines(pw_raw,pw_ai_mode,pw_ai_threshold,pw_ai_protocol,pw_deployment_id,pw_lines)) return false;
   string pw_text=GoatProfileWriterChartText(pw_symbol,pw_token,pw_ea,pw_lines);
   if(pw_text=="") return false;
   GoatProfileWriterEncodeUtf16(pw_text,pw_out);
   return true;
}

// ------------------------------------------------------------------ profile names
string GoatProfileWriterProfileName(const string pw_deployment_id)
{
   if(!GoatProfileWriterIsDeploymentId(pw_deployment_id))
   {
      GoatProfileWriterRefuse(GOAT_PW_VALUE_REFUSED,"invalid deployment ID for the deploy profile");
      return "";
   }
   return GOAT_PW_PROFILE_PREFIX+StringSubstr(pw_deployment_id,0,16);
}

// chart01.chr .. chart101.chr; "" outside 1..101.
string GoatProfileWriterChartFileName(const int pw_slot)
{
   if(pw_slot<1 || pw_slot>GOAT_PW_MAX_MEMBERS+1) return "";
   return "chart"+(pw_slot<10 ? "0" : "")+IntegerToString(pw_slot)+".chr";
}

bool GoatProfileWriterMemberCountOk(const int pw_members)
{
   return pw_members>=1 && pw_members<=GOAT_PW_MAX_MEMBERS;
}

// ------------------------------------------------------------------ dashboard state TSV
// studio_demo_deploy.state_bytes: the V147_2 header with the AI policy, then one row per member in
// plan order, every row starting cid=0 magic=0. A field holding a tab, CR or LF is refused.
bool GoatProfileWriterTsvFieldOk(const string pw_field)
{
   int pw_len=StringLen(pw_field);
   for(int pw_i=0;pw_i<pw_len;pw_i++)
   {
      int pw_c=StringGetCharacter(pw_field,pw_i);
      if(pw_c==0x09 || pw_c==0x0A || pw_c==0x0D || pw_c==0) return false;
   }
   return true;
}

bool GoatProfileWriterStateFile(const int pw_ai_mode,const int pw_ai_threshold,const int pw_ai_protocol,const string &pw_paths[],
                                const string &pw_names[],const string &pw_symbols[],const string &pw_strategies[],uchar &pw_out[])
{
   GoatProfileWriterClear();
   ArrayResize(pw_out,0);
   int pw_n=ArraySize(pw_paths);
   if(!GoatProfileWriterMemberCountOk(pw_n) || ArraySize(pw_names)!=pw_n || ArraySize(pw_symbols)!=pw_n || ArraySize(pw_strategies)!=pw_n)
      return GoatProfileWriterRefuse(GOAT_PW_VALUE_REFUSED,"a deploy profile holds 1 to 100 members");
   string pw_tab="\t",pw_crlf="\r\n";
   string pw_text=GOAT_PW_STATE_HEADER+pw_tab+IntegerToString(pw_ai_mode)+pw_tab+IntegerToString(pw_ai_threshold)+pw_tab
                  +IntegerToString(pw_ai_protocol)+pw_crlf;
   for(int pw_i=0;pw_i<pw_n;pw_i++)
   {
      if(!GoatProfileWriterTsvFieldOk(pw_paths[pw_i]) || !GoatProfileWriterTsvFieldOk(pw_names[pw_i])
         || !GoatProfileWriterTsvFieldOk(pw_symbols[pw_i]) || !GoatProfileWriterTsvFieldOk(pw_strategies[pw_i]))
         return GoatProfileWriterRefuse(GOAT_PW_VALUE_REFUSED,"a dashboard row field holds a tab or a line break");
      pw_text+=pw_paths[pw_i]+pw_tab+pw_names[pw_i]+pw_tab+pw_symbols[pw_i]+pw_tab+pw_strategies[pw_i]+pw_tab
               +"As SET"+pw_tab+"As optimized"+pw_tab+"As SET"+pw_tab+"0"+pw_tab+"0"+pw_crlf;
   }
   GoatProfileWriterEncodeUtf16(pw_text,pw_out);
   return true;
}

#endif
