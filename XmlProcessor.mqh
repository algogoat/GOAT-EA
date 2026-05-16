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

   SRowDefinition()
   {
      pass=-1; back_result=0; back_profit=0; back_PF=0; back_RF=0; back_SR=0; back_DD_pc=0; back_trades=0;
      forward_result=0; forward_profit=0; forward_PF=0; forward_RF=0; forward_SR=0; forward_DD_pc=0; forward_trades=0;
      Inputs=""; Score=0;
   }
   SRowDefinition(const SRowDefinition &src)
   {
      pass=src.pass;
      back_result=src.back_result; back_profit=src.back_profit; back_PF=src.back_PF; back_RF=src.back_RF; back_SR=src.back_SR; back_DD_pc=src.back_DD_pc; back_trades=src.back_trades;
      forward_result=src.forward_result; forward_profit=src.forward_profit; forward_PF=src.forward_PF; forward_RF=src.forward_RF; forward_SR=src.forward_SR;
      forward_DD_pc=src.forward_DD_pc; forward_trades=src.forward_trades;
      Inputs=src.Inputs;
      Score=src.Score;
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
         if(FileReadString(hBack)=="<Row>")
         {
            Rows[i].pass=(int)ExtractDataAsDouble(FileReadString(hBack));
            Rows[i].back_result=ExtractDataAsDouble(FileReadString(hBack));
            Rows[i].back_profit=ExtractDataAsDouble(FileReadString(hBack));
            if(Rows[i].back_profit<0.001)
            {
               line="";
               while(line!="</Row>")line=FileReadString(hBack);
               i--; continue;
            }
            string dump=FileReadString(hBack);
            Rows[i].back_PF=ExtractDataAsDouble(FileReadString(hBack));
            Rows[i].back_RF=ExtractDataAsDouble(FileReadString(hBack));
            Rows[i].back_SR=ExtractDataAsDouble(FileReadString(hBack));
            string dump2=FileReadString(hBack);
            Rows[i].back_DD_pc=ExtractDataAsDouble(FileReadString(hBack));
            Rows[i].back_trades=(int)ExtractDataAsDouble(FileReadString(hBack));
            if(Rows[i].back_trades<50)//<=90
            {
               line="";
               while(line!="</Row>")line=FileReadString(hBack);
               i--;
               continue;
            }
            Rows[i].Inputs=ExtractDataFromCell(FileReadString(hBack));
            while(true)
            {
               line=FileReadString(hBack);
               if(line=="</Row>")break;
               Rows[i].Inputs+=","+ExtractDataFromCell(line);
            }
            ArrayResize(Rows,ArraySize(Rows)+1,3000);
         }
         else
         {
            ArrayResize(Rows,ArraySize(Rows)-1);
            LogOrPrint(reportMode,"No further back <Row> Found. Rows Saved="+(string)ArraySize(Rows)+"/"+(string)i,_K,_N,_S);
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
      for(int i=0; !FileIsEnding(hForward); i++)
      {
         if(FileReadString(hForward)=="<Row>")
         {
            int pass=(int)ExtractDataAsDouble(FileReadString(hForward));
            int bPos=GetBackPassRow(pass);
            if(bPos==-1)
            {
               line="";
               while(line!="</Row>")line=FileReadString(hForward);
               discarded++; continue;
            }
            Rows[bPos].forward_result=ExtractDataAsDouble(FileReadString(hForward));
            double tmpBackResult=ExtractDataAsDouble(FileReadString(hForward));
            if(Rows[bPos].back_result!=tmpBackResult)
            {
               LogOrPrint(reportMode,"❌ Back result mismatch in forward xml. Pass="+(string)pass,_K,_N,_S);
               //return false;
            }
            Rows[bPos].forward_profit=ExtractDataAsDouble(FileReadString(hForward));
            string dump=FileReadString(hForward);
            Rows[bPos].forward_PF=ExtractDataAsDouble(FileReadString(hForward));
            Rows[bPos].forward_RF=ExtractDataAsDouble(FileReadString(hForward));
            Rows[bPos].forward_SR=ExtractDataAsDouble(FileReadString(hForward));
            string dump2=FileReadString(hForward);
            Rows[bPos].forward_DD_pc=ExtractDataAsDouble(FileReadString(hForward));
            Rows[bPos].forward_trades=(int)ExtractDataAsDouble(FileReadString(hForward));
            string Inputsforward=ExtractDataFromCell(FileReadString(hForward));
            while(true)
            {
               line=FileReadString(hForward);
               if(line=="</Row>")break;
               Inputsforward+=","+ExtractDataFromCell(line);
            }
            if(Inputsforward!=Rows[bPos].Inputs)
            {
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
private:
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
   }
};
//----------------------------------------------------------------------------------------------------------------------------------------------------
SXmlData xmlData;
bool ReportAnalyzerCombiner(string &Files[],bool reportMode,string Key_,string EA_Name_,string Server_)
  {
   xmlData.reportMode=reportMode; xmlData._K=Key_; xmlData._N=EA_Name_; xmlData._S=Server_;
   bool ret=true;
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
      for(int j=0; j<ArraySize(Files); j++)
        {
         if(StringCompare(Files[j], baseName + ".forward.xml") == 0) {forwardFound = true; break;}
        }
      if(forwardFound)
        {
         LogOrPrint(reportMode,"File: "+fileMain+" found.",Key_,EA_Name_,Server_);
         // 1) (Optionally) set the forward date from your EA logic
         datetime ForwardDate=0;
         if(xmlData.ExtractForwardDate(fileMain,ForwardDate)) LogOrPrint(reportMode,"Forward Date Extracted: "+TimeToString(ForwardDate,TIME_DATE),Key_,EA_Name_,Server_);
         else                                                {LogOrPrint(reportMode,"❌ Forward Date cannot be extracted from: "+fileMain,Key_,EA_Name_,Server_); ret=false;}
         xmlData.forwardD = ForwardDate; // or some other known forward date
         // 2) Process the back test XML => populates Rows[] and extracts startD, endD
         if(!xmlData.ProcessBackXml(fileMain)) ret=false;
         if(StringFind(fileMain,xmlData.Title)<0)
         {LogOrPrint(reportMode,"❌ xml File name and internal title do not match,\nTitle: "+xmlData.Title+"\nFilename: "+fileMain,Key_,EA_Name_,Server_); ret=false;}
         // 3) Process the forward test => merges forward data, calculates Score, then sorts
         if(!xmlData.ProcessForwardXml((baseName+".forward.xml"))) ret=false;
         if(ForwardDate!=0)
         {
          double topScore=0.0;
          if(ArraySize(xmlData.Rows)>0)
          {
           topScore=xmlData.Rows[0].Score;
          }
          string scorePostfix=DoubleToString(topScore,1);
          int saved=xmlData.WriteTopToXml (baseName+"_CombinedRows_Score="+scorePostfix+".xml",100,60.0); if(saved==0) ret=false;
          int wanted=saved/3; if(saved>0&&wanted==0) wanted=saved;
          if(!xmlData.WriteUniqueRowsToXml(baseName+"_UniqueRows_Score="+scorePostfix+".xml",100,wanted,0.0)) ret=false;
         }
         if(ret) LogOrPrint(reportMode,"Finished reading & matching Back/Forward data. Found rows = "+(string)ArraySize(xmlData.Rows),Key_,EA_Name_,Server_);
        }
      else {LogOrPrint(reportMode,"❌ No matching forward file found for: "+fileMain,Key_,EA_Name_,Server_); ret=false;}
     }
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
bool MigrateFilesToCommon(const string folder, string &MovedFileNames[])
  {
   bool success=true,created_common=false;
   string filter=folder+"\\*";
   string entry;
   // Check if the source folder has anything
   long h=FileFindFirst(filter,entry,0);
   if(h==INVALID_HANDLE)
     {
      // Folder is empty in MQL5\Files, delete it
      FolderDelete(folder);
      return true;
     }
   // Process each item
   do{
      string src=folder+"\\"+entry;
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
            FolderCreate(folder,FILE_COMMON);
            created_common=true;
           }
         // Move the file
         if(!FileMove(src,0,src,FILE_COMMON|FILE_REWRITE))
           {
            Print("Error moving file: ", src, " Error: ", GetLastError());
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
   if(h2==INVALID_HANDLE) FolderDelete(folder);
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
   string filter = folder + "\\*";
   string entry;
   //-- First item (if any)
   long h = FileFindFirst(filter, entry, 0);
   if(h == INVALID_HANDLE)          // nothing here – just delete the empty dir and bail out
   {
      FolderDelete(folder);
      return true;
   }
   //-- Make sure the target root exists in FILE_COMMON
   FolderCreate(CommonFolder, FILE_COMMON);
   do
   {
      string src  = folder + "\\" + entry;          // source, relative to local MQL5\Files
      ResetLastError();
      FileIsExist(src, 0);
      bool is_dir = (GetLastError() == ERR_FILE_IS_DIRECTORY);
      if(is_dir)                                    // ── recurse into sub-folder ──
      {
         string dstSub = CommonFolder + "\\" + entry;
         FolderCreate(dstSub, FILE_COMMON);         // ensure matching sub-dir exists in FILE_COMMON
         if(!MigrateLeftOverFilesToCommon(src, moved_files, dstSub))
         {
            Print(__FUNCTION__, ": failed to migrate subfolder ", src);
            success = false;
         }
      }
      else                                          // ── move a single file ──
      {
         string dst = CommonFolder + "\\" + entry;  // e.g.  "LeftoverXMLs\\file.xml"
         if(!FileMove(src, 0, dst, FILE_COMMON | FILE_REWRITE))
         {
            Print(__FUNCTION__,": error moving ", src, " → ", dst,"  (", GetLastError(), ")");
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
   if(h2 == INVALID_HANDLE) FolderDelete(folder);
   else                     FileFindClose(h2);
   return success;
}
//----------------------------------------------------------------------------------------------------------------------------------------------------

