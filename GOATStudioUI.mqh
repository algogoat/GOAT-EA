#ifndef GOAT_STUDIO_UI_MQH
#define GOAT_STUDIO_UI_MQH
#include "GOATStudioBridge.mqh"
#include "GOATStudioNative.mqh"
CGoatStudioBridge g_StudioBridge;
bool g_StudioBound=false;
string g_StudioPendingId="",g_StudioPendingHash="",g_StudioPendingCommand="",g_StudioLastError="";
string g_StudioLastObservation="";
ulong g_StudioObservationMillis=0;
int g_StudioEditorLock=INVALID_HANDLE;
bool g_StudioReceiptResolved=false;
string g_StudioSnapshot="",g_StudioQueueRendered="",g_StudioQueueIds[],g_StudioQueueStatuses[];
long g_StudioQueueRevision=-1,g_StudioQueueGeneration=-1;
string g_StudioSchemaHash="",g_StudioStrategyName="";
bool g_StudioHasStrategy=false;
void GoatStudioDispatch(void);

bool GoatStudioManaged(void)
  {
   // Explicit local opt-in, only in the already isolated monitor operating path.
   return g_GoatStudioReadOnlyMonitor && FileIsExist("GOATStudio\\active.json");
  }

string GoatStudioFields(const bool exports)
  {
   return exports ? "SetsToExport,MinScore,TargetDD,AdjustLots,BackOOSDate,MinARF,MinSR,IncludeBackOOS"
      : "Expert,Symbol,Period,Model,ExecutionMode,Optimization,OptimizationCriterion,FromDate,ToDate,ForwardMode,ForwardDate,Deposit,Currency,Leverage,UseLocal,UseRemote,UseCloud,Visual";
  }

bool GoatStudioSectionINI(const string body,SGOATJsonToken &tokens[],const int section,const bool exports,string &ini)
  {
   ini="";
   if(section<0 || tokens[section].type!=GOAT_JSON_OBJECT) return false;
   string fields[]; int count=StringSplit(GoatStudioFields(exports),',',fields);
   for(int i=0;i<count;i++)
     {
      int token=GOATJsonFindField(body,tokens,section,fields[i]);
      if(token<0) return false;
      string value;
      if(tokens[token].type==GOAT_JSON_STRING)
        {if(!GOATJsonStringValue(body,tokens[token],value)) return false;}
      else if(tokens[token].type==GOAT_JSON_NUMBER) value=StringSubstr(body,tokens[token].start,tokens[token].end-tokens[token].start);
      else if(tokens[token].type==GOAT_JSON_TRUE) value="1";
      else if(tokens[token].type==GOAT_JSON_FALSE) value="0";
      else return false;
      if(StringFind(value,"\n")>=0 || StringFind(value,"\r")>=0) return false;
      ini+=fields[i]+"="+value+"\n";
     }
   return true;
  }

bool GoatStudioUIState(string &tester,string &exports,string &owner,long &revision,long &generation,string &status,bool &saved)
  {
   saved=false; g_StudioReceiptResolved=false; status="Controller unavailable";
   if(!GoatStudioManaged()) return false;
   if(!g_StudioBound)
     {
      status="Unable to read or verify local Studio activation config";
      string config,id,terminal,run,data; SGOATJsonToken cfg[];
      if(!GoatStudioReadUtf8("GOATStudio\\active.json",config) || !GOATJsonParse(config,cfg)
         || !GOATJsonGetString(config,cfg,0,"directory_id",id)
         || !GOATJsonGetString(config,cfg,0,"terminal_id",terminal)
         || !GOATJsonGetString(config,cfg,0,"run_id",run)
         || !GOATJsonGetString(config,cfg,0,"terminal_data_path",data)
         || data!=TerminalInfoString(TERMINAL_DATA_PATH)) return false;
      status="Unable to bind local Studio controller";
      g_StudioBound=g_StudioBridge.Bind(id,terminal,run);
      if(!g_StudioBound) return false;
     }
   // Claim the editor before recovering/acknowledging any human command.
   if(g_StudioEditorLock==INVALID_HANDLE)
     {
      g_StudioEditorLock=FileOpen(g_StudioBridge.DraftPath()+".lock",FILE_READ|FILE_WRITE|FILE_BIN);
      if(g_StudioEditorLock==INVALID_HANDLE) {status="Another Studio editor owns this run"; return false;}
     }
   string pending_id,pending_hash,pending_command;
   int pending=g_StudioBridge.RecoverPending(pending_id,pending_hash,pending_command);
   if(pending<0) {status="Pending command recovery failed; journal retained"; return false;}
   if(pending==1)
     {g_StudioPendingId=pending_id; g_StudioPendingHash=pending_hash; g_StudioPendingCommand=pending_command;}
   string body; SGOATJsonToken tokens[];
   status="Unable to read or verify controller snapshot";
   if(!g_StudioBridge.ReadSnapshot(body) || !GOATJsonParse(body,tokens,16384,2000000)) return false;
   int state=GOATJsonFindField(body,tokens,0,"state");
   if(!GOATJsonGetString(body,tokens,state,"owner",owner)
      || !GOATJsonGetInteger(body,tokens,state,"revision",revision)
      || !GOATJsonGetInteger(body,tokens,state,"generation",generation)) return false;
   status=(owner=="human" ? "Human controls settings" : "Agent controls settings")+" / revision "+(string)revision;
   if(g_StudioPendingId!="")
     {
      string receipt; bool applied=false;
      if(g_StudioBridge.ReadReceipt(g_StudioPendingId,g_StudioPendingHash,receipt,applied))
        {
         long acknowledged=-1;
         if(applied)
           {
            SGOATJsonToken rt[]; long committed=-1;
            if(!GOATJsonParse(receipt,rt)) return false;
            int rr=GOATJsonFindField(receipt,rt,0,"receipt");
            int rs=GOATJsonFindField(receipt,rt,rr,"state");
            if(!GOATJsonGetInteger(receipt,rt,rs,"revision",committed) || committed>revision)
              {status="Waiting for committed snapshot"; return false;}
            acknowledged=committed;
           }
         saved=applied && acknowledged==revision && g_StudioPendingCommand=="draft.replace_configuration";
         if(applied && acknowledged<revision) g_StudioLastError="Newer committed changes exist; review before saving retained edits";
         if(!applied) {SGOATJsonToken rt[]; string error; if(GOATJsonParse(receipt,rt)&&GOATJsonGetString(receipt,rt,0,"error",error)) g_StudioLastError=error;}
         // Keep the original request recoverable until the editor has durably
         // recorded its acknowledged baseline and any later unsaved edits.
         g_StudioReceiptResolved=true;
        }
      else status="Waiting for controller receipt";
     }
   if(g_StudioLastError!="") status=g_StudioLastError;
   if(!GoatStudioSectionINI(body,tokens,GOATJsonFindField(body,tokens,state,"tester_draft"),false,tester)
      || !GoatStudioSectionINI(body,tokens,GOATJsonFindField(body,tokens,state,"export_draft"),true,exports))
     {status="Controller needs tester and export drafts"; return false;}
   g_StudioSnapshot=body;
   g_StudioHasStrategy=false; g_StudioStrategyName=""; g_StudioSchemaHash="";
   GOATJsonGetString(body,tokens,0,"schema_hash",g_StudioSchemaHash);
   int strategy=GOATJsonFindField(body,tokens,state,"strategy_draft");
   if(strategy>=0 && tokens[strategy].type==GOAT_JSON_OBJECT)
     {
      int values=GOATJsonFindField(body,tokens,strategy,"values");
      g_StudioHasStrategy=(values>=0 && tokens[values].type==GOAT_JSON_OBJECT);
      GOATJsonGetString(body,tokens,values,"EA_Desc",g_StudioStrategyName);
     }
   g_StudioQueueRevision=revision; g_StudioQueueGeneration=generation;
   return true;
  }

bool GoatStudioINIJson(const string ini,const bool exports,string &body)
  {
   body="{"; string fields[]; int count=StringSplit(GoatStudioFields(exports),',',fields);
   string strings=",Expert,Symbol,Period,FromDate,ToDate,ForwardDate,Currency,Leverage,BackOOSDate,";
   for(int i=0;i<count;i++)
     {
      string key=fields[i],value=GoatOptReadIniValue(ini,key);
      // Preserve explicit shared worker policy; the legacy editor has no worker controls.
      if(!exports && (key=="UseLocal" || key=="UseRemote" || key=="UseCloud"))
        {
         SGOATJsonToken snapshot[]; long worker;
         if(!GOATJsonParse(g_StudioSnapshot,snapshot,16384,2000000)) return false;
         int state=GOATJsonFindField(g_StudioSnapshot,snapshot,0,"state");
         int tester=GOATJsonFindField(g_StudioSnapshot,snapshot,state,"tester_draft");
         if(!GOATJsonGetInteger(g_StudioSnapshot,snapshot,tester,key,worker) || (worker!=0 && worker!=1)) return false;
         value=(string)worker;
        }
      if(key=="Leverage" && StringFind(value,":")<0) value="1:"+value;
      if(key=="ForwardDate" && GoatOptReadIniValue(ini,"ForwardMode")!="4") value="";
      string encoded;
      if(StringFind(strings,","+key+",")>=0) encoded=GoatStudioQuote(value);
      else if(key=="AdjustLots" || key=="IncludeBackOOS")
        {if(value!="0" && value!="1") return false; encoded=(value=="1" ? "true" : "false");}
      else
        {SGOATJsonToken number[]; int pos=0,token=-1; if(!GOATJsonParseNumberToken(value,pos,-1,number,token) || pos!=StringLen(value) || ArraySize(number)!=1) return false; encoded=value;}
      body+=(i==0 ? "" : ",")+GoatStudioQuote(key)+":"+encoded;
     }
   body+="}"; return true;
  }

bool GoatStudioUISubmit(const string command,const string tester,const string exports,const long revision,const long generation)
  {
   if(!g_StudioBound || g_StudioPendingId!="") return false;
   string payload="{}";
   if(command=="draft.replace_configuration")
     {
      string t,e;
      if(!GoatStudioINIJson(tester,false,t) || !GoatStudioINIJson(exports,true,e)) return false;
      payload="{\"tester\":"+t+",\"export\":"+e+"}";
     }
   string id="ui-"+(string)ChartID()+"-"+(string)GetMicrosecondCount(),hash;
   if(!g_StudioBridge.SubmitHuman(id,command,payload,hash,revision,generation)) return false;
   g_StudioPendingId=id; g_StudioPendingHash=hash; g_StudioPendingCommand=command; g_StudioLastError=""; return true;
  }

// Enable() in ControlsPlus restores its light-theme defaults and can reveal
// the arrow of an otherwise hidden combo. Restore our theme and page visibility.
void GoatStudioComboTheme(CComboBox &combo,const bool visible,const bool editable)
  {
   CEdit *field=(CEdit*)combo.Control(0);
   if(field!=NULL) field.Color(editable ? C'225,238,248' : C'135,181,216');
   if(!visible) combo.Hide();
  }

void CStrategyTesterDialog::ChartEvent(const int id,const long &lparam,const double &dparam,const string &sparam)
  {
   // Reflow before the base dialog compares the old size with the new chart.
   // Its automatic minimize path corrupts the managed layout during shrinking.
   if(GoatStudioManaged() && id==CHARTEVENT_CHART_CHANGE)
     {ManagedResize(); ChartRedraw(m_chart_id); return;}
   CAppDialog::ChartEvent(id,lparam,dparam,sparam);
  }

void CStrategyTesterDialog::ManagedResize(void)
  {
   int cw=(int)ChartGetInteger(m_chart_id,CHART_WIDTH_IN_PIXELS);
   int ch=(int)ChartGetInteger(m_chart_id,CHART_HEIGHT_IN_PIXELS);
   if(cw<=0 || ch<=0) return;
   // Reflow from viewport dimensions, never from previously rounded controls.
   // Retain a readable minimum canvas when docked panes leave too little room.
   int width=(int)MathMax(1000,cw-16);
   int height=(int)MathMax(480,ch-52);
   D_Width=width; D_Height=height;
   m_leftMargin=16; m_topMargin=8; m_GapHoriz=10;
   m_controlHeight=(int)MathMax(24,Font_Size*2+8);
   m_rowHeight=(int)MathMax(m_controlHeight+4,MathMin(34,(height-60)/14));
   int editor_width=(width-64)*46/100;
   m_labelWidth=100;
   m_controlWidth=editor_width-m_labelWidth-m_GapHoriz;
   int left=(int)MathMax(0,(cw-width)/2),top=(int)MathMax(0,(ch-height-36)/2);
   m_norm_rect.SetBound(left,top,left+width,top+height+36);
   Rebound(m_norm_rect);
   m_caption.Height(28);
   m_client_area.Alignment(WND_ALIGN_CLIENT,8,32,8,8);
   m_client_area.Move(Left()+8,Top()+32); m_client_area.Size(width-16,height-4);
   StageMove(c_Wnd_OPT,0,0,true,width-16,height-4);
   int tabs_width=width-48,tab_gap=8,tab_width=(tabs_width-3*tab_gap)/4;
   StageMove(m_btnStageSetup,16,8,true,tab_width,m_controlHeight);
   StageMove(m_btnStageTimeline,16+tab_width+tab_gap,8,true,tab_width,m_controlHeight);
   StageMove(m_btnStageExecution,16+2*(tab_width+tab_gap),8,true,tab_width,m_controlHeight);
   StageMove(m_btnStageExport,16+3*(tab_width+tab_gap),8,true,tabs_width-3*(tab_width+tab_gap),m_controlHeight);
   int qx=m_leftMargin+editor_width+24,qw=width-32-qx;
   int list_top=m_topMargin+2*m_rowHeight;
   int bottom=height-16-m_controlHeight;
   StageMove(m_lblQueue,qx,m_topMargin+m_rowHeight,true,qw,m_controlHeight);
   StageMove(m_listQueue,qx,list_top,true,qw,bottom-list_top-8);
   m_listQueue.FitRows(m_rowHeight-1,Font_Size);
   Id(Id()); // Register event IDs for rows and scrollbars created during reflow.
   int gap=6,arrow=32,action=(qw-5*gap-2*arrow)/4;
   int x=qx;
   StageMove(m_btnDelQ,x,bottom,true,action,m_controlHeight); x+=action+gap;
   StageMove(m_btnDelQitem,x,bottom,true,action,m_controlHeight); x+=action+gap;
   StageMove(m_btnUpQitem,x,bottom,true,arrow,m_controlHeight); x+=arrow+gap;
   StageMove(m_btnDownQitem,x,bottom,true,arrow,m_controlHeight); x+=arrow+gap;
   StageMove(m_btnCancelSelected,x,bottom,true,action,m_controlHeight); x+=action+gap;
   StageMove(m_btnMakePending,x,bottom,true,qx+qw-x,m_controlHeight);
   int half=(editor_width-8)/2,button_height=m_controlHeight+8;
   int action_y=bottom-button_height-8;
   StageMove(m_lblBatchControl,m_leftMargin,action_y-m_rowHeight,true,editor_width,m_controlHeight);
   StageMove(m_btnStart,m_leftMargin,action_y,true,half,button_height);
   StageMove(m_btnStop,m_leftMargin+half+8,action_y,true,editor_width-half-8,button_height);
   StageMove(m_edtBatchProgress,m_leftMargin,bottom,true,half,m_controlHeight);
   StageMove(m_edtBatchErrors,m_leftMargin+half+8,bottom,true,editor_width-half-8,m_controlHeight);
   ApplyStudioStage(m_activeStage);
   ManagedControls();
  }

void CStrategyTesterDialog::ManagedControls(void)
  {
   bool edit=m_studioLoaded && !m_studioDraftFailed && m_studioOwner=="human";
   m_btnStart.Text("TAKE CONTROL"); m_btnStart.Enable();
   m_btnStop.Text("GIVE TO AGENT");
   m_btnAddQueue.Text("SAVE SETTINGS"); m_btnSetPresets.Text("LOAD SAVED");
   m_btnSetPresets.Enable();
   if(edit) {m_btnAddQueue.Enable(); m_btnStop.Enable();}
   else {m_btnAddQueue.Disable(); m_btnStop.Disable();}
   // All other actions remain disabled by the monitor's base layout.
   if(edit)
     {
      m_cmbSymbol.Enable(); m_cmbPeriod.Enable(); m_dtFrom.Enable(); m_dtTo.Enable();
      m_cmbForward.Enable(); if(m_cmbForward.Select()=="Custom") m_dtForward.Enable();
      m_cmbDelay.Enable(); m_cmbModel.Enable(); m_edtDeposit.Enable(); m_edtCurrency.Enable();
      m_cmbLeverage.Enable(); m_edtSetsToExport.Enable(); m_dpBackOOS.Enable();
      m_edtMinScore.Enable(); m_edtMinARF.Enable(); m_edtTargetDD.Enable(); m_edtMinSR.Enable();
      m_chkAdjustLots.Enable(); m_chkVerifyOOS.Enable();
     }
   else
     {
      m_cmbSymbol.Disable(); m_cmbPeriod.Disable(); m_dtFrom.Disable(); m_dtTo.Disable();
      m_cmbForward.Disable(); m_dtForward.Disable(); m_cmbDelay.Disable(); m_cmbModel.Disable();
      m_edtDeposit.Disable(); m_edtCurrency.Disable(); m_cmbLeverage.Disable();
      m_edtSetsToExport.Disable(); m_dpBackOOS.Disable(); m_edtMinScore.Disable();
      m_edtMinARF.Disable(); m_edtTargetDD.Disable(); m_edtMinSR.Disable();
      m_chkAdjustLots.Disable(); m_chkVerifyOOS.Disable();
     }
   m_btnStart.Color(C'225,238,248'); m_btnSetPresets.Color(C'225,238,248');
   m_btnAddQueue.Color(edit ? C'225,238,248' : C'100,120,140');
   m_btnStop.Color(edit ? C'225,238,248' : C'100,120,140');
   GoatStudioComboTheme(m_cmbSymbol,m_activeStage==0,edit);
   GoatStudioComboTheme(m_cmbPeriod,m_activeStage==0,edit);
   GoatStudioComboTheme(m_cmbForward,m_activeStage==1,edit);
   GoatStudioComboTheme(m_cmbDelay,m_activeStage==2,edit);
   GoatStudioComboTheme(m_cmbModel,m_activeStage==2,edit);
   GoatStudioComboTheme(m_cmbLeverage,m_activeStage==2,edit);
   if(m_activeStage!=1) {m_dtFrom.Hide(); m_dtTo.Hide(); m_dtForward.Hide();}
   if(m_activeStage!=3) {m_dpBackOOS.Hide(); m_chkAdjustLots.Hide(); m_chkVerifyOOS.Hide();}
   int selected=m_listQueue.Current();
   bool pending=selected>=0 && selected<ArraySize(g_StudioQueueStatuses) && g_StudioQueueStatuses[selected]=="pending";
   bool queue_edit=edit && g_StudioPendingId=="";
   if(queue_edit && GOATIsLowerHex(g_StudioSchemaHash,64)) m_btnSelectFile.Enable(); else m_btnSelectFile.Disable();
   m_btnSelectFile.Color(queue_edit ? C'225,238,248' : C'100,120,140');
   m_edtStrategy.Text(g_StudioHasStrategy ? g_StudioStrategyName : "Select a strategy SET file");
   m_btnDelQitem.Text("Remove"); m_btnMakePending.Text("Queue saved");
   if(queue_edit && g_StudioHasStrategy) m_btnMakePending.Enable(); else m_btnMakePending.Disable();
   if(queue_edit && pending)
     {m_btnDelQitem.Enable(); m_btnCancelSelected.Enable(); m_btnUpQitem.Enable(); m_btnDownQitem.Enable();}
   else
     {m_btnDelQitem.Disable(); m_btnCancelSelected.Disable(); m_btnUpQitem.Disable(); m_btnDownQitem.Disable();}
   m_btnMakePending.Color(queue_edit && g_StudioHasStrategy ? C'225,238,248' : C'100,120,140');
   color qcolor=queue_edit && pending ? C'225,238,248' : C'100,120,140';
   m_btnDelQitem.Color(qcolor); m_btnCancelSelected.Color(qcolor); m_btnUpQitem.Color(qcolor); m_btnDownQitem.Color(qcolor);
  }

void CStrategyTesterDialog::ManagedSelectStrategy(void)
  {
   if(m_studioOwner!="human" || g_StudioPendingId!="" || !GOATIsLowerHex(g_StudioSchemaHash,64)) return;
   string files[];
   if(FileSelectDialog("Select strategy SET",NULL,"SET files (*.set)|*.set",FSD_FILE_MUST_EXIST|FSD_COMMON_FOLDER,files,NULL)<=0) return;
   int handle=FileOpen(files[0],FILE_READ|FILE_BIN|FILE_COMMON|FILE_SHARE_READ);
   if(handle==INVALID_HANDLE) {m_edtBatchErrors.Text("Unable to read selected SET from Common Files"); return;}
   ulong size=FileSize(handle); uchar bytes[];
   if(size<2 || size>2000000) {FileClose(handle); m_edtBatchErrors.Text("SET size is invalid"); return;}
   uint count=FileReadArray(handle,bytes,0,(uint)size); FileClose(handle);
   if(count!=(uint)size) {m_edtBatchErrors.Text("Incomplete SET read"); return;}
   string text="";
   if(bytes[0]==255 && bytes[1]==254)
     {
      if(count%2!=0) {m_edtBatchErrors.Text("Truncated UTF-16 SET"); return;}
      ushort wide[]; ArrayResize(wide,(int)count/2-1);
      for(int i=2;i<(int)count;i+=2) wide[i/2-1]=(ushort)(bytes[i]+256*bytes[i+1]);
      text=ShortArrayToString(wide,0,ArraySize(wide));
     }
   else
     {
      int offset=(count>=3 && bytes[0]==239 && bytes[1]==187 && bytes[2]==191 ? 3 : 0);
      text=CharArrayToString(bytes,offset,(int)count-offset,CP_UTF8);
     }
   string set_lines[],names[],values="{"; int n=StringSplit(text,'\n',set_lines),found=0;
   for(int i=0;i<n;i++)
     {
      string line=set_lines[i],trimmed=line;
      if(StringLen(line)>0 && StringSubstr(line,StringLen(line)-1)=="\r") line=StringSubstr(line,0,StringLen(line)-1);
      trimmed=line; StringTrimLeft(trimmed); StringTrimRight(trimmed);
      if(trimmed=="" || StringSubstr(trimmed,0,1)==";") continue;
      int equals=StringFind(line,"=");
      if(equals<1) {m_edtBatchErrors.Text("SET contains an invalid assignment"); return;}
      string name=StringSubstr(line,0,equals),value=StringSubstr(line,equals+1);
      for(int j=0;j<found;j++) if(names[j]==name) {m_edtBatchErrors.Text("Duplicate SET input: "+name); return;}
      ArrayResize(names,found+1); names[found]=name;
      values+=(found>0 ? "," : "")+GoatStudioQuote(name)+":"+GoatStudioQuote(value); found++;
     }
   if(found==0) {m_edtBatchErrors.Text("SET contains no inputs"); return;}
   values+="}";
   ManagedQueueSubmit("draft.replace_strategy","{\"schema_hash\":"+GoatStudioQuote(g_StudioSchemaHash)+",\"values\":"+values+"}");
  }

void CStrategyTesterDialog::ManagedQueueRefresh(void)
  {
   if(g_StudioSnapshot=="" || g_StudioSnapshot==g_StudioQueueRendered) return;
   SGOATJsonToken tokens[];
   if(!GOATJsonParse(g_StudioSnapshot,tokens,16384,2000000)) return;
   int state=GOATJsonFindField(g_StudioSnapshot,tokens,0,"state");
   int queue=GOATJsonFindField(g_StudioSnapshot,tokens,state,"queue");
   if(queue<0 || tokens[queue].type!=GOAT_JSON_ARRAY) return;
   string ids[],statuses[],labels[];
   for(int i=queue+1;i<ArraySize(tokens);i++)
     {
      if(tokens[i].parent!=queue) continue;
      string id,status,symbol,period;
      if(!GOATJsonGetString(g_StudioSnapshot,tokens,i,"job_id",id)
         || !GOATJsonGetString(g_StudioSnapshot,tokens,i,"status",status)) return;
      if(status=="removed" || status=="superseded") continue;
      int config=GOATJsonFindField(g_StudioSnapshot,tokens,i,"configuration");
      int tester=GOATJsonFindField(g_StudioSnapshot,tokens,config,"tester");
      if(!GOATJsonGetString(g_StudioSnapshot,tokens,tester,"Symbol",symbol)
         || !GOATJsonGetString(g_StudioSnapshot,tokens,tester,"Period",period)) return;
      int n=ArraySize(ids); ArrayResize(ids,n+1); ArrayResize(statuses,n+1); ArrayResize(labels,n+1);
      ids[n]=id; statuses[n]=status; labels[n]=status+" | "+symbol+" "+period+" | "+id;
     }
   string selected=""; int index=m_listQueue.Current();
   if(index>=0 && index<ArraySize(g_StudioQueueIds)) selected=g_StudioQueueIds[index];
   ArrayCopy(g_StudioQueueIds,ids); ArrayResize(g_StudioQueueIds,ArraySize(ids));
   ArrayCopy(g_StudioQueueStatuses,statuses); ArrayResize(g_StudioQueueStatuses,ArraySize(statuses));
   m_listQueue.ItemsClear();
   for(int i=0;i<ArraySize(ids);i++) {m_listQueue.AddItem(labels[i]); if(ids[i]==selected) m_listQueue.Select(i);}
   int pending_count=0,completed_count=0;
   for(int i=0;i<ArraySize(statuses);i++)
     {if(statuses[i]=="pending") pending_count++; if(statuses[i]=="completed") completed_count++;}
   m_lblQueue.Text("QUEUE: "+(string)pending_count+" pending / "+(string)completed_count+" completed");
   Id(Id()); // ItemsClear/AddItem can recreate the scrollbar after initial Run().
   g_StudioQueueRendered=g_StudioSnapshot; m_listQueue.Show();
  }

void CStrategyTesterDialog::ManagedQueueSubmit(const string command,const string payload)
  {
   if(m_studioOwner!="human" || g_StudioPendingId!="" || !ManagedPersistDraft())
     {m_edtBatchErrors.Text("Queue edit unavailable; retain control and wait for pending commands"); return;}
   string id="ui-"+(string)ChartID()+"-"+(string)GetMicrosecondCount(),hash;
   if(!g_StudioBridge.SubmitHuman(id,command,payload,hash,g_StudioQueueRevision,g_StudioQueueGeneration))
     {m_edtBatchErrors.Text("Unable to submit queue edit"); return;}
   g_StudioPendingId=id; g_StudioPendingHash=hash; g_StudioPendingCommand=command; g_StudioLastError="";
   m_edtBatchErrors.Text("Queue edit submitted; waiting for controller"); ManagedControls();
  }
void CStrategyTesterDialog::ManagedQueueEnqueue(void)
  {
   if(GetTESTERsettingsString(true)+GetExportSettingsString()!=m_studioBaseline)
     {m_edtBatchErrors.Text("Save your settings before queuing a job"); return;}
   ManagedQueueSubmit("queue.enqueue","{\"job_id\":"+GoatStudioQuote("job-"+(string)ChartID()+"-"+(string)GetMicrosecondCount())+"}");
  }
void CStrategyTesterDialog::ManagedQueueCancel(void)
  {
   int i=m_listQueue.Current(); if(i<0 || i>=ArraySize(g_StudioQueueIds)) return;
   ManagedQueueSubmit("queue.cancel","{\"job_id\":"+GoatStudioQuote(g_StudioQueueIds[i])+"}");
  }
void CStrategyTesterDialog::ManagedQueueRemove(void)
  {
   int i=m_listQueue.Current(); if(i<0 || i>=ArraySize(g_StudioQueueIds)) return;
   ManagedQueueSubmit("queue.remove","{\"job_id\":"+GoatStudioQuote(g_StudioQueueIds[i])+"}");
  }
void CStrategyTesterDialog::ManagedQueueUp(void) {ManagedQueueMove(-1);}
void CStrategyTesterDialog::ManagedQueueDown(void) {ManagedQueueMove(1);}
void CStrategyTesterDialog::ManagedQueueMove(const int direction)
  {
   int selected=m_listQueue.Current(); if(selected<0 || selected>=ArraySize(g_StudioQueueIds)) return;
   string ids[]; int index=-1;
   for(int i=0;i<ArraySize(g_StudioQueueIds);i++)
      if(g_StudioQueueStatuses[i]=="pending")
        {int n=ArraySize(ids); ArrayResize(ids,n+1); ids[n]=g_StudioQueueIds[i]; if(i==selected) index=n;}
   int target=index+direction; if(index<0 || target<0 || target>=ArraySize(ids)) return;
   string saved=ids[index]; ids[index]=ids[target]; ids[target]=saved;
   string payload="{\"job_ids\":[";
   for(int i=0;i<ArraySize(ids);i++) payload+=(i>0 ? "," : "")+GoatStudioQuote(ids[i]);
   ManagedQueueSubmit("queue.reorder",payload+"]}");
  }

bool CStrategyTesterDialog::ManagedPersistDraft(void)
  {
   if(!m_studioLoaded || !g_StudioBound || m_studioDraftFailed || g_StudioEditorLock==INVALID_HANDLE) return false;
   string body="{\"schema_version\":1,\"terminal_id\":"+GoatStudioQuote(g_StudioBridge.TerminalId())
      +",\"run_id\":"+GoatStudioQuote(g_StudioBridge.RunId())
      +",\"revision\":"+(string)m_studioRevision+",\"generation\":"+(string)m_studioGeneration
      +",\"tester_ini\":"+GoatStudioQuote(GetTESTERsettingsString(true))
      +",\"export_ini\":"+GoatStudioQuote(GetExportSettingsString())
      +",\"baseline\":"+GoatStudioQuote(m_studioBaseline)
      +",\"submitted\":"+GoatStudioQuote(m_studioSubmitted)+"}";
   string path=g_StudioBridge.DraftPath(),previous;
   if(GoatStudioReadUtf8(path,previous) && previous==body) return true;
   return GoatStudioWriteUtf8(path,body,true);
  }

bool CStrategyTesterDialog::ManagedRestoreDraft(void)
  {
   if(m_studioDraftChecked) return !m_studioDraftFailed;
   if(!g_StudioBound) return false;
   // The UI-state reader claims this handle before processing human receipts.
   // A process exit releases it; stale lock-file existence is not ownership.
   if(g_StudioEditorLock==INVALID_HANDLE) return false;
   m_studioDraftChecked=true;
   string path=g_StudioBridge.DraftPath();
   if(!FileIsExist(path)) return true;
   string body,terminal,run,tester,exports,baseline,submitted;
   long version,revision,generation; SGOATJsonToken tokens[];
   if(!GoatStudioReadUtf8(path,body) || !GOATJsonParse(body,tokens)
      || !GOATJsonGetInteger(body,tokens,0,"schema_version",version) || version!=1
      || !GOATJsonGetString(body,tokens,0,"terminal_id",terminal) || terminal!=g_StudioBridge.TerminalId()
      || !GOATJsonGetString(body,tokens,0,"run_id",run) || run!=g_StudioBridge.RunId()
      || !GOATJsonGetInteger(body,tokens,0,"revision",revision) || revision<0
      || !GOATJsonGetInteger(body,tokens,0,"generation",generation) || generation<0
      || !GOATJsonGetString(body,tokens,0,"tester_ini",tester)
      || !GOATJsonGetString(body,tokens,0,"export_ini",exports)
      || !GOATJsonGetString(body,tokens,0,"baseline",baseline)
      || !GOATJsonGetString(body,tokens,0,"submitted",submitted))
     {m_studioDraftFailed=true; return false;}
   string required="Expert,Symbol,Period,Model,ExecutionMode,Optimization,OptimizationCriterion,FromDate,ToDate,ForwardMode,Deposit,Currency,Leverage,Visual";
   string keys[]; int count=StringSplit(required,',',keys);
   for(int i=0;i<count;i++)
      if(StringFind("\n"+tester,"\n"+keys[i]+"=")<0) {m_studioDraftFailed=true; return false;}
   count=StringSplit(GoatStudioFields(true),',',keys);
   for(int i=0;i<count;i++)
      if(StringFind("\n"+exports,"\n"+keys[i]+"=")<0) {m_studioDraftFailed=true; return false;}
   ApplyTesterSettingsToControls(tester); ApplyExportSettingsToControls(exports);
   // Preserve empty/incomplete numeric text as an unsaved draft too.
   m_edtSetsToExport.Text(GoatOptReadIniValue(exports,"SetsToExport"));
   m_edtMinScore.Text(GoatOptReadIniValue(exports,"MinScore"));
   m_edtTargetDD.Text(GoatOptReadIniValue(exports,"TargetDD"));
   m_edtMinARF.Text(GoatOptReadIniValue(exports,"MinARF"));
   m_edtMinSR.Text(GoatOptReadIniValue(exports,"MinSR"));
   m_edtDeposit.Text(GoatOptReadIniValue(tester,"Deposit"));
   m_edtCurrency.Text(GoatOptReadIniValue(tester,"Currency"));
   m_studioBaseline=baseline; m_studioSubmitted=submitted;
   m_studioRevision=revision; m_studioGeneration=generation; m_studioLoaded=true;
   return true;
  }

void CStrategyTesterDialog::Destroy(const int reason)
  {
   if(GoatStudioManaged() && m_studioLoaded && !ManagedPersistDraft())
      Print("Studio: unable to persist unsaved draft; existing recovery file retained");
   if(g_StudioEditorLock!=INVALID_HANDLE) {FileClose(g_StudioEditorLock); g_StudioEditorLock=INVALID_HANDLE;}
   CAppDialog::Destroy(reason);
  }

void CStrategyTesterDialog::ManagedRefresh(void)
  {
   Caption("GOAT / OPTIMIZATION STUDIO / SHARED SETTINGS / "+GOAT_BUILD_MARKER+" Q350-FILL");
   string tester,exports,owner,status; long revision,generation; bool saved=false;
   string current=GetTESTERsettingsString(true)+GetExportSettingsString();
   if(m_studioLoaded && !ManagedPersistDraft())
     {m_edtBatchErrors.Text("Unable to preserve local draft; existing file retained"); return;}
   if(!GoatStudioUIState(tester,exports,owner,revision,generation,status,saved))
     {m_studioOwner=""; m_edtBatchErrors.Text(status); ManagedControls(); ManagedObservation(status); return;}
   if(!ManagedRestoreDraft())
     {m_studioOwner=""; ManagedControls(); m_edtBatchErrors.Text("Editor busy or draft recovery failed; local file retained"); return;}
   current=GetTESTERsettingsString(true)+GetExportSettingsString();
   if(saved)
     {
      // Edits made while saving stay dirty, but now build on our acknowledged revision.
      m_studioBaseline=m_studioSubmitted;
      m_studioRevision=revision; m_studioGeneration=generation;
     }
   bool dirty=m_studioLoaded && current!=m_studioBaseline;
   m_studioOwner=owner;
   if(!dirty)
     {
      if(!m_studioLoaded || revision!=m_studioRevision)
        {
         ApplyTesterSettingsToControls(tester); ApplyExportSettingsToControls(exports);
         m_studioBaseline=GetTESTERsettingsString(true)+GetExportSettingsString();
         m_studioRevision=revision; m_studioGeneration=generation; m_studioLoaded=true;
        }
     }
   else status+=" / Unsaved edits retained";
   m_edtBatchProgress.Text(status);
   m_edtBatchErrors.Text("Managed settings / native execution not connected");
   if(!ManagedPersistDraft()) status="Unable to preserve local draft; do not close Studio";
   else if(g_StudioReceiptResolved)
     {
      if(!g_StudioBridge.AcknowledgePending(g_StudioPendingId,g_StudioPendingHash))
         status="Settings recovered; unable to acknowledge local command journal";
      else
        {
         g_StudioPendingId=""; g_StudioPendingHash=""; g_StudioPendingCommand="";
         g_StudioReceiptResolved=false;
        }
     }
   m_edtBatchProgress.Text(status);
   ManagedQueueRefresh(); ManagedControls(); ManagedObservation(status); ChartRedraw(m_chart_id);
   GoatStudioDispatch();
  }

// Passive read: no clipboard, panel activation, cached child handles or idle heuristics.
string GoatStudioTesterState(void)
  {
   if(!MQLInfoInteger(MQL_DLLS_ALLOWED) || IsStopped()) return "unknown";
   long handle=MTTESTER::GetTerminalHandle();
   int ids[]={0xE81E,0x804E,0x2712,0x4196};
   for(int i=0;i<ArraySize(ids) && handle!=0;i++)
     {
      if(TerminalInfoInteger(TERMINAL_BUILD)>5000 && ids[i]==0xE81E) continue;
      handle=user32::GetDlgItem(handle,ids[i]);
     }
   if(handle==0) return "unknown";
   ushort caption[32]; ArrayInitialize(caption,0);
   if(user32::GetWindowTextW(handle,caption,32)<=0) return "unknown";
   string text=ShortArrayToString(caption);
   if(text=="Start" || text=="Старт") return "idle";
   if(text=="Stop" || text=="Стоп") return "running";
   return "unknown";
  }

void CStrategyTesterDialog::ManagedObservation(const string status)
  {
   string effective_tester="null";
   if(g_StudioBound && !GoatStudioINIJson(GetTESTERsettingsString(true),false,effective_tester)) effective_tester="null";
   string body="{\"schema_version\":1,\"build\":"+GoatStudioQuote(GOAT_BUILD_MARKER)
      +",\"queue_rows\":"+(string)ArraySize(g_StudioQueueIds)
      +",\"queue_first\":"+GoatStudioQuote(ArraySize(g_StudioQueueIds)>0 ? g_StudioQueueIds[0] : "")
      +",\"queue_last\":"+GoatStudioQuote(ArraySize(g_StudioQueueIds)>0 ? g_StudioQueueIds[ArraySize(g_StudioQueueIds)-1] : "")
      +",\"chart_id\":"+GoatStudioQuote((string)m_chart_id)
      +",\"loaded\":"+(m_studioLoaded ? "true" : "false")
      +",\"bound\":"+(g_StudioBound ? "true" : "false")
      +",\"revision\":"+(string)m_studioRevision+",\"generation\":"+(string)m_studioGeneration
      +",\"owner\":"+GoatStudioQuote(m_studioOwner)+",\"status\":"+GoatStudioQuote(status)
      +",\"layout_width\":"+(string)D_Width+",\"layout_height\":"+(string)D_Height
      +",\"dialog_width\":"+(string)Width()+",\"dialog_height\":"+(string)Height()
      +",\"chart_width\":"+(string)ChartGetInteger(m_chart_id,CHART_WIDTH_IN_PIXELS)
      +",\"chart_height\":"+(string)ChartGetInteger(m_chart_id,CHART_HEIGHT_IN_PIXELS)
      +",\"tester_ini\":"+GoatStudioQuote(GetTESTERsettingsString(true))
      +",\"export_ini\":"+GoatStudioQuote(GetExportSettingsString())
      +",\"effective_tester\":"+effective_tester
      +",\"pending_id\":"+GoatStudioQuote(g_StudioPendingId)
      +",\"runtime\":{\"data_path\":"+GoatStudioQuote(TerminalInfoString(TERMINAL_DATA_PATH))
      +",\"installation_path\":"+GoatStudioQuote(TerminalInfoString(TERMINAL_PATH))
      +",\"program_path\":"+GoatStudioQuote(MQLInfoString(MQL_PROGRAM_PATH))
      +",\"tester_state\":"+GoatStudioQuote(GoatStudioTesterState())
      +",\"terminal_build\":"+(string)TerminalInfoInteger(TERMINAL_BUILD)
      +",\"connected\":"+(TerminalInfoInteger(TERMINAL_CONNECTED) ? "true" : "false")
      +",\"terminal_trade_allowed\":"+(TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) ? "true" : "false")
      +",\"account_login\":"+GoatStudioQuote((string)AccountInfoInteger(ACCOUNT_LOGIN))
      +",\"account_server\":"+GoatStudioQuote(AccountInfoString(ACCOUNT_SERVER))
      +",\"account_demo\":"+(AccountInfoInteger(ACCOUNT_TRADE_MODE)==ACCOUNT_TRADE_MODE_DEMO ? "true" : "false")
      +",\"batch_ongoing\":"+(GlobalVariableCheck("BatchOnGoing") && GlobalVariableGet("BatchOnGoing")!=0 ? "true" : "false")
      +",\"restart_pending\":"+(GlobalVariableCheck("GOAT_BatchRestartPending") && GlobalVariableGet("GOAT_BatchRestartPending")!=0 ? "true" : "false")+"}";
   ulong now=GetTickCount64();
   if(body==g_StudioLastObservation && now-g_StudioObservationMillis<5000) return;
   string published=body+",\"observed_terminal_utc\":"+GoatStudioQuote(TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS))+"}";
   if(GoatStudioWriteUtf8("GOATStudio\\ui-observation.json",published,true))
     {g_StudioLastObservation=body; g_StudioObservationMillis=now;}
  }

void CStrategyTesterDialog::ManagedSave(void)
  {
   if(g_StudioPendingId!="") {m_edtBatchErrors.Text("Wait for the pending save receipt"); return;}
   string tester=GetTESTERsettingsString(true);
   string exports=GetExportSettingsString();
   m_studioSubmitted=GetTESTERsettingsString(true)+exports;
   if(!ManagedPersistDraft()) {m_edtBatchErrors.Text("Unable to persist draft before submission"); return;}
   if(GoatStudioUISubmit("draft.replace_configuration",tester,exports,m_studioRevision,m_studioGeneration))
     {m_studioSubmitted=GetTESTERsettingsString(true)+exports; m_edtBatchErrors.Text("Settings submitted; waiting for validation");}
   else m_edtBatchErrors.Text("Unable to submit: controller unavailable, pending request, or invalid numeric value");
  }
void CStrategyTesterDialog::ManagedTakeover(void)
  {
   if(!GoatStudioUISubmit("control.takeover","","",-1,-1)) m_edtBatchErrors.Text("Unable to request control");
  }
void CStrategyTesterDialog::ManagedGrant(void)
  {
   if(GetTESTERsettingsString(true)+GetExportSettingsString()!=m_studioBaseline)
     {m_edtBatchErrors.Text("Save or load saved settings before giving control to the agent"); return;}
   if(!GoatStudioUISubmit("control.grant_agent","","",m_studioRevision,m_studioGeneration)) m_edtBatchErrors.Text("Unable to hand over control");
  }
void CStrategyTesterDialog::ManagedReload(void)
  {
   if(g_StudioPendingId!="") {m_edtBatchErrors.Text("Wait for the pending command receipt"); return;}
   if(m_studioDraftFailed) {m_edtBatchErrors.Text("Recovery file needs review before discarding it"); return;}
   m_studioLoaded=false; ManagedRefresh();
  }
#include "GOATStudioDispatch.mqh"
#endif
