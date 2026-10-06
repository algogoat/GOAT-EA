// A back pass is kept only with profit >= 0.001 and at least this many back trades.
#define GOAT_XML_MIN_BACK_TRADES 50
// A combined (back + forward) row is exported only with at least this score.
#define GOAT_XML_MIN_COMBINED_SCORE 60.0
// Kept passes were scored with their forward period and none reached the export score.
#define GOAT_XML_NO_QUALIFYING_ROWS "no_qualifying_rows"
// below_score export (goatai#1885): the export tier and its folder name, and the FWD trade floor
// (the controller's OOS window floor, studio_oos_windows.MIN_TRADES).
#define GOAT_XML_BELOW_SCORE "below_score"
#define GOAT_XML_BELOW_SCORE_MIN_FWD_TRADES 30
// Switch-on fall-through outcome (GOAT_EXPORT_RANK_FWD_PROFIT_DD): passes reached the score, none was FWD-eligible.
#define GOAT_XML_NO_FWD_ELIGIBLE_ROWS "no_fwd_eligible_rows"
//+------------------------------------------------------------------+
//| Data structure for a single row (Back/Forward test record)      |
//+------------------------------------------------------------------+
struct SRowDefinition
{
   int pass; //--- Core fields
   double back_result,   back_profit,   back_PF,   back_RF,   back_SR,   back_DD_pc;
   int back_trades;
   double forward_result,forward_profit,forward_PF,forward_RF,forward_SR,forward_DD_pc;
   int forward_trades;
   string Inputs; // e.g. "10,1.0,0.02" for 3 input values
   double Score;  // custom score
   bool forward_seen; // this kept back pass was found in the forward report

   SRowDefinition()
   {
      pass=-1; back_result=0; back_profit=0; back_PF=0; back_RF=0; back_SR=0; back_DD_pc=0; back_trades=0;
      forward_result=0; forward_profit=0; forward_PF=0; forward_RF=0; forward_SR=0; forward_DD_pc=0; forward_trades=0;
      Inputs=""; Score=0; forward_seen=false;
   }
   SRowDefinition(const SRowDefinition &src)
   {
      pass=src.pass;
      back_result=src.back_result; back_profit=src.back_profit; back_PF=src.back_PF; back_RF=src.back_RF; back_SR=src.back_SR; back_DD_pc=src.back_DD_pc; back_trades=src.back_trades;
      forward_result=src.forward_result; forward_profit=src.forward_profit; forward_PF=src.forward_PF; forward_RF=src.forward_RF; forward_SR=src.forward_SR;
      forward_DD_pc=src.forward_DD_pc; forward_trades=src.forward_trades;
      Inputs=src.Inputs;
      Score=src.Score;
      forward_seen=src.forward_seen;
   }
};
//+------------------------------------------------------------------+
//| Container struct to process/store XML data and handle logic     |
//+------------------------------------------------------------------+
struct SXmlData
{
public:
   string _K,_N,_S;
   bool reportMode;
   SRowDefinition Rows[],topRowsNoDup[],RowsUnique[];
   string metadataWithWorkbookStart, DocumentProperties, Title, WorksheetLine, InputsNames, symbol_,TF_;
   datetime startD, endD, forwardD;
   string m_inputVarNames[];
   // Every back pass is counted before the profit/trade filter below, so a report
   // whose passes all lost is told apart from a report that could not be read.
   int passesSeen, profitableSeen;
   double bestProfit, bestResult;
   // Proof the optimization really ran and the report is whole: passes with trades,
   // rows that did not parse, and whether the results table closed normally.
   int tradedSeen, malformedSeen, forwardRows;
   bool reportClosed;
   // Forward merge evidence: kept passes found in the forward report, passes whose back
   // values or inputs disagree (or repeat), forward rows that did not parse, and the
   // best combined score after sorting.
   int forwardMatched, forwardMismatches, forwardMalformed;
   double bestCombinedScore;
   string outcome;     // set by ReportAnalyzerCombiner; "" unless every pair was tested without edge
   string pairOutcome; // the research outcome of the last pair read, "" when it was not one
#ifdef GOAT_BELOW_SCORE_EXPORT_V149
   int belowScoreRow;  // Rows[] index of the below_score slot 1 (GoatXmlFwdRank first), -1 when none
#endif
//+------------------------------------------------------------------+
   bool ProcessBackXml(const string &filename)
   {
      ResetData();
      int hBack=FileOpen(filename, FILE_READ|FILE_COMMON|FILE_ANSI, '\t', CP_UTF8);
      if(hBack==INVALID_HANDLE) {LogOrPrint(reportMode,"❌ "+__FUNCTION__+": Error opening back file: "+filename,_K,_N,_S); return false;}
      else                       LogOrPrint(reportMode,"Back File Processing Start...",_K,_N,_S);
      string line="";
      while(!FileIsEnding(hBack))
      {
         line=FileReadString(hBack); if(line=="")continue;
         if(StringFind(line,"<DocumentProperties")>=0)break;
         metadataWithWorkbookStart+=line+"\n";
      }
      DocumentProperties+=line;
      while(!FileIsEnding(hBack))
      {
         line=FileReadString(hBack); if(line=="")continue;
         if(StringFind(line,"</DocumentProperties")>=0)break;
         DocumentProperties+=line+"\n";
      }
      DocumentProperties+=line;
      
      if(!ExtractTitleFromDocument(DocumentProperties,Title)){LogOrPrint(reportMode,"❌ Could not find <Title>.",_K,_N,_S); return false;}
      else                                                    LogOrPrint(reportMode,"Title: "+Title,_K,_N,_S);
      
      if(ExtractDatesFromTitle(Title,startD,endD)) 
           LogOrPrint(reportMode,"Extracted Back Test range: "+TimeToString(startD,TIME_DATE)+" - "+TimeToString(endD,TIME_DATE),_K,_N,_S);
      else LogOrPrint(reportMode,"❌ Could not parse date range in: "+Title,_K,_N,_S);
      
      if(ExtractSymbolTfFromTitle(Title,symbol_,TF_))
           LogOrPrint(reportMode,"Extracted Symbol, TF: "+symbol_+", "+TF_,_K,_N,_S);
      else LogOrPrint(reportMode,"❌ Could not parse symbol/time‑frame in: "+Title,_K,_N,_S);
      
      while(!FileIsEnding(hBack))
      {
         line=FileReadString(hBack); if(line=="")continue;
         if(StringFind(line,"<Worksheet")>=0){WorksheetLine+=line;break;}
      }
      while(!FileIsEnding(hBack))
      {
         line=FileReadString(hBack); if(line=="")continue;
         if(StringFind(line,"<Row>")>=0)
         {
            while(!FileIsEnding(hBack))
            {
               line=FileReadString(hBack); if(line=="")continue;
               if(StringFind(line,">Trades<")>=0)break;
            }
            break;
         }
      }
      while(!FileIsEnding(hBack))
      {
         line=FileReadString(hBack); if(line=="")continue;
         if(StringFind(line,"</Row")>=0)break;
         InputsNames+=line+",";
      }
      ParseInputVariableNames();
      ArrayResize(Rows,1,3000);
      for(int i=0; !FileIsEnding(hBack); i++)
      {
         string rowStart=FileReadString(hBack);
         if(rowStart=="<Row>")
         {
            string passCell=FileReadString(hBack);
            Rows[i].pass=(int)ExtractDataAsDouble(passCell);
            Rows[i].back_result=ExtractDataAsDouble(FileReadString(hBack));
            string profitCell=FileReadString(hBack);
            Rows[i].back_profit=ExtractDataAsDouble(profitCell);
            if(passesSeen==0 || Rows[i].back_profit>bestProfit) bestProfit=Rows[i].back_profit;
            if(passesSeen==0 || Rows[i].back_result>bestResult) bestResult=Rows[i].back_result;
            passesSeen++;
            if(!IsNumberCell(passCell) || !IsNumberCell(profitCell)) malformedSeen++;
            if(Rows[i].back_profit<0.001)
            {
               // Read on to this pass's Trades cell (the 10th): a report whose EA never
               // traded, or that cannot be read, is never taken for a tested loss.
               line="";
               for(int cell=3;cell<=9 && line!="</Row>" && !FileIsEnding(hBack);cell++) line=FileReadString(hBack);
               if(line=="</Row>" || !IsNumberCell(line)) malformedSeen++;
               else if(ExtractDataAsDouble(line)>0) tradedSeen++;
               while(line!="</Row>" && !FileIsEnding(hBack))line=FileReadString(hBack);
               i--; continue;
            }
            profitableSeen++;
            string dump=FileReadString(hBack);
            // Every cell the combined score reads must parse: an unreadable one is a
            // processing error, never a low score.
            string pfCell=FileReadString(hBack), rfCell=FileReadString(hBack), srCell=FileReadString(hBack);
            Rows[i].back_PF=ExtractDataAsDouble(pfCell);
            Rows[i].back_RF=ExtractDataAsDouble(rfCell);
            Rows[i].back_SR=ExtractDataAsDouble(srCell);
            if(!IsNumberCell(pfCell)) malformedSeen++;
            if(!IsNumberCell(rfCell)) malformedSeen++;
            if(!IsNumberCell(srCell)) malformedSeen++;
            string dump2=FileReadString(hBack);
            Rows[i].back_DD_pc=ExtractDataAsDouble(FileReadString(hBack));
            string tradesCell=FileReadString(hBack);
            Rows[i].back_trades=(int)ExtractDataAsDouble(tradesCell);
            if(!IsNumberCell(tradesCell)) malformedSeen++;
            else if(Rows[i].back_trades>0) tradedSeen++;
            if(Rows[i].back_trades<GOAT_XML_MIN_BACK_TRADES)//<=90
            {
               line="";
               while(line!="</Row>" && !FileIsEnding(hBack))line=FileReadString(hBack);
               i--;
               continue;
            }
            Rows[i].Inputs=ExtractDataFromCell(FileReadString(hBack));
            while(true)
            {
               line=FileReadString(hBack);
               if(line=="</Row>")break;
               if(FileIsEnding(hBack)) {malformedSeen++; break;}   // truncated report: never loop at EOF
               Rows[i].Inputs+=","+ExtractDataFromCell(line);
            }
            ArrayResize(Rows,ArraySize(Rows)+1,3000);
         }
         else
         {
            // A whole report ends its results table here; a truncated one never does.
            reportClosed=(StringFind(rowStart,"</Table>")>=0);
            ArrayResize(Rows,ArraySize(Rows)-1);
            // i counts kept rows only (skipped rows rewind it), so report kept/total passes.
            LogOrPrint(reportMode,"No further back <Row> Found. Rows Saved="+(string)ArraySize(Rows)+"/"+(string)passesSeen
                       +" (profitable="+(string)profitableSeen+", min trades="+(string)GOAT_XML_MIN_BACK_TRADES+")",_K,_N,_S);
            break;
         }
      }
      //LogOrPrint(reportMode,"Back XML reading end.",_K,_N,_S);
      FileClose(hBack);
      return true;
   }
//+------------------------------------------------------------------+
   bool ProcessForwardXml(const string filename)
   {
      if(ArraySize(Rows)==0)        {LogOrPrint(reportMode,"❌ "+__FUNCTION__+": No rows available from back file.",_K,_N,_S); return false;}
      int hForward=FileOpen(filename,FILE_READ|FILE_COMMON|FILE_ANSI,'\t',CP_UTF8);
      if(hForward==INVALID_HANDLE)  {LogOrPrint(reportMode,"❌ "+__FUNCTION__+": Error opening forward file: "+filename,_K,_N,_S); return false;}
      else                           LogOrPrint(reportMode,"Forward File Processing Start...",_K,_N,_S);
      string line="";
      while(!FileIsEnding(hForward))
      {
         line=FileReadString(hForward); if(line=="")continue;
         if(StringFind(line,"</Row>")>=0)break;
      }
      int discarded=0;
      forwardMatched=0; forwardMismatches=0; forwardMalformed=0; bestCombinedScore=0;
      for(int i=0; !FileIsEnding(hForward); i++)
      {
         if(FileReadString(hForward)=="<Row>")
         {
            string passCell=FileReadString(hForward);
            int pass=(int)ExtractDataAsDouble(passCell);
            if(!IsNumberCell(passCell)) forwardMalformed++;
            int bPos=GetBackPassRow(pass);
            if(bPos==-1)
            {
               line="";
               while(line!="</Row>" && !FileIsEnding(hForward))line=FileReadString(hForward);
               if(line!="</Row>") forwardMalformed++;   // truncated report: never loop at EOF
               discarded++; continue;
            }
            // A pass seen twice is not a clean merge: its forward values are overwritten.
            if(Rows[bPos].forward_seen) forwardMismatches++;
            else {Rows[bPos].forward_seen=true; forwardMatched++;}
            Rows[bPos].forward_result=ExtractDataAsDouble(FileReadString(hForward));
            double tmpBackResult=ExtractDataAsDouble(FileReadString(hForward));
            if(Rows[bPos].back_result!=tmpBackResult)
            {
               forwardMismatches++;
               LogOrPrint(reportMode,"❌ Back result mismatch in forward xml. Pass="+(string)pass,_K,_N,_S);
               //return false;
            }
            string profitCell=FileReadString(hForward);
            Rows[bPos].forward_profit=ExtractDataAsDouble(profitCell);
            string dump=FileReadString(hForward);
            string pfCell=FileReadString(hForward), rfCell=FileReadString(hForward), srCell=FileReadString(hForward);
            Rows[bPos].forward_PF=ExtractDataAsDouble(pfCell);
            Rows[bPos].forward_RF=ExtractDataAsDouble(rfCell);
            Rows[bPos].forward_SR=ExtractDataAsDouble(srCell);
            string dump2=FileReadString(hForward);
            Rows[bPos].forward_DD_pc=ExtractDataAsDouble(FileReadString(hForward));
            string tradesCell=FileReadString(hForward);
            Rows[bPos].forward_trades=(int)ExtractDataAsDouble(tradesCell);
            // Every cell the combined score reads must parse (profit, PF, RF, SR, trades).
            if(!IsNumberCell(profitCell)) forwardMalformed++;
            if(!IsNumberCell(pfCell)) forwardMalformed++;
            if(!IsNumberCell(rfCell)) forwardMalformed++;
            if(!IsNumberCell(srCell)) forwardMalformed++;
            if(!IsNumberCell(tradesCell)) forwardMalformed++;
            string Inputsforward=ExtractDataFromCell(FileReadString(hForward));
            while(true)
            {
               line=FileReadString(hForward);
               if(line=="</Row>")break;
               if(FileIsEnding(hForward)) {forwardMalformed++; break;}   // truncated report: never loop at EOF
               Inputsforward+=","+ExtractDataFromCell(line);
            }
            if(Inputsforward!=Rows[bPos].Inputs)
            {
               forwardMismatches++;
               LogOrPrint(reportMode,"❌ Inputs mismatch in back vs. forward. Pass="+(string)pass,_K,_N,_S);
               LogOrPrint(reportMode,"Forward Inputs="+Inputsforward,_K,_N,_S);
               LogOrPrint(reportMode,"Back    Inputs="+Rows[bPos].Inputs,_K,_N,_S);
               //return false;
            }
            Rows[bPos].Score=CalculateCustomScore (Rows[bPos].back_profit,Rows[bPos].forward_profit,
                                                   Rows[bPos].back_RF    ,Rows[bPos].forward_RF,
                                                   Rows[bPos].back_trades,Rows[bPos].forward_trades, startD,endD,forwardD);
                                                   
            Rows[bPos].Score=CalculateCustomScore2(Rows[bPos].back_profit,Rows[bPos].forward_profit,
                                                   Rows[bPos].back_PF    ,Rows[bPos].forward_PF,
                                                   Rows[bPos].back_RF    ,Rows[bPos].forward_RF,
                                                   Rows[bPos].back_SR    ,Rows[bPos].forward_SR,
                                                   Rows[bPos].back_trades,Rows[bPos].forward_trades, startD,endD,forwardD);
         }
         else
         {
            LogOrPrint(reportMode,"No further forward <Row> Found. Discarded="+(string)discarded+"/"+(string)i,_K,_N,_S);
            break;
         }
      }
      //LogOrPrint(reportMode,"Forward XML reading End.",_K,_N,_S);
      FileClose(hForward);
      SortRowsByScoreDescending();
      bestCombinedScore=(ArraySize(Rows)>0 ? Rows[0].Score : 0.0);
      return true;
   }
//+------------------------------------------------------------------+
   string getInputsSettingString(int rowIndex)
   {
      string rowInputVals[];
      StringSplit(RowsUnique[rowIndex].Inputs, ',', rowInputVals);
      string output="";
      int nameCount=ArraySize(m_inputVarNames), valCount=ArraySize(rowInputVals), count=MathMin(nameCount,valCount);
      for(int i=0; i<count; i++)
      {
         string piece=m_inputVarNames[i]+"="+rowInputVals[i];
         if(i==0) output=piece; else output+="\n"+piece;
      }
      return output;
   }
//+------------------------------------------------------------------+
//| WriteTopToXml – keeps first row for each unique Score ≥ minScore |
//|    up to ‘count’ rows, writes them, and populates topRowsNoDup[].|
//|    Returns # rows actually written.                              |
//+------------------------------------------------------------------+
int WriteTopToXml(const string xmlFileName,int count = 100,double minScore = 70.0)
  {
   const double EPS = 1e-6;
   int total = ArraySize(Rows);
   if(total == 0) {LogOrPrint(reportMode,"❌ "+__FUNCTION__+": No Rows!",_K,_N,_S); return(0);}
   /*-- clear the buffer that the next routine will read --*/
   ArrayResize(topRowsNoDup,0);
   /*-- open output file --*/
   int fh = FileOpen(xmlFileName, FILE_WRITE|FILE_TXT|FILE_COMMON);
   if(fh < 1)     {LogOrPrint(reportMode,"❌ "+__FUNCTION__+": cannot open: "+xmlFileName,_K,_N,_S); return(0);}
   /*-- header --*/
   FileWriteString(fh,metadataWithWorkbookStart+"\n");
   FileWriteString(fh,DocumentProperties+"\n");
   FileWriteString(fh,WorksheetLine+"\n");
   FileWriteString(fh,"<Table>\n  <Row>\n");
   const string hdr[] = {"Pass","Score","Result(Back)","Result(Forward)","Trades(Back)","Trades(Forward)","Profit(Back)","Profit(Forward)","PF(Back)","PF(Forward)"
                                                                    ,"RF(Back)","RF(Forward)","SR(Back)","SR(Forward)","DD(Back)","DD(Forward)"};
   for(int h=0; h<ArraySize(hdr); ++h)             FileWriteString(fh,"    <Cell><Data ss:Type=\"String\">"+hdr[h]+"</Data></Cell>\n");
   for(int i=0; i<ArraySize(m_inputVarNames); ++i) FileWriteString(fh,"    <Cell><Data ss:Type=\"String\">"+m_inputVarNames[i]+"</Data></Cell>\n");
   FileWriteString(fh,"  </Row>\n");

   double lastScore = DBL_MAX;
   int written = 0;

   for(int i=0; i<total && written<count; ++i)
     {
      double s = Rows[i].Score;
      if(s < minScore) break;
      if(MathAbs(s - lastScore) < EPS) continue;   // duplicate score

      FileWriteString(fh,"  <Row>\n");
      WriteNumberCell(fh,Rows[i].pass);           WriteNumberCell(fh,s);
      WriteNumberCell(fh,Rows[i].back_result);    WriteNumberCell(fh,Rows[i].forward_result);
      WriteNumberCell(fh,Rows[i].back_trades);    WriteNumberCell(fh,Rows[i].forward_trades);
      WriteNumberCell(fh,Rows[i].back_profit);    WriteNumberCell(fh,Rows[i].forward_profit);
      WriteNumberCell(fh,Rows[i].back_PF);        WriteNumberCell(fh,Rows[i].forward_PF);
      WriteNumberCell(fh,Rows[i].back_RF);        WriteNumberCell(fh,Rows[i].forward_RF);
      WriteNumberCell(fh,Rows[i].back_SR);        WriteNumberCell(fh,Rows[i].forward_SR);
      WriteNumberCell(fh,Rows[i].back_DD_pc);     WriteNumberCell(fh,Rows[i].forward_DD_pc);

      string inVals[]; StringSplit(Rows[i].Inputs,',',inVals);
      for(int k=0;k<ArraySize(inVals);++k)  if(inVals[k]!="") WriteNumberCell(fh,StringToDouble(inVals[k]));
      FileWriteString(fh,"  </Row>\n");

      int p = ArraySize(topRowsNoDup);  ArrayResize(topRowsNoDup,p+1);
      topRowsNoDup[p] = Rows[i];
      lastScore = s; ++written;
     }
   FileWriteString(fh,"</Table>\n</Worksheet>\n</Workbook>\n"); FileClose(fh);
   LogOrPrint(reportMode,__FUNCTION__+": wrote "+(string)written+" distinct row(s) (Score≥"+DoubleToString(minScore,0)+") to "+FileNameOnly(xmlFileName),_K,_N,_S);
   return(written);
  }
 /*void WriteTopToXml(const string xmlFileName,int count=100)
   {
      int total=ArraySize(Rows); if(total<2){Print(__FUNCTION__,": No data available in Rows[]");return;}
      int handle=FileOpen(xmlFileName,FILE_WRITE|FILE_TXT|FILE_COMMON);
      if(handle<1){Print(__FUNCTION__,": Failed to open XML file: ",xmlFileName);return;}
      FileWriteString(handle,metadataWithWorkbookStart+"\n");
      FileWriteString(handle,DocumentProperties+"\n");
      FileWriteString(handle,WorksheetLine+"\n");
      FileWriteString(handle,"<Table>\n");
      FileWriteString(handle,"  <Row>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">Pass</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">Score</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">Result(Back)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">Result(Forward)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">Trades(Back)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">Trades(Forward)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">Profit(Back)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">Profit(Forward)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">PF(Back)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">PF(Forward)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">RF(Back)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">RF(Forward)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">SR(Back)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">SR(Forward)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">DD(Back)</Data></Cell>\n");
      FileWriteString(handle,"    <Cell><Data ss:Type=\"String\">DD(Forward)</Data></Cell>\n");
      for(int i=0;i<ArraySize(m_inputVarNames);i++)
      {
         string hdr="    <Cell><Data ss:Type=\"String\">"+m_inputVarNames[i]+"</Data></Cell>\n";
         FileWriteString(handle,hdr);
      }
      FileWriteString(handle,"  </Row>\n");
      int limit=MathMin(count,total);
      for(int i=0;i<limit;i++)
      {
         FileWriteString(handle,"  <Row>\n");
         WriteNumberCell(handle,Rows[i].pass);
         WriteNumberCell(handle,Rows[i].Score);
         WriteNumberCell(handle,Rows[i].back_result);
         WriteNumberCell(handle,Rows[i].forward_result);
         WriteNumberCell(handle,Rows[i].back_trades);
         WriteNumberCell(handle,Rows[i].forward_trades);
         WriteNumberCell(handle,Rows[i].back_profit);
         WriteNumberCell(handle,Rows[i].forward_profit);
         WriteNumberCell(handle,Rows[i].back_PF);
         WriteNumberCell(handle,Rows[i].forward_PF);
         WriteNumberCell(handle,Rows[i].back_RF);
         WriteNumberCell(handle,Rows[i].forward_RF);
         WriteNumberCell(handle,Rows[i].back_SR);
         WriteNumberCell(handle,Rows[i].forward_SR);
         WriteNumberCell(handle,Rows[i].back_DD_pc);
         WriteNumberCell(handle,Rows[i].forward_DD_pc);
         string rowInputVals[]; StringSplit(Rows[i].Inputs,',',rowInputVals);
         for(int k=0;k<ArraySize(rowInputVals);k++)
         {
            if(rowInputVals[k]!="")
            {
               double val=StringToDouble(rowInputVals[k]);
               WriteNumberCell(handle,val);
            }
         }
         FileWriteString(handle,"  </Row>\n");
      }
      FileWriteString(handle,"</Table>\n</Worksheet>\n</Workbook>\n");
      FileClose(handle);
      Print("Top ",limit," rows written to ",xmlFileName);
   }*/
//+------------------------------------------------------------------+
// Global helper function to compute Euclidean distance between two row vectors
//+------------------------------------------------------------------+
double Distance(const double &featureVectors[][], int dim, int idxA, int idxB)
  {
   double sumSq = 0.0;
   for(int d = 0; d < dim; d++)
     {
      double diff = featureVectors[idxA][d] - featureVectors[idxB][d];
      sumSq += diff * diff;
     }
   return MathSqrt(sumSq);
  }
//+------------------------------------------------------------------+
//| Global helper function to select rows whose distance is above a  |
//| given threshold. The resulting indices are stored in the output  |
//| array selIdx.                                                    |
// Greedy selection with "rejected-prototype" cache
//------------------------------------------------------------------
void SelectRows(const double &fv[][],          // normalised vectors
                int   limit,
                int   dim,
                double thr,
                int  &selIdx[],               // <- selected rows (OUT)
                int  &rejIdx[])               // <- rejected prototypes (OUT)
{
   ArrayResize(selIdx,0);   // make sure both arrays are empty
   ArrayResize(rejIdx,0);

   for(int i=0;i<limit;i++)
   {
      bool isFar = true;
      // 1) compare to rows we've already kept
      for(int s=0; s<ArraySize(selIdx); s++)
         if(Distance(fv,dim,i,selIdx[s]) < thr) { isFar = false; break; }
      // 2) compare to the prototypes we rejected earlier
      if(isFar)
         for(int r=0; r<ArraySize(rejIdx); r++)
            if(Distance(fv,dim,i,rejIdx[r]) < thr) { isFar = false; break; }
      if(isFar)   // --- keep it -----------------------------------
      {
         int pos = ArraySize(selIdx);
         ArrayResize(selIdx,pos+1);           // enlarge by one element
         selIdx[pos] = i;                     // write new index
      }
      else        // --- remember as prototype ---------------------
      {
         int pos = ArraySize(rejIdx);
         ArrayResize(rejIdx,pos+1);
         rejIdx[pos] = i;
      }
   }
}
//+------------------------------------------------------------------+
//| WriteUniqueRowsToXml                                             |
//| Picks unique rows from top_count (sorted by Score) by applying   |
//| a distance threshold. If distance_threshold <= 0, it auto-finds  |
//| an internal threshold to yield wanted_count picks. Writes them   |
//| to an XML file with same columns as WriteTopToXml().             |
//+------------------------------------------------------------------+
bool WriteUniqueRowsToXml(const string xmlFileName,int top_count = 100,int wanted_count = 25,double distance_threshold = 0.0)
  {
   /* 0) source data */
   int total = ArraySize(topRowsNoDup);
   if(total == 0) { LogOrPrint(reportMode,"❌ "+__FUNCTION__+": No Rows!",_K,_N,_S); return false; }

   int limit = MathMin(top_count, total);
   wanted_count = MathMin(wanted_count, limit);      // can’t ask for more than we have
   /* 1)  build feature matrix ------------------------------------------------*/
   const int perfCount  = 14;
   const int inputCount = ArraySize(m_inputVarNames);
   const int dim        = perfCount + inputCount;
   if(dim > 99) { LogOrPrint(reportMode,"❌ "+__FUNCTION__+": too many dimensions ("+(string)dim+") – reduce inputs",_K,_N,_S); return false; }

   double fv[][99];  ArrayResize(fv, limit);
   double cMin[], cMax[]; ArrayResize(cMin,dim); ArrayResize(cMax,dim);
   ArrayInitialize(cMin, DBL_MAX); ArrayInitialize(cMax, -DBL_MAX);

   for(int i=0;i<limit;++i)
     {
      double v[]; ArrayResize(v,dim);
      const SRowDefinition R = topRowsNoDup[i];
      v[ 0] = R.back_result;  v[ 1] = R.forward_result;
      v[ 2] = R.back_trades;  v[ 3] = R.forward_trades;
      v[ 4] = R.back_profit;  v[ 5] = R.forward_profit;
      v[ 6] = R.back_PF;      v[ 7] = R.forward_PF;
      v[ 8] = R.back_RF;      v[ 9] = R.forward_RF;
      v[10] = R.back_SR;      v[11] = R.forward_SR;
      v[12] = R.back_DD_pc;   v[13] = R.forward_DD_pc;

      string inVals[]; StringSplit(R.Inputs,',',inVals);
      for(int k=0;k<inputCount;++k)
         v[perfCount+k] = (k<ArraySize(inVals)) ? StringToDouble(inVals[k]) : 0.0;
      /* copy + min/max */
      for(int d=0; d<dim; ++d)
        {
         fv[i][d] = v[d];
         if(v[d] < cMin[d]) cMin[d]=v[d];
         if(v[d] > cMax[d]) cMax[d]=v[d];
        }
     }
   /* 2)  min-max normalise */
   for(int d=0; d<dim; ++d)
     {
      double range = cMax[d]-cMin[d];
      if(MathAbs(range)<1e-12) { for(int i=0;i<limit;++i) fv[i][d]=0.0; continue; }
      for(int i=0;i<limit;++i) fv[i][d] = (fv[i][d]-cMin[d]) / range;
     }
   /* 3)  greedy diversity pick */
   int sel[], rej[];
   double useThr = distance_threshold;

   if(distance_threshold>0.0) SelectRows(fv,limit,dim,distance_threshold,sel,rej);
   else{
      double lo=0.0, hi=MathSqrt(dim);
      for(int it=0; it<15; ++it)
        {
         double mid=0.5*(lo+hi);
         int tmpSel[], tmpRej[];
         SelectRows(fv,limit,dim,mid,tmpSel,tmpRej);
         if(ArraySize(tmpSel)>=wanted_count) lo=mid; else hi=mid;
        }
      useThr = 0.5*(lo+hi);
      SelectRows(fv,limit,dim,useThr,sel,rej);
     }
   if(ArraySize(sel) > wanted_count) ArrayResize(sel,wanted_count);
   int finalCnt = ArraySize(sel);
   if(finalCnt == 0) { LogOrPrint(reportMode,"❌ "+__FUNCTION__+": selector returned 0 rows",_K,_N,_S); return false; }
   /* 4) expose via RowsUnique[] for caller convenience */
   ArrayResize(RowsUnique, finalCnt);
   for(int i=0;i<finalCnt;++i) RowsUnique[i] = topRowsNoDup[ sel[i] ];
   /* 5)  write xml ----------------------------------------------------------*/
   int fh = FileOpen(xmlFileName, FILE_WRITE|FILE_TXT|FILE_COMMON);
   if(fh<1){ LogOrPrint(reportMode,"❌ "+__FUNCTION__+": cannot open: "+xmlFileName,_K,_N,_S); return false; }

   FileWriteString(fh,metadataWithWorkbookStart+"\n");
   FileWriteString(fh,DocumentProperties+"\n");
   FileWriteString(fh,WorksheetLine+"\n");
   FileWriteString(fh,"<Table>\n  <Row>\n");

   const string hdrU[] =
     {"Pass","Score","Result(Back)","Result(Forward)",
      "Trades(Back)","Trades(Forward)","Profit(Back)","Profit(Forward)",
      "PF(Back)","PF(Forward)","RF(Back)","RF(Forward)",
      "SR(Back)","SR(Forward)","DD(Back)","DD(Forward)"};

   for(int h=0;h<ArraySize(hdrU);++h) FileWriteString(fh,"    <Cell><Data ss:Type=\"String\">"+hdrU[h]+"</Data></Cell>\n");
   
   for(int c=0;c<inputCount;++c)    FileWriteString(fh,"    <Cell><Data ss:Type=\"String\">"+m_inputVarNames[c]+"</Data></Cell>\n");
   FileWriteString(fh,"  </Row>\n");

   for(int n=0;n<finalCnt;++n)
     {
      const SRowDefinition R = topRowsNoDup[ sel[n] ];
      FileWriteString(fh,"  <Row>\n");
      WriteNumberCell(fh,R.pass);             WriteNumberCell(fh,R.Score);
      WriteNumberCell(fh,R.back_result);      WriteNumberCell(fh,R.forward_result);
      WriteNumberCell(fh,R.back_trades);      WriteNumberCell(fh,R.forward_trades);
      WriteNumberCell(fh,R.back_profit);      WriteNumberCell(fh,R.forward_profit);
      WriteNumberCell(fh,R.back_PF);          WriteNumberCell(fh,R.forward_PF);
      WriteNumberCell(fh,R.back_RF);          WriteNumberCell(fh,R.forward_RF);
      WriteNumberCell(fh,R.back_SR);          WriteNumberCell(fh,R.forward_SR);
      WriteNumberCell(fh,R.back_DD_pc);       WriteNumberCell(fh,R.forward_DD_pc);

      string inVals[];  StringSplit(R.Inputs,',',inVals);
      for(int k=0;k<ArraySize(inVals);++k) if(inVals[k]!="") WriteNumberCell(fh,StringToDouble(inVals[k]));
      FileWriteString(fh,"  </Row>\n");
     }
   FileWriteString(fh,"</Table>\n</Worksheet>\n</Workbook>\n"); FileClose(fh);
   LogOrPrint(reportMode,__FUNCTION__+": "+(string)finalCnt+" unique rows written to "+FileNameOnly(xmlFileName),_K,_N,_S);
   LogOrPrint(reportMode,__FUNCTION__+": threshold distance="+DoubleToString(useThr,3),_K,_N,_S);
   return true;
  }
//+------------------------------------------------------------------+
double CalculateCustomScore(double backProfit,double forwardProfit,
                            double backRecoveryFactor,double forwardRecoveryFactor,
                            int backTrades,int forwardTrades,
                            datetime startDate,datetime endDate,datetime forwardDate)
   {
      if((backTrades+forwardTrades)<70) return(0.0);
      if(forwardProfit<=0.0) return(0.0);

      double totalProfit=backProfit+forwardProfit;
      double worstDrawdown=MathMax((backRecoveryFactor==0.0?0.0:backProfit/backRecoveryFactor),(forwardRecoveryFactor==0.0?0.0:forwardProfit/forwardRecoveryFactor));
      double scoreMultiplier=0.0;if(worstDrawdown!=0.0)scoreMultiplier=totalProfit/worstDrawdown;
      double startDbl=(double)startDate, endDbl=(double)endDate, fwdDbl=(double)forwardDate;
      double timeRatio=0.0, denomTime=(endDbl-fwdDbl); if(denomTime!=0.0)timeRatio=(fwdDbl-startDbl)/denomTime;
      double profitMatchRatio=0.0;
      if(backProfit!=0.0&&timeRatio!=0.0)
      {
         double ratioPart=forwardProfit/(backProfit/timeRatio);
         profitMatchRatio=(1.0-MathAbs(1.0-ratioPart))*100.0;
      }
      double scoreMultiplierr=0.0;if(scoreMultiplier>0.0)scoreMultiplierr=(MathLog(scoreMultiplier)/MathLog(4.0))*100.0*0.2;
      double profitMatchWeight=profitMatchRatio*0.6;
      double backProfitRatio=(backRecoveryFactor!=0.0?backProfit/backRecoveryFactor:0.0);
      double forwardProfitRatio=(forwardRecoveryFactor!=0.0?forwardProfit/forwardRecoveryFactor:0.0);
      double recoveryFactorMatchRatio=0.0, denomRF=(forwardProfitRatio+backProfitRatio);
      if(denomRF!=0.0)recoveryFactorMatchRatio=(1.0-MathAbs((forwardProfitRatio-backProfitRatio)/denomRF))*100.0*0.1;
      double tradesMatchRatio=0.0;
      if(backTrades!=0&&timeRatio!=0.0)
      {
         double tradesScaled=(double)backTrades/timeRatio;
         if(tradesScaled!=0.0)
         {
            double tradesPart=(double)forwardTrades/tradesScaled;
            tradesMatchRatio=(1.0-MathAbs(1.0-tradesPart))*100.0*0.1;
         }
      }
      double customScore=profitMatchWeight+scoreMultiplierr+recoveryFactorMatchRatio+tradesMatchRatio;
      return(customScore);
   }
//+------------------------------------------------------------------+
//|  Extended “back + forward” quality score                          |
//|  – keeps all v2 terms (multiplier, profit-match, RF-match, trades-match)                                                  |
//|  – adds new PF-match & SR-match                                   |
//|  – weights rebased so the total = 100                             |
//+------------------------------------------------------------------+
double  CalculateCustomScore2(                 // 0-100 scaled total
                double  backProfit,   double  forwardProfit,
                double  backPF,       double  forwardPF,          // NEW
                double  backRecoveryFactor,   double  forwardRecoveryFactor,
                double  backSR,       double  forwardSR,          // NEW
                int     backTrades,   int     forwardTrades,
                datetime startDate,   datetime endDate,datetime forwardDate)
  {
   /*––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
     0.  guards
   ­––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––*/
   if((backTrades+forwardTrades)<50)   return(0.0);
   if(forwardProfit<=0.0)              return(0.0);
   /*––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
     1.  risk-adjusted PROFIT (‘multiplier’) – unweighted
   ­––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––*/
   double totalProfit   = backProfit + forwardProfit;
   double worstDD       = MathMax( (backRecoveryFactor   ==0.0 ? 0.0 : backProfit   / backRecoveryFactor),
                                   (forwardRecoveryFactor==0.0 ? 0.0 : forwardProfit / forwardRecoveryFactor));
   double scoreMult = 0.0;  // 0-100
   if(worstDD>0.0)
     {
      double m = totalProfit / worstDD;          // risk-adjusted return
      if(m>0.0)  scoreMult = ( MathLog(m) / MathLog(4.0) ) * 100.0;   // log4(m) ×100
     }
   scoreMult = MathMax(scoreMult,0.0);
   /*––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
     2.  time ratio  &  PROFIT-match – unweighted
   ­––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––*/
   double timeRatio = 0.0;
   double denomTime = double(endDate) - double(forwardDate);
   if(denomTime!=0.0) timeRatio = (double(forwardDate) - double(startDate)) / denomTime;

   double profitMatch = 0.0;                     // 0-100
   if(backProfit!=0.0 && timeRatio!=0.0)
     {
      double ratioPart = forwardProfit / (backProfit / timeRatio);
      profitMatch = (1.0 - MathAbs(1.0 - ratioPart)) * 100.0;
     }
   profitMatch = MathMin(MathMax(profitMatch,0.0),100);
   /*––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
     3.  PROFIT-FACTOR match – NEW – unweighted
   ­––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––*/
   double pfMatch = 0.0;                          // 0-100
   if(backPF>0.0) pfMatch = (1.0 - MathAbs(1.0 - forwardPF / backPF)) * 100.0;
   pfMatch = MathMin(MathMax(pfMatch,0.0),100);
   /*––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
     4.  RECOVERY-FACTOR match
   ­––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––*/
   double backProfitRatio    = (backRecoveryFactor   !=0.0 ? backProfit   / backRecoveryFactor  : 0.0);
   double forwardProfitRatio = (forwardRecoveryFactor!=0.0 ? forwardProfit/ forwardRecoveryFactor: 0.0);

   double rfMatch = 0.0;                           // 0-100
   double denomRF = forwardProfitRatio + backProfitRatio;
   if(denomRF!=0.0)  rfMatch = (1.0 - MathAbs((forwardProfitRatio - backProfitRatio)/denomRF)) * 100.0;
   rfMatch = MathMin(MathMax(rfMatch,0.0),100);
   /*––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
     5.  SHARPE-RATIO match – NEW – unweighted
   ­––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––*/
   double srMatch = 0.0;                           // 0-100
   if(backSR>0.0) srMatch = (1.0 - MathAbs(1.0 - forwardSR / backSR)) * 100.0;
   srMatch = MathMin(MathMax(srMatch,0.0),100);
   /*––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
     6.  TRADES-match – unweighted
   ­––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––*/
   double tradesMatch = 0.0;                       // 0-100
   if(backTrades!=0 && timeRatio!=0.0)
     {
      double tradesScaled=double(backTrades)/timeRatio;
      if(tradesScaled!=0.0)
        {
         double tradesPart = double(forwardTrades) / tradesScaled;
         tradesMatch = (1.0 - MathAbs(1.0 - tradesPart)) * 100.0;
        }
     }
    tradesMatch = MathMin(MathMax(tradesMatch,0.0),100);
   /*––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
     7.  WEIGHTED blend  (rebased to 100)
   ­––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––*/
   double customScore =
        profitMatch *0.40 +
        scoreMult   *0.20 +
        pfMatch     *0.10 +
        rfMatch     *0.10 +
        srMatch     *0.05 +
        tradesMatch *0.15;
   /*––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––
     8.  linear deterioration for low trade count
   ­––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––––*/
   double tradeScale = MathMin(double(backTrades+forwardTrades+100)/200.0,1.0);
   return(customScore * tradeScale);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
//+------------------------------------------------------------------+
string StringTrim(string str) {StringTrimLeft(str); StringTrimRight(str); return str;}
//+------------------------------------------------------------------+
   bool ExtractForwardDate(const string text,datetime &forwardDate)
   {
    // 1. Locate the '(' and ')' characters in the string
    int openPos=StringFind(text,"(");
    if(openPos<0) return false;
    int closePos=StringFind(text,")",openPos+1);
    if(closePos<0) return false;
    // 2. Extract the substring inside the parentheses
    int len=closePos-openPos-1; // number of chars between '(' and ')'
    if(len!=10) return false;   // must match YYYY.MM.DD length
    string dateStr=StringSubstr(text,openPos+1,len);
    // 3. Minimal format checks for 'YYYY.MM.DD'
    if(dateStr[4]!='.' || dateStr[7]!='.') return false;
    // 4. Convert to datetime and validate
    datetime dt=StringToTime(dateStr);
    if(dt==0) return false;
    // 5. Success: assign and return
    forwardDate=dt;
    return true;
   }
//+------------------------------------------------------------------+
//| Extract "<SYMBOL>,<TF>" token that stands just before date range |
//| Return true on success                                           |
//+------------------------------------------------------------------+
bool ExtractSymbolTfFromTitle(const string &title,
                              string &sym,
                              string &tf)
{
   string tokens[];                           // split on spaces
   int n = StringSplit(title,' ',tokens);
   if(n < 3) return false;                    // we expect "... <SYM,TF> <DATE‑FROM>..."
   
   string sym_tf = tokens[n-2];               // "... EURCADp,M1 2024.10.01-..."
   
   string p[];                               // split on comma to get symbol / tf
   if(StringSplit(sym_tf,',',p) != 2) return false;
   
   sym = p[0];
   tf  = p[1];
   return true;
}
//+------------------------------------------------------------------+
//| Research outcome of the last back report (see ReportAnalyzer-    |
//| Combiner). key=value pairs for item_stats.tsv; the tested window |
//| is always stated, so "no edge here" never reads as "never works".|
//+------------------------------------------------------------------+
string OutcomeDetails(void)
  {
   string details="outcome="+outcome+";passes="+(string)passesSeen+";profitable="+(string)profitableSeen
          +";traded="+(string)tradedSeen+";malformed="+(string)malformedSeen+";complete="+(reportClosed ? "1" : "0")
          +";forward_rows="+(string)forwardRows
          +";best_profit="+DoubleToString(bestProfit,2)+";best_score="+DoubleToString(bestResult,4)
          +";min_trades="+(string)GOAT_XML_MIN_BACK_TRADES+";window_start="+TimeToString(startD,TIME_DATE)
          +";window_end="+TimeToString(forwardD,TIME_DATE)+";forward_end="+TimeToString(endD,TIME_DATE);
   // Kept passes were merged with the forward report: say how many, and how far the best one fell short.
   if(outcome==GOAT_XML_NO_QUALIFYING_ROWS)
      details+=";back_rows="+(string)ArraySize(Rows)+";forward_matched="+(string)forwardMatched
               +";forward_discarded="+(string)(forwardRows-forwardMatched)+";forward_mismatches="+(string)forwardMismatches
               +";forward_malformed="+(string)forwardMalformed+";best_combined_score="+DoubleToString(bestCombinedScore,1)
               +";score_threshold="+DoubleToString(GOAT_XML_MIN_COMBINED_SCORE,1);
   return details;
  }
string OutcomeWindow(void)
  {
   return TimeToString(startD,TIME_DATE)+" to "+TimeToString(forwardD,TIME_DATE);
  }
string OutcomeSentence(void)
  {
   if(pairOutcome==GOAT_XML_NO_QUALIFYING_ROWS)
      return "Tested "+(string)passesSeen+" settings on "+symbol_+" "+TF_+" in "+OutcomeWindow()
             +": "+(string)ArraySize(Rows)+" "+(ArraySize(Rows)==1 ? "was" : "were")+" profitable with "+(string)GOAT_XML_MIN_BACK_TRADES
             +"+ trades in-sample but none scored "+DoubleToString(GOAT_XML_MIN_COMBINED_SCORE,0)+"+ once the forward period to "
             +TimeToString(endD,TIME_DATE)+" was included (best "+DoubleToString(bestCombinedScore,1)+(bestCombinedScore<=0 ? ": the forward period scored zero" : "")+"). A result for this window, not an error.";
   return "Tested "+(string)passesSeen+" settings on "+symbol_+" "+TF_+" in "+OutcomeWindow()
          +": none was profitable with "+(string)GOAT_XML_MIN_BACK_TRADES+"+ trades ("+(profitableSeen>0 ? (string)profitableSeen+" profitable on fewer, " : "")
          +"best profit "+DoubleToString(bestProfit,2)+"). A result for this window, not an error.";
  }
// Data rows in a forward report, or -1 when it cannot be read or its table never closed.
int ForwardReportRows(const string filename)
  {
   int h=FileOpen(filename,FILE_READ|FILE_COMMON|FILE_ANSI,'\t',CP_UTF8);
   if(h==INVALID_HANDLE) return -1;
   int rows=0; bool table_closed=false;
   while(!FileIsEnding(h))
     {
      string line=FileReadString(h);
      if(line=="<Row>") rows++;
      else if(StringFind(line,"</Table>")>=0) {table_closed=true; break;}
     }
   FileClose(h);
   return (table_closed && rows>0) ? rows-1 : -1;   // the first row is the header
  }
//+------------------------------------------------------------------+
private:
   // A Number cell whose text is strictly a decimal number ([+-]digits[.digits][e[+-]digits]).
   // ExtractDataAsDouble turns anything else into 0.0, which must never pass for a result.
   bool IsNumberCell(const string cell)
   {
      string tag="ss:Type=\"Number\">";
      int start=StringFind(cell,tag); if(start<0) return false;
      start+=StringLen(tag);
      int end=StringFind(cell,"</Data>",start); if(end<0) return false;
      string text=StringSubstr(cell,start,end-start);
      StringTrimLeft(text); StringTrimRight(text);
      int n=StringLen(text), digits=0, expDigits=0, dots=0, exps=0;
      for(int k=0;k<n;k++)
      {
         ushort ch=StringGetCharacter(text,k);
         if(ch>='0' && ch<='9') {if(exps>0) expDigits++; else digits++;}
         else if(ch=='.') {if(dots>0 || exps>0) return false; dots++;}
         else if(ch=='e' || ch=='E') {if(exps>0 || digits==0) return false; exps++;}
         else if(ch=='+' || ch=='-')
         {
            if(k==0) continue;
            ushort prev=StringGetCharacter(text,k-1);
            if(prev!='e' && prev!='E') return false;
         }
         else return false;
      }
      return digits>0 && (exps==0 || expDigits>0);
   }
   int GetBackPassRow(int Forward_pass)
   {
      for(int i=0;i<ArraySize(Rows);i++)
         if(Rows[i].pass==Forward_pass)return i;
      return -1;
   }
   double ExtractDataAsDouble(const string cell_string)
   {
      string start_tag="ss:Type=\"Number\">";
      int start_pos=StringFind(cell_string,start_tag,0);
      if(start_pos==-1)return(0.0);
      start_pos+=StringLen(start_tag);
      int end_pos=StringFind(cell_string,"</Data>",start_pos);
      if(end_pos==-1)return(0.0);
      string numeric_str=StringSubstr(cell_string,start_pos,end_pos-start_pos);
      StringTrimLeft(numeric_str); StringTrimRight(numeric_str);
      return(StringToDouble(numeric_str));
   }
   string ExtractDataFromCell(const string cell_string)
   {
      string start_tag="ss:Type=\"Number\">";
      if(StringFind(cell_string,"String")>=0)start_tag="ss:Type=\"String\">";
      int start_pos=StringFind(cell_string,start_tag,0);
      if(start_pos==-1)return("");
      start_pos+=StringLen(start_tag);
      int end_pos=StringFind(cell_string,"</Data>",start_pos);
      if(end_pos==-1)return("");
      string result=StringSubstr(cell_string,start_pos,end_pos-start_pos);
      StringTrimLeft(result); StringTrimRight(result);
      return(result);
   }
   bool ExtractTitleFromDocument(const string docText,string &outTitle)
   {
    int start=StringFind(docText,"<Title>"); if(start==-1)return false; start+=7;
    int end=StringFind(docText,"</Title>",start); if(end==-1)return false;
    outTitle=StringSubstr(docText,start,end-start);
    return true;
   }
   bool ExtractDatesFromTitle(const string text,datetime &dateStart,datetime &dateEnd)
   {
    int dashPos=-1,searchPos=0,pos;
    while(true)
    {
     pos=StringFind(text,"-",searchPos); if (pos<0) break;
     dashPos=pos; searchPos=pos+1;
    }
    if (dashPos==-1) return false;
    if (dashPos<10) return false;
    if (dashPos+10>StringLen(text)-1) return false;
    string s1=StringSubstr(text,dashPos-10,10), s2=StringSubstr(text,dashPos+1,10);
    if (s1[4]!='.'||s1[7]!='.'||s2[4]!='.'||s2[7]!='.') return false;
    datetime d1=StringToTime(s1), d2=StringToTime(s2);
    if (d1==0||d2==0) return false;
    dateStart=d1; dateEnd=d2; return true;
   }
  /*bool ExtractDatesFromTitle2(const string title,datetime &dateStart,datetime &dateEnd)
   {
    int spacePos=StringFind(title," "); if(spacePos==-1)return false;
    string dateRange=StringSubstr(title,spacePos+1); if(StringLen(dateRange)<10)return false;
    int dashPos=StringFind(dateRange,"-"); if(dashPos==-1)return false;
    datetime tmpStart=StringToTime(StringSubstr(dateRange,0,dashPos)),tmpEnd=StringToTime(StringSubstr(dateRange,dashPos+1));
    if(tmpStart==0||tmpEnd==0)return false; dateStart=tmpStart; dateEnd=tmpEnd; return true;
   }
   bool ExtractDatesFromTitle3(const string title,datetime &dateStart,datetime &dateEnd)
   {
      int pos=StringFind(title,"M1 "); if(pos==-1)return(false); pos+=3;
      int endPos=StringFind(title,"</Title>",pos); if(endPos==-1)return(false);
      string dateRange=StringSubstr(title,pos,endPos-pos);
      int dashPos=StringFind(dateRange,"-"); if(dashPos==-1)return(false);
      string strStart=StringSubstr(dateRange,0,dashPos), strEnd=StringSubstr(dateRange,dashPos+1);
      datetime tmpStart=StringToTime(strStart), tmpEnd=StringToTime(strEnd);
      if(tmpStart==0||tmpEnd==0)return(false);
      dateStart=tmpStart; dateEnd=tmpEnd; return(true);
   }
   bool ExtractDatesFromTitle4(const string text,datetime &dateStart,datetime &dateEnd)
   {
    int dash=StringFind(text,"-"); if(dash==-1)return(false);
    if(dash<10 || dash+10>StringLen(text))return(false);
    string s1=StringSubstr(text,dash-10,10), s2=StringSubstr(text,dash+1,10);
    // minimal dot-position check (YYYY.MM.DD)
    if(s1[4]!='.'||s1[7]!='.'||s2[4]!='.'||s2[7]!='.')return(false);
    datetime d1=StringToTime(s1),d2=StringToTime(s2);
    if(d1==0 || d2==0)return(false);
    dateStart=d1; dateEnd=d2; return(true);
   }*/
   void ParseInputVariableNames()
   {
      string Lines[]; StringSplit(InputsNames,',',Lines);
      for(int i=0;i<ArraySize(Lines);i++)
      {
         if(Lines[i]=="")continue;
         string extracted=ExtractDataFromCell(Lines[i]);
         if(extracted!="")
         {
            int sz=ArraySize(m_inputVarNames);
            ArrayResize(m_inputVarNames,sz+1);
            m_inputVarNames[sz]=extracted;
         }
      }
   }
   void SortRowsByScoreDescending()
   {
      int n=ArraySize(Rows); if(n<2)return;
      for(int i=0;i<n-1;i++)
         for(int j=i+1;j<n;j++)
            if(Rows[j].Score>Rows[i].Score)
            {
               SRowDefinition temp=Rows[i];
               Rows[i]=Rows[j];
               Rows[j]=temp;
            }
   }
   void WriteNumberCell(const int fileHandle,double val)
   {
      string cell="    <Cell><Data ss:Type=\"Number\">"+DoubleToString(val,2)+"</Data></Cell>\n";
      FileWriteString(fileHandle,cell);
   }
   void ResetData()
   {
      ArrayResize(Rows,0); ArrayResize(topRowsNoDup,0); ArrayResize(RowsUnique,0);
      metadataWithWorkbookStart=""; DocumentProperties=""; WorksheetLine="";
      InputsNames=""; startD=endD=0; ArrayResize(m_inputVarNames,0);
      passesSeen=0; profitableSeen=0; bestProfit=0; bestResult=0;
      tradedSeen=0; malformedSeen=0; reportClosed=false;
      forwardMatched=0; forwardMismatches=0; forwardMalformed=0; bestCombinedScore=0; pairOutcome="";
   }
};
//----------------------------------------------------------------------------------------------------------------------------------------------------
SXmlData xmlData;
//----------------------------------------------------------------------------------------------------------------------------------------------------
// A pair is tested without edge only when its back report was read whole (table
// closed, every row parsed), matches its file name, has a known back/forward window,
// at least one pass really traded, none was kept (profitable with enough trades), and
// its forward report is whole with no more rows than back passes. A report whose EA
// never traded, that cannot be read, or that is partial stays an error and is retried.
#define GOAT_XML_NO_PROFITABLE_PASSES "no_profitable_passes"
string GoatXmlResearchOutcome(const bool back_read,const bool title_matches,const datetime window_start,
                              const datetime forward_date,const datetime window_end,const int passes,const int kept,
                              const int traded,const int malformed,const bool report_closed,const int forward_rows)
  {
   if(!back_read || !title_matches) return "";
   if(window_start<=0 || forward_date<=window_start || window_end<=forward_date) return "";
   if(passes<=0 || kept!=0) return "";
   if(!report_closed || malformed!=0) return "";
   if(traded<=0 || traded>passes) return "";
   if(forward_rows<=0 || forward_rows>passes) return "";
   return GOAT_XML_NO_PROFITABLE_PASSES;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
// A pair is tested with nothing qualified only when the same whole-report proof holds,
// at least one pass was kept (profitable with enough trades), the forward report was
// read whole and every kept pass was found in it exactly once with matching back
// values and inputs, and the best combined score is below the export score. A forward
// report that is partial, unreadable, or disagrees with the back report stays an error.
string GoatXmlNoQualifierOutcome(const bool back_read,const bool title_matches,const datetime window_start,
                                 const datetime forward_date,const datetime window_end,const int passes,const int kept,
                                 const int profitable,const int traded,const int malformed,const bool report_closed,
                                 const int forward_rows,const bool forward_read,const int forward_matched,
                                 const int forward_mismatches,const int forward_malformed,const double best_score,
                                 const double min_score)
  {
   if(!back_read || !title_matches || !forward_read) return "";
   if(window_start<=0 || forward_date<=window_start || window_end<=forward_date) return "";
   if(passes<=0 || kept<=0 || kept>profitable || profitable>passes) return "";
   if(!report_closed || malformed!=0) return "";
   if(traded<kept || traded>passes) return "";
   if(forward_rows<=0 || forward_rows>passes) return "";
   if(forward_matched!=kept || forward_mismatches!=0 || forward_malformed!=0) return "";
   if(min_score<=0 || best_score<0 || !(best_score<min_score)) return "";
   return GOAT_XML_NO_QUALIFYING_ROWS;
  }
#ifdef GOAT_BELOW_SCORE_EXPORT_V149
//----------------------------------------------------------------------------------------------------------------------------------------------------
// FWD profit/DD export rule (goatai#1885: Ops 6021950497 (c), 6021976286 and 6022010662; Claude-Mac
// 6021965811, 6022008420 and 6022264062). Used by the below_score export (nothing reached the export
// score) and, behind GOAT_EXPORT_RANK_FWD_PROFIT_DD (off by default), by normal exports.
// Eligible: found in the forward report, SAMPLE (back) profit > 0 with GOAT_XML_MIN_BACK_TRADES+
// trades, FWD profit > 0 with GOAT_XML_BELOW_SCORE_MIN_FWD_TRADES+ trades, a positive FWD recovery
// factor and a combined score of at least minScore (pass a negative minScore for no score floor).
// Ranked on the FWD window alone by profit/DD: the forward Recovery Factor MT5 reports (FWD profit
// over FWD maximal drawdown). Ties go to the higher FWD profit, then the lower pass number. Never
// ranked by the combined (match) score, and never by BOOS or FOOS: those windows are not in the
// optimization reports and stay gates.
#define GOAT_EXPORT_SLOT2_MAX_CORRELATION 0.5
#define GOAT_EXPORT_SLOT2_MIN_SR 2.5
#define GOAT_EXPORT_SLOT2_MIN_ARF 0.2
#define GOAT_EXPORT_CORRELATION_MIN_DAYS 20
// A pass's parameter character (slot 2): the template's own key inputs, i.e. those of its optimized
// inputs (the report's input columns) that set the entry regime (direction and signal modes) or the
// exit regime (stop, target, trailing and lock). A mode or switch differs on any change; a size
// differs when one is off (0) and the other on, the signs differ (pips vs ATR), or one is at least
// twice the other. Inputs the template does not optimize are equal in every pass.
#define GOAT_CHARACTER_MODES ",Mode_Trade,Reverse_Seq,Allow_Opposite_Seq,RSI_Mode,EMA_Mode,ADX_Mode,BB_Mode,MACD_Mode,MACD_Mode_Trend,RSI2_Mode,Mode_Bias,Mode_Bias_Trades,Mode_Bias_Exit,Mode_News,Mode_RRR,Mode_Trail,"
#define GOAT_CHARACTER_SIZES ",SL_Pips,TP_Pips,RRR,TSL_Size,Lock_Profit_Size,"
// Why a pass is not FWD-eligible: 0 eligible, 1 not in the forward report, 2 SAMPLE unprofitable or
// under GOAT_XML_MIN_BACK_TRADES trades, 3 FWD unprofitable, 4 FWD under the trade floor, 5 FWD
// profit/DD not measurable, 6 below the score floor (minScore >= 0 only). The first reason wins.
int GoatXmlFwdIneligibility(const SRowDefinition &rows[],const int i,const double minScore)
  {
   if(!rows[i].forward_seen) return 1;
   if(!(rows[i].back_profit>0) || rows[i].back_trades<GOAT_XML_MIN_BACK_TRADES) return 2;
   if(!(rows[i].forward_profit>0)) return 3;
   if(rows[i].forward_trades<GOAT_XML_BELOW_SCORE_MIN_FWD_TRADES) return 4;
   if(!(rows[i].forward_RF>0)) return 5;
   if(minScore>=0 && rows[i].Score<minScore) return 6;
   return 0;
  }
bool GoatXmlFwdEligible(const SRowDefinition &rows[],const int i,const double minScore)
  {
   return GoatXmlFwdIneligibility(rows,i,minScore)==0;
  }
// NO_FWD_ELIGIBLE_PASS facts: every kept pass counted under the first reason it is not FWD-eligible.
string GoatXmlFwdIneligibleCounts(const SRowDefinition &rows[],const double minScore)
  {
   int eligible=0,notForward=0,sample=0,fwdLoss=0,fwdThin=0,fwdDd=0,belowScore=0,scoreOk=0;
   for(int i=0;i<ArraySize(rows);i++)
     {
      int why=GoatXmlFwdIneligibility(rows,i,minScore);
      if(why==0) eligible++;
      else if(why==1) notForward++;
      else if(why==2) sample++;
      else if(why==3) fwdLoss++;
      else if(why==4) fwdThin++;
      else if(why==5) fwdDd++;
      else belowScore++;
      if(minScore>=0 && rows[i].Score>=minScore) scoreOk++;
     }
   return "rows="+(string)ArraySize(rows)+";fwd_eligible="+(string)eligible+";not_in_forward="+(string)notForward
          +";sample_unprofitable_or_thin="+(string)sample+";fwd_unprofitable="+(string)fwdLoss
          +";fwd_trades_under_floor="+(string)fwdThin+";fwd_dd_unmeasured="+(string)fwdDd
          +(minScore>=0 ? ";below_min_score="+(string)belowScore+";at_min_score="+(string)scoreOk : "");
  }
bool GoatXmlFwdBetter(const SRowDefinition &rows[],const int a,const int b)
  {
   if(rows[a].forward_RF!=rows[b].forward_RF) return rows[a].forward_RF>rows[b].forward_RF;
   if(rows[a].forward_profit!=rows[b].forward_profit) return rows[a].forward_profit>rows[b].forward_profit;
   return rows[a].pass<rows[b].pass;
  }
// Eligible Rows[] indices, best first. Returns how many.
int GoatXmlFwdRank(const SRowDefinition &rows[],const double minScore,int &ranked[])
  {
   ArrayResize(ranked,0);
   for(int i=0;i<ArraySize(rows);i++)
     {
      if(!GoatXmlFwdEligible(rows,i,minScore)) continue;
      int n=ArraySize(ranked); ArrayResize(ranked,n+1);
      int at=n;
      while(at>0 && GoatXmlFwdBetter(rows,i,ranked[at-1])) {ranked[at]=ranked[at-1]; at--;}
      ranked[at]=i;
     }
   return ArraySize(ranked);
  }
// "" when two passes (comma-joined report inputs, in the order of names[]) share a character,
// else the first key input that differs, as "name a->b".
string GoatXmlCharacterDifference(const string &names[],const string inputsA,const string inputsB)
  {
   string a[],b[];
   StringSplit(inputsA,',',a); StringSplit(inputsB,',',b);
   int count=MathMin(ArraySize(names),MathMin(ArraySize(a),ArraySize(b)));
   for(int k=0;k<count;k++)
     {
      string key=","+names[k]+",";
      string va=a[k],vb=b[k];
      StringTrimLeft(va); StringTrimRight(va); StringTrimLeft(vb); StringTrimRight(vb);
      if(StringFind(GOAT_CHARACTER_MODES,key)>=0)
        {
         if(va!=vb) return names[k]+" "+va+"->"+vb;
         continue;
        }
      if(StringFind(GOAT_CHARACTER_SIZES,key)<0) continue;
      double x=StringToDouble(va),y=StringToDouble(vb);
      bool distinct=((x==0)!=(y==0)) || (x*y<0);
      if(!distinct && x!=0 && y!=0) distinct=(MathMax(MathAbs(x),MathAbs(y))>=2.0*MathMin(MathAbs(x),MathAbs(y)));
      if(distinct) return names[k]+" "+va+"->"+vb;
     }
   return "";
  }
// Daily closes of a GOAT equity CSV ("<DATE>\t<BALANCE>\t<EQUITY>..." rows in broker server time,
// oldest first) on days in [from,to): the last equity of each day. -1 when rows go back in time.
int GoatEquityDailyCloses(const string csv,const datetime from,const datetime to,datetime &days[],double &closes[])
  {
   ArrayResize(days,0); ArrayResize(closes,0);
   string lines[];
   int total=StringSplit(csv,'\n',lines);
   for(int i=0;i<total;i++)
     {
      string cells[];
      if(StringSplit(lines[i],'\t',cells)<3) continue;
      string stamp=cells[0];
      StringTrimLeft(stamp); StringTrimRight(stamp);
      if(StringLen(stamp)<10 || StringGetCharacter(stamp,4)!='.' || StringGetCharacter(stamp,7)!='.') continue;
      datetime day=StringToTime(StringSubstr(stamp,0,10));
      if(day<=0 || day<from || day>=to) continue;
      double equity=StringToDouble(cells[2]);
      int n=ArraySize(days);
      if(n>0 && day<days[n-1]) return -1;
      if(n>0 && day==days[n-1]) {closes[n-1]=equity; continue;}
      ArrayResize(days,n+1); ArrayResize(closes,n+1);
      days[n]=day; closes[n]=equity;
     }
   return ArraySize(days);
  }
// Pearson correlation of two equity curves' daily changes over [from,to), on the union of their days
// (a day missing from one curve carries its last close; changes start once both curves have a close).
// EMPTY_VALUE when the curves cannot be read, give fewer than GOAT_EXPORT_CORRELATION_MIN_DAYS
// changes, or one is flat: then the two are never proven different.
double GoatDailyReturnCorrelation(const string csvA,const string csvB,const datetime from,const datetime to,int &n)
  {
   n=0;
   datetime da[],db[]; double ca[],cb[];
   int na=GoatEquityDailyCloses(csvA,from,to,da,ca), nb=GoatEquityDailyCloses(csvB,from,to,db,cb);
   if(na<2 || nb<2) return EMPTY_VALUE;
   int i=0,j=0;
   bool seenA=false,seenB=false;
   double lastA=0,lastB=0,sx=0,sy=0,sxx=0,syy=0,sxy=0;
   while(i<na || j<nb)
     {
      datetime day=((j>=nb || (i<na && da[i]<=db[j])) ? da[i] : db[j]);
      bool hasA=(i<na && da[i]==day), hasB=(j<nb && db[j]==day);
      double a=(hasA ? ca[i] : lastA), b=(hasB ? cb[j] : lastB);
      if(seenA && seenB)
        {
         double x=a-lastA, y=b-lastB;
         n++; sx+=x; sy+=y; sxx+=x*x; syy+=y*y; sxy+=x*y;
        }
      if(hasA) {lastA=a; seenA=true; i++;}
      if(hasB) {lastB=b; seenB=true; j++;}
     }
   if(n<GOAT_EXPORT_CORRELATION_MIN_DAYS) return EMPTY_VALUE;
   double vx=sxx-sx*sx/n, vy=syy-sy*sy/n;
   if(!(vx>0) || !(vy>0)) return EMPTY_VALUE;
   return (sxy-sx*sy/n)/MathSqrt(vx*vy);
  }
#endif
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool ReportAnalyzerCombiner(string &Files[],bool reportMode,string Key_,string EA_Name_,string Server_)
  {
   xmlData.reportMode=reportMode; xmlData._K=Key_; xmlData._N=EA_Name_; xmlData._S=Server_;
   bool ret=true;
#ifdef GOAT_RESEARCH_OUTCOME_V149
   xmlData.outcome="";
   int pairs=0,noEdgePairs=0,noQualifierPairs=0;
#endif
#ifdef GOAT_BELOW_SCORE_EXPORT_V149
   xmlData.belowScoreRow=-1;
#endif
   // Loop over moved files to find matching pairs.
   for(int i=0; i<ArraySize(Files); i++)
     {
      string fileMain = Files[i];
      // Skip files that already are .forward.xml (we want the base file first)
      if(StringFind(fileMain, ".forward.xml") != -1) continue;
      // Ensure the file name ends with ".xml"
      if(StringLen(fileMain) < 4 || StringSubstr(fileMain, StringLen(fileMain)-4, 4) != ".xml") continue;
      // The file should have symbol name
      //if(StringFind(fileMain, Symbol())==-1 && !reportMode) {Alert("File Name not matching current Symbol:"+Symbol()+"\nFilename: "+fileMain); ret=false; continue;}
      // Construct the expected forward file name.
      string baseName = StringSubstr(fileMain, 0, StringLen(fileMain)-4); // remove ".xml"
      // Search for the forward file in the list.
      bool forwardFound = false;
      string forwardFile=baseName + ".forward.xml";
      for(int j=0; j<ArraySize(Files); j++)
        {
         if(StringCompare(Files[j], forwardFile) == 0) {forwardFound = true; break;}
        }
      if(!forwardFound)
        {
         string noExtForward=baseName;
         for(int j=0; j<ArraySize(Files); j++)
           {
            if(StringCompare(Files[j], noExtForward) == 0)
              {
               forwardFile=noExtForward;
               forwardFound=true;
               LogOrPrint(reportMode,"Forward report matched without .forward.xml suffix: "+FileNameOnly(forwardFile),Key_,EA_Name_,Server_);
               break;
              }
           }
        }
      if(forwardFound)
        {
#ifdef GOAT_RESEARCH_OUTCOME_V149
         pairs++;
#endif
         LogOrPrint(reportMode,"File: "+fileMain+" found.",Key_,EA_Name_,Server_);
         // 1) (Optionally) set the forward date from your EA logic
         datetime ForwardDate=0;
         if(xmlData.ExtractForwardDate(fileMain,ForwardDate)) LogOrPrint(reportMode,"Forward Date Extracted: "+TimeToString(ForwardDate,TIME_DATE),Key_,EA_Name_,Server_);
         else                                                {LogOrPrint(reportMode,"❌ Forward Date cannot be extracted from: "+fileMain,Key_,EA_Name_,Server_); ret=false;}
         xmlData.forwardD = ForwardDate; // or some other known forward date
         // 2) Process the back test XML => populates Rows[] and extracts startD, endD
         bool backRead=xmlData.ProcessBackXml(fileMain);
         if(!backRead) ret=false;
         bool titleMatches=(StringFind(fileMain,xmlData.Title)>=0);
         if(!titleMatches)
         {LogOrPrint(reportMode,"❌ xml File name and internal title do not match,\nTitle: "+xmlData.Title+"\nFilename: "+fileMain,Key_,EA_Name_,Server_); ret=false;}
#ifdef GOAT_RESEARCH_OUTCOME_V149
         // A partial or unreadable back report never combines: its trailing or short rows
         // are not results. It stays a real error (retried by --include-failed), never no-edge.
         if(backRead && (!xmlData.reportClosed || xmlData.malformedSeen>0))
         {LogOrPrint(reportMode,"❌ Back report is partial or has unreadable rows (table closed="+(xmlData.reportClosed ? "yes" : "no")
                     +", unreadable rows="+(string)xmlData.malformedSeen+"): "+FileNameOnly(fileMain),Key_,EA_Name_,Server_); ret=false;}
         // Passes ran and none was kept: there is nothing to combine or export for
         // this window. Recorded as a research outcome below, not as a combine error.
         xmlData.forwardRows=xmlData.ForwardReportRows(forwardFile);
         if(GoatXmlResearchOutcome(backRead,titleMatches,xmlData.startD,ForwardDate,xmlData.endD,
                                   xmlData.passesSeen,ArraySize(xmlData.Rows),xmlData.tradedSeen,xmlData.malformedSeen,
                                   xmlData.reportClosed,xmlData.forwardRows)!="")
         {
          noEdgePairs++;
          xmlData.pairOutcome=GOAT_XML_NO_PROFITABLE_PASSES;
          LogOrPrint(reportMode,xmlData.OutcomeSentence(),Key_,EA_Name_,Server_);
          continue;
         }
#endif
         // 3) Process the forward test => merges forward data, calculates Score, then sorts
         bool forwardRead=xmlData.ProcessForwardXml(forwardFile);
         if(!forwardRead) ret=false;
#ifdef GOAT_RESEARCH_OUTCOME_V149
         // Kept passes were scored with their forward period and none reached the export
         // score: nothing to combine or export for this window. Recorded as a research
         // outcome below, not as a combine error ("No Rows!").
         if(GoatXmlNoQualifierOutcome(backRead,titleMatches,xmlData.startD,ForwardDate,xmlData.endD,
                                      xmlData.passesSeen,ArraySize(xmlData.Rows),xmlData.profitableSeen,xmlData.tradedSeen,
                                      xmlData.malformedSeen,xmlData.reportClosed,xmlData.forwardRows,forwardRead,
                                      xmlData.forwardMatched,xmlData.forwardMismatches,xmlData.forwardMalformed,
                                      xmlData.bestCombinedScore,GOAT_XML_MIN_COMBINED_SCORE)!="")
         {
          noQualifierPairs++;
          xmlData.pairOutcome=GOAT_XML_NO_QUALIFYING_ROWS;
          LogOrPrint(reportMode,xmlData.OutcomeSentence(),Key_,EA_Name_,Server_);
          continue;
         }
#endif
         if(ForwardDate!=0)
         {
          double topScore=0.0;
          if(ArraySize(xmlData.Rows)>0)
          {
           topScore=xmlData.Rows[0].Score;
          }
          string scorePostfix=DoubleToString(topScore,1);
          int saved=xmlData.WriteTopToXml (baseName+"_CombinedRows_Score="+scorePostfix+".xml",100,GOAT_XML_MIN_COMBINED_SCORE); if(saved==0) ret=false;
          int wanted=saved/3; if(saved>0&&wanted==0) wanted=saved;
          if(!xmlData.WriteUniqueRowsToXml(baseName+"_UniqueRows_Score="+scorePostfix+".xml",100,wanted,0.0)) ret=false;
         }
         if(ret) LogOrPrint(reportMode,"Finished reading & matching Back/Forward data. Found rows = "+(string)ArraySize(xmlData.Rows),Key_,EA_Name_,Server_);
        }
      else {LogOrPrint(reportMode,"❌ No matching forward file found for: "+fileMain,Key_,EA_Name_,Server_); ret=false;}
     }
#ifdef GOAT_RESEARCH_OUTCOME_V149
   // Only when every pair was tested to the same research outcome and nothing else
   // failed is this the outcome; it still returns false (nothing combined, nothing to
   // export). Pairs that mix both outcomes keep the old error result: the details
   // describe one pair only, so they could not honestly describe the member.
   if(noEdgePairs+noQualifierPairs>0)
     {
      if(ret && noEdgePairs==pairs) xmlData.outcome=GOAT_XML_NO_PROFITABLE_PASSES;
      if(ret && noQualifierPairs==pairs) xmlData.outcome=GOAT_XML_NO_QUALIFYING_ROWS;
      ret=false;
     }
#ifdef GOAT_BELOW_SCORE_EXPORT_V149
   // One pair only: xmlData keeps the last pair's merged passes, so a member with several pairs
   // never exports below_score (its passes could not be told apart from another pair's).
   if(xmlData.outcome==GOAT_XML_NO_QUALIFYING_ROWS && pairs==1)
     {
      int ranked[];
      if(GoatXmlFwdRank(xmlData.Rows,-1.0,ranked)>0) xmlData.belowScoreRow=ranked[0];
     }
#endif
   if(xmlData.outcome!="")
     {
      if(reportMode) Alert(xmlData.OutcomeSentence());
      return ret;
     }
#endif
   if(!ret && reportMode) Alert("One or more error(s) in Report Analyzer+Combiner function, check Experts logs.");
   return ret;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void LogOrAlert(bool reportMode,string body,string Key_,string EA_Name_,string Server_)
  {
   if(reportMode) Alert(body); else WriteLog("TESTER: "+body,true,Key_,EA_Name_,Server_);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void LogOrPrint(bool reportMode,string body,string Key_,string EA_Name_,string Server_)
  {
   if(reportMode) Print(body); else WriteLog(""+body,true,Key_,EA_Name_,Server_);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
void WriteLog(string text,bool print,string Key_,string EA_Name_,string Server_)
  {
   Sleep(10);
   // Trim spaces from both ends
   StringTrimLeft(text); StringTrimRight(text);
   int newlinePos = StringFind(text, "\n");
   if(newlinePos != -1) text = StringSubstr(text, 0, newlinePos);
   if(print) Print(EA_Name_,": ", text);
   int fileHandle = FileOpen(GoatOptLogPath(EA_Name_,Server_),FILE_WRITE|FILE_SHARE_WRITE|FILE_READ|FILE_TXT|FILE_COMMON);
 //int fileHandle = FileOpen(strT._Key_+"\\"+strT._EA_Name_+"-"+strT._Server_+"\\log."+strT._Key_,FILE_WRITE|FILE_SHARE_WRITE|FILE_READ|FILE_TXT|FILE_COMMON);
   if(fileHandle == INVALID_HANDLE) {Print("Error: Could not open or create log file!"); return;}
   // Move file pointer to the end of the file so we effectively append
   FileSeek(fileHandle, 0, SEEK_END);
   // Now write the new entry
   FileWrite(fileHandle, TimeToString(TimeLocal(),TIME_DATE)+" "+TimeToString(TimeLocal(),TIME_SECONDS)+" "+TimeToString(TimeCurrent(),TIME_SECONDS)+"  "+EA_Name_+": "+text);
   // Always close your handle
   FileClose(fileHandle); Sleep(10);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string FileNameOnly(const string full_path)
  {
   // 1) try Windows-style '\' 
   string parts[];
   int n = StringSplit(full_path,'\\',parts);
   if(n > 0)                 // found at least one '\'
      return parts[n-1];     // last token is the file name
   // 2) fallback for an eventual '/' (e.g. in Wine / macOS)
   n = StringSplit(full_path,'/',parts);
   if(n > 0)
      return parts[n-1];
   // 3) nothing to split – already just a name
   return full_path;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string GoatXmlNormalizePath(string path)
  {
   StringReplace(path,"/","\\");
   while(StringFind(path,"\\\\")>=0) StringReplace(path,"\\\\","\\");
   StringTrimLeft(path);
   StringTrimRight(path);
   while(StringLen(path)>0 && StringGetCharacter(path,0)=='\\')
      path=StringSubstr(path,1);
   return path;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool GoatXmlEndsWith(const string text,const string suffix)
  {
   int textLen=StringLen(text), suffixLen=StringLen(suffix);
   if(textLen<suffixLen) return false;
   return (StringSubstr(text,textLen-suffixLen)==suffix);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string GoatXmlFolderOf(string path)
  {
   path=GoatXmlNormalizePath(path);
   int last=-1;
   for(int i=0;i<StringLen(path);i++)
      if(StringGetCharacter(path,i)=='\\') last=i;
   if(last<=0) return "";
   return StringSubstr(path,0,last);
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool GoatXmlFileContains(const string relPath,const bool common,const string needle)
  {
   int flags=FILE_READ|FILE_TXT|FILE_SHARE_READ|FILE_SHARE_WRITE;
   if(common) flags|=FILE_COMMON;
   int handle=FileOpen(relPath,flags);
   if(handle==INVALID_HANDLE) return false;

   int scanLines=0;
   bool found=false;
   while(!FileIsEnding(handle) && scanLines<400)
     {
      string line=FileReadString(handle);
      if(StringFind(line,needle,0)>=0) { found=true; break; }
      scanLines++;
     }
   FileClose(handle);
   return found;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
string GoatXmlNormalizedReportDestination(const string srcRel)
  {
   string dst=GoatXmlNormalizePath(srcRel);
   string lower=dst;
   StringToLower(lower);

   if(GoatXmlEndsWith(lower,".forward.xml") || GoatXmlEndsWith(lower,".xml"))
      return dst;

   if(GoatXmlFileContains(dst,false,"<?xml"))
      return dst+".forward.xml";

   return dst;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool GoatXmlMoveLocalToCommon(const string srcRel,const string dstRel,const string context)
  {
   string src=GoatXmlNormalizePath(srcRel);
   string dst=GoatXmlNormalizePath(dstRel);
   string dstFolder=GoatXmlFolderOf(dst);
   if(dstFolder!="") GoatOptEnsureCommonFolderTree(dstFolder);

   ResetLastError();
   if(FileMove(src,0,dst,FILE_COMMON|FILE_REWRITE))
      return true;

   int mqlErr=GetLastError();
   string localAbs=TerminalInfoString(TERMINAL_DATA_PATH)+"\\MQL5\\Files\\"+src;
   string commonAbs=TerminalInfoString(TERMINAL_COMMONDATA_PATH)+"\\Files\\"+dst;
   ResetLastError();
   if(MTTESTER::FileMove(localAbs,commonAbs,true))
     {
      Print(context,": MQL FileMove failed (",mqlErr,") but absolute fallback moved ",src," -> ",dst);
      return true;
     }

   Print(context,": error moving ",src," -> ",dst,"  MQL error=",mqlErr," fallback error=",GetLastError());
   return false;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool MigrateRunReportFilesToCommon(const string reportRoot,string &MovedFileNames[],string Key_,string EA_Name_,string Server_)
  {
   string root=GoatXmlNormalizePath(reportRoot);
   bool success=true;
   string filter=root+"\\*";
   string entry;
   long h=FileFindFirst(filter,entry,0);
   if(h==INVALID_HANDLE)
     {
      FolderDelete(root);
      return true;
     }

   do
     {
      string src=GoatXmlNormalizePath(root+"\\"+entry);
      ResetLastError();
      FileIsExist(src,0);
      if(GetLastError()==ERR_FILE_IS_DIRECTORY)
        {
         if(!MigrateRunReportFilesToCommon(src,MovedFileNames,Key_,EA_Name_,Server_))
           {
            Print(__FUNCTION__,": failed to migrate subfolder ",src);
            success=false;
           }
        }
      else
        {
         string dst=GoatXmlNormalizedReportDestination(src);
         if(GoatXmlMoveLocalToCommon(src,dst,__FUNCTION__))
           {
            int idx=ArraySize(MovedFileNames);
            ArrayResize(MovedFileNames,idx+1);
            MovedFileNames[idx]=dst;
            WriteLog("DEINIT: XML migrated: "+FileNameOnly(dst),false,Key_,EA_Name_,Server_);
           }
         else success=false;
        }
     }
   while(FileFindNext(h,entry));
   FileFindClose(h);

   long h2=FileFindFirst(filter,entry,0);
   if(h2==INVALID_HANDLE) FolderDelete(root);
   else FileFindClose(h2);
   return success;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
bool MigrateFilesToCommon(const string folder, string &MovedFileNames[])
  {
   bool success=true,created_common=false;
   string sourceFolder=GoatXmlNormalizePath(folder);
   string filter=sourceFolder+"\\*";
   string entry;
   // Check if the source folder has anything
   long h=FileFindFirst(filter,entry,0);
   if(h==INVALID_HANDLE)
     {
      // Folder is empty in MQL5\Files, delete it
      FolderDelete(sourceFolder);
      return true;
      }
   // Process each item
   do{
      string src=GoatXmlNormalizePath(sourceFolder+"\\"+entry);
      ResetLastError();
      FileIsExist(src,0);
      if(GetLastError()==ERR_FILE_IS_DIRECTORY)
        {
         // Recursively migrate subfolder
         if(!MigrateFilesToCommon(src,MovedFileNames))
           {
            Print("Failed to migrate subfolder: ", src);
            success=false;
           }
        }
      else
        {
         // Create the matching folder in Common if this is the first file
         if(!created_common)
            {
             GoatOptEnsureCommonFolderTree(sourceFolder);
             created_common=true;
            }
          // Move the file
          if(!GoatXmlMoveLocalToCommon(src,src,__FUNCTION__))
            {
             success=false;
            }
         else
           {
            // Store the relative path so we can later open with FILE_COMMON
            int idx=ArraySize(MovedFileNames);
            ArrayResize(MovedFileNames,idx+1);
            MovedFileNames[idx]=src; // Relative path to 'folder\filename'
           }
        }
     }
   while(FileFindNext(h,entry));
   FileFindClose(h);
   // After handling all items, check if folder became empty and remove it
   long h2=FileFindFirst(filter,entry,0);
    if(h2==INVALID_HANDLE) FolderDelete(sourceFolder);
   else FileFindClose(h2);
   return success;
  }
//----------------------------------------------------------------------------------------------------------------------------------------------------
//  Recursively move everything that is now in  <folder>\*
//  to        FILE_COMMON\<CommonFolder>\…                (preserving any sub-folder structure)
//  •  Deletes empty source directories on the way back up
//  •  Builds a list with the relative paths that can later be opened with FILE_COMMON
bool MigrateLeftOverFilesToCommon(const string folder,string &moved_files[],string CommonFolder="LeftoverXMLs")
 {
   bool success = true;
   string sourceFolder=GoatXmlNormalizePath(folder);
   string commonRoot=GoatXmlNormalizePath(CommonFolder);
   string filter = sourceFolder + "\\*";
   string entry;
   //-- First item (if any)
   long h = FileFindFirst(filter, entry, 0);
   if(h == INVALID_HANDLE)          // nothing here – just delete the empty dir and bail out
   {
       FolderDelete(sourceFolder);
       return true;
    }
    //-- Make sure the target root exists in FILE_COMMON
    GoatOptEnsureCommonFolderTree(commonRoot);
   do
   {
       string src  = GoatXmlNormalizePath(sourceFolder + "\\" + entry);          // source, relative to local MQL5\Files
      ResetLastError();
      FileIsExist(src, 0);
      bool is_dir = (GetLastError() == ERR_FILE_IS_DIRECTORY);
      if(is_dir)                                    // ── recurse into sub-folder ──
      {
          string dstSub = GoatXmlNormalizePath(commonRoot + "\\" + entry);
          GoatOptEnsureCommonFolderTree(dstSub);      // ensure matching sub-dir exists in FILE_COMMON
         if(!MigrateLeftOverFilesToCommon(src, moved_files, dstSub))
         {
            Print(__FUNCTION__, ": failed to migrate subfolder ", src);
            success = false;
         }
      }
      else                                          // ── move a single file ──
      {
          string dst = GoatXmlNormalizePath(commonRoot + "\\" + entry);  // e.g.  "LeftoverXMLs\\file.xml"
          string normalizedReport=GoatXmlNormalizedReportDestination(src);
          if(normalizedReport!=src)
             dst+=StringSubstr(normalizedReport,StringLen(src));
          if(!GoatXmlMoveLocalToCommon(src,dst,__FUNCTION__))
          {
             success = false;
          }
         else                                       // remember for the caller
         {
            int n = ArraySize(moved_files);
            ArrayResize(moved_files, n + 1);
            moved_files[n] = dst;                   // relative to FILE_COMMON
         }
      }
   }
   while(FileFindNext(h, entry));
   FileFindClose(h);
   //-- remove the source folder if we emptied it
   long h2 = FileFindFirst(filter, entry, 0);
    if(h2 == INVALID_HANDLE) FolderDelete(sourceFolder);
   else                     FileFindClose(h2);
   return success;
}
//----------------------------------------------------------------------------------------------------------------------------------------------------

