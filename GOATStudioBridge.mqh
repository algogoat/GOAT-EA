#ifndef GOAT_STUDIO_BRIDGE_MQH
#define GOAT_STUDIO_BRIDGE_MQH
// Include after GOATAIWireV2.mqh so the established JSON parser is available.
// Local Files only. Never writes native queues, globals, account settings or orders.
string GoatStudioQuote(const string value)
  {
   string out="\"";
   for(int i=0;i<StringLen(value);i++)
     {
      ushort c=StringGetCharacter(value,i);
      if(c=='"') out+="\\\"";
      else if(c=='\\') out+="\\\\";
      else if(c==10) out+="\\n";
      else if(c==13) out+="\\r";
      else if(c==9) out+="\\t";
      else if(c==8) out+="\\b";
      else if(c==12) out+="\\f";
      else if(c<32) out+=StringFormat("\\u%04x",(int)c);
      else out+=ShortToString(c);
     }
   return out+"\"";
  }

bool GoatStudioId(const string value)
  {
   if(StringLen(value)<1 || StringLen(value)>100) return false;
   for(int i=0;i<StringLen(value);i++)
     {
      ushort c=StringGetCharacter(value,i);
      if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-')) return false;
     }
   return true;
  }

bool GoatStudioReadUtf8(const string path,string &body,const bool common=false)
  {
   body="";
   int handle=FileOpen(path,FILE_READ|FILE_BIN|FILE_SHARE_READ|(common ? FILE_COMMON : 0));
   if(handle==INVALID_HANDLE) return false;
   ulong size=FileSize(handle);
   if(size==0 || size>2000000) {FileClose(handle); return false;}
   uchar bytes[];
   uint count=FileReadArray(handle,bytes,0,(uint)size);
   FileClose(handle);
   if(count!=(uint)size) return false;
   body=CharArrayToString(bytes,0,(int)count,CP_UTF8);
   return true;
  }

bool GoatStudioWriteUtf8(const string target,const string body,const bool replace=false)
  {
   uchar bytes[]; int count=StringToCharArray(body,bytes,0,WHOLE_ARRAY,CP_UTF8)-1;
   if(count<1 || count>2000000) return false;
   string temporary=target+"-"+(string)ChartID()+"-"+(string)GetMicrosecondCount()+".tmp";
   int handle=FileOpen(temporary,FILE_WRITE|FILE_BIN);
   if(handle==INVALID_HANDLE) return false;
   bool written=(FileWriteArray(handle,bytes,0,count)==(uint)count);
   FileFlush(handle); FileClose(handle);
   if(!written || !FileMove(temporary,0,target,replace ? FILE_REWRITE : 0)) {FileDelete(temporary); return false;}
   return true;
  }

class CGoatStudioBridge
  {
private:
   string m_root,m_terminal,m_run;
   bool m_bound,m_observed;
   long m_revision,m_generation;
   string m_owner;
public:
   CGoatStudioBridge(void):m_bound(false),m_observed(false),m_revision(-1),m_generation(-1) {}
   // Uncommitted editor state is separate from requests and committed drafts.
   string DraftPath(void) {return m_bound ? m_root+"\\human\\ui-draft.json" : "";}
   string TerminalId(void) {return m_terminal;}
   string RunId(void) {return m_run;}
   bool Bind(const string directory_id,const string terminal_id,const string run_id)
     {
      m_bound=false; m_observed=false; m_revision=-1; m_generation=-1;
      if(!GoatStudioId(directory_id) || terminal_id=="" || run_id=="") return false;
      m_root="GOATStudio\\"+directory_id;
      m_terminal=terminal_id; m_run=run_id;
      string body,terminal,run; SGOATJsonToken tokens[]; long version;
      if(!GoatStudioReadUtf8(m_root+"\\binding.json",body) || !GOATJsonParse(body,tokens)) return false;
      if(!GOATJsonGetInteger(body,tokens,0,"protocol_version",version) || version!=1
         || !GOATJsonGetString(body,tokens,0,"terminal_id",terminal) || terminal!=m_terminal
         || !GOATJsonGetString(body,tokens,0,"run_id",run) || run!=m_run) return false;
      m_bound=true; return true;
     }
   bool ReadSnapshot(string &body)
     {
      m_observed=false;
      if(!m_bound || !GoatStudioReadUtf8(m_root+"\\snapshot.json",body)) return false;
      SGOATJsonToken tokens[]; long version,revision,generation; string terminal,run,owner;
      if(!GOATJsonParse(body,tokens,16384,2000000) || !GOATJsonGetInteger(body,tokens,0,"protocol_version",version) || version!=1) return false;
      int state=GOATJsonFindField(body,tokens,0,"state");
      if(state<0 || tokens[state].type!=GOAT_JSON_OBJECT
         || !GOATJsonGetString(body,tokens,state,"terminal_id",terminal) || terminal!=m_terminal
         || !GOATJsonGetString(body,tokens,state,"run_id",run) || run!=m_run
         || !GOATJsonGetInteger(body,tokens,state,"revision",revision) || revision<0 || revision<m_revision
         || !GOATJsonGetInteger(body,tokens,state,"generation",generation) || generation<0 || generation<m_generation
         || !GOATJsonGetString(body,tokens,state,"owner",owner) || (owner!="human" && owner!="agent")) return false;
      m_revision=revision; m_generation=generation; m_owner=owner; m_observed=true;
      return true;
     }
   bool SubmitHuman(const string id,const string command,const string payload,string &request_hash,
                    const long expected_revision=-1,const long expected_generation=-1)
     {
      request_hash="";
      if(!m_bound || !m_observed || !GoatStudioId(id) || FileIsExist(m_root+"\\human\\pending.json")) return false;
      bool control=(command=="control.takeover" || command=="control.grant_agent");
      bool draft=(command=="draft.replace_tester" || command=="draft.replace_export"
                  || command=="draft.replace_configuration" || command=="draft.replace_strategy");
      bool queue=(command=="queue.enqueue" || command=="queue.cancel" || command=="queue.remove" || command=="queue.reorder");
      if(!control && !draft && !queue) return false; // Execution remains unavailable.
      if((draft || queue) && m_owner!="human") return false;
      SGOATJsonToken tokens[];
      if(!GOATJsonParse(payload,tokens) || tokens[0].type!=GOAT_JSON_OBJECT) return false;
      string body="{\"schema_version\":1,\"request_id\":"+GoatStudioQuote(id)
         +",\"terminal_id\":"+GoatStudioQuote(m_terminal)+",\"run_id\":"+GoatStudioQuote(m_run)
         +",\"expected_revision\":"+(string)(expected_revision<0 ? m_revision : expected_revision)
         +",\"generation\":"+(string)(expected_generation<0 ? m_generation : expected_generation)
         +",\"command\":"+GoatStudioQuote(command)+",\"payload\":"+payload+"}";
      if(!GOATSha256Utf8(body,request_hash)) return false;
      // Persist exact bytes before publishing; never construct a fresh retry after restart.
      if(!GoatStudioWriteUtf8(m_root+"\\human\\pending.json",body)) return false;
      GoatStudioWriteUtf8(m_root+"\\human\\inbox\\"+id+".json",body);
      // Journal acceptance is durable even if inbox publication needs retry.
      return true;
     }
   int RecoverPending(string &id,string &hash,string &command)
     {
      id=""; hash=""; command="";
      if(!m_bound) return -1;
      string path=m_root+"\\human\\pending.json";
      if(!FileIsExist(path)) return 0;
      string body,terminal,run; SGOATJsonToken tokens[]; long version,revision,generation;
      if(!GoatStudioReadUtf8(path,body) || !GOATJsonParse(body,tokens)
         || !GOATJsonGetInteger(body,tokens,0,"schema_version",version) || version!=1
         || !GOATJsonGetString(body,tokens,0,"request_id",id) || !GoatStudioId(id)
         || !GOATJsonGetString(body,tokens,0,"terminal_id",terminal) || terminal!=m_terminal
         || !GOATJsonGetString(body,tokens,0,"run_id",run) || run!=m_run
         || !GOATJsonGetString(body,tokens,0,"command",command)
         || !GOATJsonGetInteger(body,tokens,0,"expected_revision",revision) || revision<0
         || !GOATJsonGetInteger(body,tokens,0,"generation",generation) || generation<0
         || !GOATSha256Utf8(body,hash)) return -1;
      string receipt; bool applied;
      if(!ReadReceipt(id,hash,receipt,applied)
         && !FileIsExist(m_root+"\\human\\inbox\\"+id+".json")
         && !FileIsExist(m_root+"\\human\\processing\\"+id+".json"))
        {
         if(!GoatStudioWriteUtf8(m_root+"\\human\\inbox\\"+id+".json",body)) return -1;
        }
      return 1;
     }
   bool AcknowledgePending(const string id,const string hash)
     {
      string receipt; bool applied;
      if(!ReadReceipt(id,hash,receipt,applied)) return false;
      string body,current_hash; SGOATJsonToken tokens[]; string current_id;
      string path=m_root+"\\human\\pending.json";
      if(!FileIsExist(path)) return true; // Another attached observer already acknowledged it.
      if(!GoatStudioReadUtf8(path,body) || !GOATJsonParse(body,tokens)
         || !GOATJsonGetString(body,tokens,0,"request_id",current_id) || current_id!=id
         || !GOATSha256Utf8(body,current_hash) || current_hash!=hash) return false;
      return FileDelete(path);
     }
   bool ReadReceipt(const string id,const string request_hash,string &body,bool &applied)
     {
      applied=false;
      if(!m_bound || !GoatStudioId(id) || !GOATIsLowerHex(request_hash,64)
         || !GoatStudioReadUtf8(m_root+"\\human\\outbox\\"+id+".json",body)) return false;
      SGOATJsonToken tokens[]; string received_id,received_hash;
      if(!GOATJsonParse(body,tokens)
         || !GOATJsonGetString(body,tokens,0,"request_id",received_id) || received_id!=id
         || !GOATJsonGetString(body,tokens,0,"request_sha256",received_hash) || received_hash!=request_hash
         || !GOATJsonGetBoolean(body,tokens,0,"ok",applied)) return false;
      return true;
     }
  };
#endif
