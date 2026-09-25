// Versioned, byte-bound export units. Included only by the V1.48 producer.
#ifndef GOAT_SEQUENCE_PACKAGE_MQH
#define GOAT_SEQUENCE_PACKAGE_MQH
sinput bool Sequence_Export_Enabled=false;
sinput string Sequence_Export_Id="";
sinput datetime Sequence_Export_Start=0;
sinput datetime Sequence_Export_End=0;
sinput int Sequence_Export_Model=4;
string g_sequence_export_csv="",g_sequence_export_set="";

bool GoatSeqPathFits(const string path)
  {
   // MT5 can silently truncate long sandbox names before a filesystem call.
   // Reserve room for the terminating NUL; callers also check .tmp names.
   return StringLen(TerminalInfoString(TERMINAL_COMMONDATA_PATH)+"\\Files\\"+path)<=255;
  }

bool GoatSeqExists(const string path)
  {
   return GoatSeqPathFits(path) ? FileIsExist(path,FILE_COMMON) : GoatSeqHostExists(path);
  }

bool GoatSeqDeleteFile(const string path)
  {
   return GoatSeqPathFits(path) ? FileDelete(path,FILE_COMMON) : GoatSeqHostDelete(path);
  }

bool GoatSeqMoveFile(const string source,const string destination)
  {
   if(GoatSeqPathFits(source) && GoatSeqPathFits(destination)) return FileMove(source,FILE_COMMON,destination,FILE_COMMON);
   return GoatSeqHostMove(source,destination);
  }

string GoatSeqAttemptRoot(const string id)
  {
   uchar data[],key[],digest[];
   int length=StringToCharArray(id,data,0,WHOLE_ARRAY,CP_UTF8)-1;
   if(length<=0) return "";
   ArrayResize(data,length);
   if(CryptEncode(CRYPT_HASH_SHA256,data,key,digest)!=32) return "";
   string token="";
   for(int i=0;i<8;++i) token+=StringFormat("%02x",(int)digest[i]);
   return "TEMP\\SQ\\"+token;
  }

bool GoatSeqSafeId(const string id)
  {
   if(StringLen(id)<1 || StringLen(id)>96) return false;
   string allowed="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_";
   for(int i=0;i<StringLen(id);++i) if(StringFind(allowed,StringSubstr(id,i,1))<0) return false;
   return true;
  }

string GoatSeqJson(const string text)
  {
   string out="\"";
   for(int i=0;i<StringLen(text);++i)
     {
      ushort c=StringGetCharacter(text,i);
      if(c=='"') out+="\\\"";
      else if(c=='\\') out+="\\\\";
      else if(c<32) out+=StringFormat("\\u%04x",(int)c);
      else out+=ShortToString(c);
     }
   return out+"\"";
  }

string GoatSeqFileName(const string path)
  {
   int pos=StringLen(path)-1;
   while(pos>=0 && StringGetCharacter(path,pos)!='\\' && StringGetCharacter(path,pos)!='/') --pos;
   return StringSubstr(path,pos+1);
  }

string GoatSeqStem(const string path)
  {
   int n=StringLen(path);
   if(n>4 && (StringSubstr(path,n-4)==".csv" || StringSubstr(path,n-4)==".set")) return StringSubstr(path,0,n-4);
   return "";
  }

void GoatSeqMakePath(const string path)
  {
   if(!GoatSeqPathFits(path)) {Print("Sequence directory exceeds native MT5 path limit; preserved without creation");return;}
   for(int i=0;i<StringLen(path);++i)
      if(StringGetCharacter(path,i)=='\\') FolderCreate(StringSubstr(path,0,i),FILE_COMMON);
   FolderCreate(path,FILE_COMMON);
  }

bool GoatSeqHash(const string path,string &hash,long &size)
  {
   hash="";size=0;
   if(!GoatSeqPathFits(path))
     {
      string staged=GoatSeqHostStage(path);
      if(staged=="") return false;
      bool ok=GoatSeqHash(staged,hash,size);
      FileDelete(staged,FILE_COMMON);
      return ok;
     }
   int file=FileOpen(path,FILE_READ|FILE_BIN|FILE_COMMON|FILE_SHARE_READ);
   if(file==INVALID_HANDLE) return false;
   size=(long)FileSize(file);
   if(size<1 || size>536870912) {FileClose(file);return false;}
   uchar data[],key[],digest[];
   if(ArrayResize(data,(int)size)!=(int)size) {FileClose(file);return false;}
   uint count=FileReadArray(file,data);FileClose(file);
   if((long)count!=size || CryptEncode(CRYPT_HASH_SHA256,data,key,digest)!=32) return false;
   for(int i=0;i<32;++i) hash+=StringFormat("%02x",(int)digest[i]);
   return true;
  }

bool GoatSeqCopyBytes(const string source,const string destination)
  {
   if((!GoatSeqPathFits(source) || !GoatSeqPathFits(destination)) && !GoatSeqHostAllowed()) return false;
   if(GoatSeqExists(destination)) return false;
   string a="",b="";long sa=0,sb=0;
   if(!GoatSeqHash(source,a,sa)) return false;
   bool copied=(GoatSeqPathFits(source) && GoatSeqPathFits(destination)) ? FileCopy(source,FILE_COMMON,destination,FILE_COMMON) : GoatSeqHostCopy(source,destination);
   if(!copied && GoatSeqHostAllowed()) copied=GoatSeqHostCopy(source,destination); // Creates a missing parent without rewriting bytes.
   if(!copied) return false;
   return GoatSeqHash(destination,b,sb) && sa==sb && a==b;
  }

bool GoatSeqAtomicText(const string destination,const string body)
  {
   if(!GoatSeqPathFits(destination+".tmp")) return false;
   if(FileIsExist(destination,FILE_COMMON) || FileIsExist(destination+".tmp",FILE_COMMON)) return false;
   int file=FileOpen(destination+".tmp",FILE_WRITE|FILE_BIN|FILE_COMMON);
   if(file==INVALID_HANDLE) return false;
   uchar bytes[];int count=StringToCharArray(body,bytes,0,WHOLE_ARRAY,CP_UTF8)-1;
   bool ok=(count>=0 && FileWriteArray(file,bytes,0,count)==(uint)count);
   ResetLastError();FileFlush(file);if(GetLastError()!=0) ok=false;
   FileClose(file);
   if(!ok) return false;
   return FileMove(destination+".tmp",FILE_COMMON,destination,FILE_COMMON);
  }

bool GoatSeqClaimAttempt()
  {
   if(!MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || MQLInfoInteger(MQL_FORWARD) || Sequence_Export_Id=="") return true;
   if(!GoatSeqSafeId(Sequence_Export_Id)) return false;
   string path="GOATSequencePending\\"+Sequence_Export_Id;
   GoatSeqMakePath(path);
   string body="{\"runId\":"+GoatSeqJson(Sequence_Export_Id)+",\"state\":\"native-attempt-issued\"}";
   if(!GoatSeqAtomicText(path+"\\attempt-issued.json",body)) return false;
   string root=GoatSeqAttemptRoot(Sequence_Export_Id);
   if(root=="") return false;
   GoatSeqMakePath(root);
   return GoatSeqAtomicText(root+"\\attempt-issued.json",body);
  }

string GoatSeqBinding(const string path,const string relative)
  {
   string hash="";long size=0;
   if(!GoatSeqHash(path,hash,size)) return "";
   return "{\"path\":"+GoatSeqJson(relative)+",\"sha256\":"+GoatSeqJson(hash)+",\"bytes\":"+(string)size+"}";
  }

string GoatSeqReadText(const string path)
  {
   if(!GoatSeqPathFits(path))
     {
      string staged=GoatSeqHostStage(path);
      if(staged=="") return "";
      string body=GoatSeqReadText(staged);
      FileDelete(staged,FILE_COMMON);
      return body;
     }
   int file=FileOpen(path,FILE_READ|FILE_BIN|FILE_COMMON|FILE_SHARE_READ);
   if(file==INVALID_HANDLE) return "";
   long size=(long)FileSize(file);
   if(size<1 || size>4194304) {FileClose(file);return "";}
   uchar data[];ArrayResize(data,(int)size);
   uint count=FileReadArray(file,data);FileClose(file);
   return ((long)count==size ? CharArrayToString(data,0,(int)size,CP_UTF8) : "");
  }

bool GoatSeqUnitFiles(const string csv,string &files[])
  {
   ArrayResize(files,0);
   string stem=GoatSeqStem(csv),dir=stem+".goatseq";
   if(stem=="" || !GoatSeqExists(csv) || !GoatSeqExists(stem+".set") || !GoatSeqExists(dir+"\\manifest.json")) return false;
   ArrayResize(files,2);files[0]=csv;files[1]=stem+".set";
   if(!GoatSeqPathFits(dir+"\\report-reconciliation.json"))
     {
      string names[];
      if(!GoatSeqHostList(dir,names)) return false;
      for(int i=0;i<ArraySize(names);++i)
        {
         if(names[i]=="manifest.json") continue;
         int n=ArraySize(files);ArrayResize(files,n+1);files[n]=dir+"\\"+names[i];
        }
      int n=ArraySize(files);ArrayResize(files,n+1);files[n]=dir+"\\manifest.json";
      return true;
     }
   string name="";long find=FileFindFirst(dir+"\\*",name,FILE_COMMON);
   if(find==INVALID_HANDLE) return false;
   do
     {
      if(name=="manifest.json") continue;
      string path=dir+"\\"+name;
      if(!GoatSeqPathFits(path)) {FileFindClose(find);return false;}
      if(!FileIsExist(path,FILE_COMMON)) {FileFindClose(find);return false;}
      int n=ArraySize(files);ArrayResize(files,n+1);files[n]=path;
     }while(FileFindNext(find,name));
   FileFindClose(find);
   int n=ArraySize(files);ArrayResize(files,n+1);files[n]=dir+"\\manifest.json";
   return true;
  }

// Copy/verify all data before publishing the destination completion manifest.
// Failed copies retain source and destination diagnostics; never cross-attach.
bool GoatSeqTransferUnit(const string csv,const string destination_csv,const bool move)
  {
   string source[],target[];
   if(!GoatSeqUnitFiles(csv,source)) return false;
   string oldstem=GoatSeqStem(csv),newstem=GoatSeqStem(destination_csv);
   if(newstem=="" || GoatSeqFileName(oldstem)!=GoatSeqFileName(newstem)) return false;
   int count=ArraySize(source);ArrayResize(target,count);
   for(int i=0;i<count;++i)
     {
      target[i]=newstem+StringSubstr(source[i],StringLen(oldstem));
      if((!GoatSeqPathFits(source[i]) || !GoatSeqPathFits(target[i]+".tmp")) && !GoatSeqHostAllowed()) {Print("Sequence package requires controller long-path IO; entire source retained: ",target[i]);return false;}
      if(GoatSeqExists(target[i]) || GoatSeqExists(target[i]+".tmp")) return false;
     }
   if(GoatSeqPathFits(newstem+".goatseq")) GoatSeqMakePath(newstem+".goatseq"); // Host byte copy creates long directories.
   for(int i=0;i<count-1;++i) if(!GoatSeqCopyBytes(source[i],target[i])) return false;
   if(!GoatSeqCopyBytes(source[count-1],target[count-1]+".tmp")) return false;
   if(!GoatSeqMoveFile(target[count-1]+".tmp",target[count-1])) return false;
   if(move)
     {
      if(!GoatSeqDeleteFile(source[count-1])) return false;
      for(int i=0;i<count-1;++i) if(!GoatSeqDeleteFile(source[i])) return false;
      if(GoatSeqPathFits(oldstem+".goatseq")) FolderDelete(oldstem+".goatseq",FILE_COMMON);
      else GoatSeqHostRemoveEmpty(oldstem+".goatseq");
     }
   return true;
  }

bool GoatSeqDeleteUnit(const string csv)
  {
   string files[];
   if(!GoatSeqUnitFiles(csv,files)) return false;
   string manifest=GoatSeqReadText(files[ArraySize(files)-1]);
   // Failed attempts are diagnostic evidence, not normal trimming candidates.
   if(StringFind(manifest,"\"status\":\"complete-awaiting-import-verification\"")<0) return false;
   if(!GoatSeqDeleteFile(files[ArraySize(files)-1])) return false;
   for(int i=0;i<ArraySize(files)-1;++i) if(!GoatSeqDeleteFile(files[i])) return false;
   if(GoatSeqPathFits(GoatSeqStem(csv)+".goatseq")) FolderDelete(GoatSeqStem(csv)+".goatseq",FILE_COMMON);
   else GoatSeqHostRemoveEmpty(GoatSeqStem(csv)+".goatseq");
   return true;
  }
#endif
