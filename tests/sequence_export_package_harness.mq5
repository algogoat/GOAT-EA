#property strict
#property version "1.00"
#define GOAT_SEQUENCE_HOST_TEST 1
sinput bool Test_Host_IO=false;
#include "..\MTTester.mqh"
#include "..\GOAT_SequenceHostIO.mqh"
#include "..\GOAT_SequencePackage.mqh"

// Fixed-tester, no-trade harness for the actual producer filesystem helpers.
// Each invocation requires a fresh ID; test output is retained for inspection.
sinput string Test_Run_Id="";
int failures=0,checks=0;
string testRoot="";

void Check(const bool passed,const string label)
  {
   checks++;
   if(!passed) {failures++;Print("SEQUENCE PACKAGE TEST FAILED: ",label);}
  }

bool Fixture(const string root,const string status)
  {
   GoatSeqMakePath(root+"\\candidate.goatseq");
   uchar bytes[6]={255,254,0,128,65,0};
   int file=FileOpen(root+"\\candidate.set",FILE_WRITE|FILE_BIN|FILE_COMMON);
   if(file==INVALID_HANDLE) return false;
   bool ok=FileWriteArray(file,bytes)==6;FileClose(file);
   ok=GoatSeqAtomicText(root+"\\candidate.csv","<DATE>\t<BALANCE>\r\n2026.02.02 00:05\t100000\r\n") && ok;
   ok=GoatSeqAtomicText(root+"\\candidate.goatseq\\run.csv","key,value\r\nrun_id,fixture\r\n") && ok;
   if(status!="") ok=GoatSeqAtomicText(root+"\\candidate.goatseq\\manifest.json","{\"status\":"+GoatSeqJson(status)+"}") && ok;
   return ok;
  }

int OnInit()
  {
   if(!MQLInfoInteger(MQL_TESTER) || MQLInfoInteger(MQL_OPTIMIZATION) || !GoatSeqSafeId(Test_Run_Id)) return INIT_PARAMETERS_INCORRECT;
   testRoot="GOATSequenceProducerTests\\"+Test_Run_Id;
   GoatSeqMakePath(testRoot);
   if(!GoatSeqAtomicText(testRoot+"\\issued.json","{\"issued\":true}")) return INIT_FAILED;
   Check(Fixture(testRoot+"\\source","complete-awaiting-import-verification"),"fixture created");
   string source=testRoot+"\\source\\candidate.csv",copy=testRoot+"\\copy\\candidate.csv",moved=testRoot+"\\moved\\candidate.csv";
   Check(GoatSeqTransferUnit(source,copy,false),"copy entire completed unit");
   string a="",b="";long sa=0,sb=0;
   Check(GoatSeqHash(GoatSeqStem(source)+".set",a,sa) && GoatSeqHash(GoatSeqStem(copy)+".set",b,sb) && a==b && sa==sb,"SET bytes survive copy including non-UTF8 bytes");
   Check(FileIsExist(GoatSeqStem(source)+".goatseq\\manifest.json",FILE_COMMON),"copy retains source manifest");
   Check(!GoatSeqTransferUnit(source,copy,false),"duplicate destination rejected");
   Check(GoatSeqHash(GoatSeqStem(copy)+".set",b,sb) && a==b,"duplicate cannot mutate destination");
   Check(GoatSeqTransferUnit(source,moved,true),"move completed unit");
   Check(!FileIsExist(source,FILE_COMMON) && !FileIsExist(GoatSeqStem(source)+".set",FILE_COMMON) && !FileIsExist(GoatSeqStem(source)+".goatseq\\manifest.json",FILE_COMMON),"move retires entire source");
   Check(FileIsExist(GoatSeqStem(moved)+".goatseq\\run.csv",FILE_COMMON),"move carries raw evidence");
   Check(GoatSeqDeleteUnit(moved),"trim completed unit");
   Check(!FileIsExist(moved,FILE_COMMON) && !FileIsExist(GoatSeqStem(moved)+".set",FILE_COMMON) && !FileIsExist(GoatSeqStem(moved)+".goatseq\\run.csv",FILE_COMMON),"trim leaves no detached evidence");
   Check(Fixture(testRoot+"\\incomplete","incomplete"),"incomplete fixture");
   Check(!GoatSeqDeleteUnit(testRoot+"\\incomplete\\candidate.csv"),"preserve incomplete diagnostics");
   Check(FileIsExist(testRoot+"\\incomplete\\candidate.goatseq\\run.csv",FILE_COMMON),"incomplete evidence retained");
   Check(Fixture(testRoot+"\\cancelled",""),"uncommitted fixture");
   Check(!GoatSeqTransferUnit(testRoot+"\\cancelled\\candidate.csv",testRoot+"\\cancelled-destination\\candidate.csv",true),"uncommitted package cannot move");
   Check(FileIsExist(testRoot+"\\cancelled\\candidate.set",FILE_COMMON),"uncommitted source remains intact");
   Check(!GoatSeqAtomicText(testRoot+"\\issued.json","changed"),"atomic marker cannot overwrite");
   string long_root=testRoot;
   for(int i=0;i<20;++i) long_root+="\\long-path-segment";
   Check(!GoatSeqPathFits(long_root+"\\candidate.goatseq\\report-reconciliation.json"),"overlong native path rejected before writing");
   if(Test_Host_IO)
     {
      Check(GoatSeqTransferUnit(copy,long_root+"\\candidate.csv",false),"controller copies long destination byte-for-byte");
      Check(!GoatSeqTransferUnit(copy,long_root+"\\candidate.csv",false),"long destination collision rejected");
      Check(GoatSeqTransferUnit(long_root+"\\candidate.csv",long_root+"-moved\\candidate.csv",true),"controller moves complete long source and destination");
      Check(GoatSeqDeleteUnit(long_root+"-moved\\candidate.csv"),"controller trims complete long package");
      Check(!GoatSeqExists(long_root+"-moved\\candidate.goatseq\\manifest.json"),"long trim removes manifest");
      Check(!GoatSeqHostCopy(copy,"..\\outside.csv"),"host adapter rejects parent traversal");
     }
   else Check(!GoatSeqTransferUnit(copy,long_root+"\\candidate.csv",false),"overlong transfer cannot truncate destination");
   Check(FileIsExist(copy,FILE_COMMON) && FileIsExist(GoatSeqStem(copy)+".goatseq\\manifest.json",FILE_COMMON),"overlong transfer retains whole source");
   string pair[];ArrayResize(pair,2);
   pair[0]=testRoot+"\\cancelled\\candidate.csv";pair[1]=testRoot+"\\cancelled\\candidate.set";
   Check(GoatSeqPairReady(pair,false),"ordinary CSV SET pair ready without sequence manifest");
   Check(!GoatSeqPairReady(pair,true),"capture enabled requires final manifest");
   pair[1]=testRoot+"\\cancelled\\different.set";
   Check(!GoatSeqPairReady(pair,false),"different stems cannot form a completed pair");
   ArrayResize(pair,1);
   Check(!GoatSeqPairReady(pair,false),"missing SET is never ready even capture off");
   if(Sequence_Export_Id!="" && !Sequence_Export_Enabled)
     {
      Check(GoatSeqClaimAttempt(),"capture off claims unique native export routing");
      Check(FileIsExist(GoatSeqAttemptRoot(Sequence_Export_Id)+"\\attempt-issued.json",FILE_COMMON),"capture off preserves unique attempt marker");
      Check(!FileIsExist("GOATSequencePending\\"+Sequence_Export_Id+"\\attempt-issued.json",FILE_COMMON),"capture off creates no pending evidence marker");
      Check(!GoatSeqClaimAttempt(),"capture off rejects duplicate export identity");
     }
   GoatSeqAtomicText(testRoot+"\\result.json","{\"checks\":"+(string)checks+",\"failures\":"+(string)failures+",\"passed\":"+(failures==0?"true":"false")+"}");
   Print("SEQUENCE PACKAGE TESTS ",checks," checks, ",failures," failures: ",testRoot);
   return INIT_SUCCEEDED;
  }
void OnTick() {TesterStop();}
