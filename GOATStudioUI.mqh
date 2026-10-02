#ifndef GOAT_STUDIO_UI_MQH
#define GOAT_STUDIO_UI_MQH
#include "GOATStudioBridge.mqh"
#include "GOATStudioNative.mqh"
#include "GOATStudioDraftDisplayPolicy.mqh"
#ifdef GOAT_CONTROL_FEEDBACK_V149
#include "GOATStudioControlFeedback.mqh"
#endif
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
#ifdef GOAT_MONITOR_ONBOARDING_V149
bool g_StudioEmptyDraft=false;
#endif
void GoatStudioDispatch(void);
#ifdef GOAT_ORPHAN_RECOVERY_V149
string GoatStudioRecoveryInstance(void);
void GoatStudioRecoveryObserveCurrent(void);
#endif

bool GoatStudioManaged(void)
  {
   // Explicit local opt-in, only in the already isolated monitor operating path.
   return g_GoatStudioReadOnlyMonitor && FileIsExist("GOATStudio\\active.json");
  }

string GoatStudioFields(const bool exports)
  {
#ifdef GOAT_SEQUENCE_EXPORT_V148
   // Preserve the strict eight-field protocol of older managed controllers.
   if(exports)
     {
      SGOATJsonToken snapshot[];
      if(GOATJsonParse(g_StudioSnapshot,snapshot,16384,2000000))
        {
         int state=GOATJsonFindField(g_StudioSnapshot,snapshot,0,"state");
         int draft=GOATJsonFindField(g_StudioSnapshot,snapshot,state,"export_draft");
         if(GOATJsonFindField(g_StudioSnapshot,snapshot,draft,"IncludeSequenceData")>=0)
            return "SetsToExport,MinScore,TargetDD,AdjustLots,BackOOSDate,MinARF,MinSR,IncludeBackOOS,IncludeSequenceData";
        }
     }
#endif
   return exports ? "SetsToExport,MinScore,TargetDD,AdjustLots,BackOOSDate,MinARF,MinSR,IncludeBackOOS"
      : "Expert,Symbol,Period,Model,ExecutionMode,Optimization,OptimizationCriterion,FromDate,ToDate,ForwardMode,ForwardDate,Deposit,Currency,Leverage,UseLocal,UseRemote,UseCloud,Visual";
  }

bool GoatStudioSectionINI(const string body,SGOATJsonToken &tokens[],const int section,const bool exports,string &ini)
  {
   ini="";
   if(section<0 || tokens[section].type!=GOAT_JSON_OBJECT) return false;
   string fieldNames=GoatStudioFields(exports);
#ifdef GOAT_SEQUENCE_EXPORT_V148
   // Incoming capabilities can differ from the previous local snapshot.
   if(exports && GOATJsonFindField(body,tokens,section,"IncludeSequenceData")>=0 && StringFind(fieldNames,",IncludeSequenceData")<0)
      fieldNames+=",IncludeSequenceData";
#endif
   string fields[]; int count=StringSplit(fieldNames,',',fields);
   for(int i=0;i<count;i++)
     {
      int token=GOATJsonFindField(body,tokens,section,fields[i]);
#ifdef GOAT_SEQUENCE_EXPORT_V148
      if(token<0 && exports && fields[i]=="IncludeSequenceData") {ini+="IncludeSequenceData=1\n";continue;}
#endif
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
   saved=false; g_StudioReceiptResolved=false; status="GOAT app not connected";
   if(!GoatStudioManaged()) return false;
   if(!g_StudioBound)
     {
      status="This chart is not linked to the GOAT app yet";
      string config,id,terminal,run,data; SGOATJsonToken cfg[];
      if(!GoatStudioReadUtf8("GOATStudio\\active.json",config) || !GOATJsonParse(config,cfg)
         || !GOATJsonGetString(config,cfg,0,"directory_id",id)
         || !GOATJsonGetString(config,cfg,0,"terminal_id",terminal)
         || !GOATJsonGetString(config,cfg,0,"run_id",run)
         || !GOATJsonGetString(config,cfg,0,"terminal_data_path",data)
         || data!=TerminalInfoString(TERMINAL_DATA_PATH)) return false;
      status="Cannot connect to the GOAT app on this PC";
      g_StudioBound=g_StudioBridge.Bind(id,terminal,run);
      if(!g_StudioBound) return false;
     }
   // Claim the editor before recovering/acknowledging any human command.
   if(g_StudioEditorLock==INVALID_HANDLE)
     {
      g_StudioEditorLock=FileOpen(g_StudioBridge.DraftPath()+".lock",FILE_READ|FILE_WRITE|FILE_BIN);
      if(g_StudioEditorLock==INVALID_HANDLE) {status="Another GOAT Studio chart is editing this run"; return false;}
     }
   string pending_id,pending_hash,pending_command;
   int pending=g_StudioBridge.RecoverPending(pending_id,pending_hash,pending_command);
   if(pending<0) {status="A saved request could not be recovered; kept for review"; return false;}
   if(pending==1)
     {g_StudioPendingId=pending_id; g_StudioPendingHash=pending_hash; g_StudioPendingCommand=pending_command;}
#ifdef GOAT_CONTROL_FEEDBACK_V149
   if(g_StudioPendingId!="") GoatStudioControlBegin(g_StudioPendingId,g_StudioPendingCommand);
#endif
   string body; SGOATJsonToken tokens[];
   status="Cannot read the GOAT app settings yet";
   if(!g_StudioBridge.ReadSnapshot(body) || !GOATJsonParse(body,tokens,16384,2000000)) return false;
   int state=GOATJsonFindField(body,tokens,0,"state");
   if(!GOATJsonGetString(body,tokens,state,"owner",owner)
      || !GOATJsonGetInteger(body,tokens,state,"revision",revision)
      || !GOATJsonGetInteger(body,tokens,state,"generation",generation)) return false;
   status=(owner=="human" ? "You control settings" : "Agent controls settings");
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
              {status="Waiting for the GOAT app to save the change"; return false;}
            acknowledged=committed;
           }
         saved=applied && acknowledged==revision && g_StudioPendingCommand=="draft.replace_configuration";
         if(applied && acknowledged<revision) g_StudioLastError="Newer settings arrived; review before saving your edits";
         if(!applied) {SGOATJsonToken rt[]; string error; if(GOATJsonParse(receipt,rt)&&GOATJsonGetString(receipt,rt,0,"error",error)) g_StudioLastError=error;}
#ifdef GOAT_CONTROL_FEEDBACK_V149
         if(g_StudioPendingCommand=="control.grant_agent" || g_StudioPendingCommand=="control.takeover")
            GoatStudioControlResolve(applied,applied ? "" : g_StudioLastError);
#endif
         // Keep the original request recoverable until the editor has durably
         // recorded its acknowledged baseline and any later unsaved edits.
         g_StudioReceiptResolved=true;
        }
      else status="Waiting for the GOAT app to confirm";
     }
   if(g_StudioLastError!="") status=g_StudioLastError;
   int tester_token=GOATJsonFindField(body,tokens,state,"tester_draft");
   int export_token=GOATJsonFindField(body,tokens,state,"export_draft");
#ifdef GOAT_MONITOR_ONBOARDING_V149
   // A valid empty binding permits HUMAN handoff before the agent creates
   // settings. Never synthesize settings or accept partial/malformed drafts.
   bool empty_draft=(tester_token>=0 && export_token>=0
      && tokens[tester_token].type==GOAT_JSON_NULL && tokens[export_token].type==GOAT_JSON_NULL);
   if(empty_draft)
     {
      int queue=GOATJsonFindField(body,tokens,state,"queue");
      int strategy=GOATJsonFindField(body,tokens,state,"strategy_draft");
      if(queue<0 || tokens[queue].type!=GOAT_JSON_ARRAY || strategy<0 || tokens[strategy].type!=GOAT_JSON_NULL)
         {status="GOAT app state is incomplete; ask your agent to repair it"; return false;}
      for(int q=queue+1;q<ArraySize(tokens);q++)
         if(tokens[q].parent==queue) {status="Queued work has no settings; ask your agent to check it"; return false;}
      tester=""; exports="";
      status=(owner=="human" ? "Ready to connect your agent" : "Agent connected; no settings yet");
      if(g_StudioPendingId!="" && !g_StudioReceiptResolved) status="Waiting for the GOAT app to confirm";
      if(g_StudioLastError!="") status=g_StudioLastError;
     }
   else
#endif
   if(!GoatStudioSectionINI(body,tokens,tester_token,false,tester)
      || !GoatStudioSectionINI(body,tokens,export_token,true,exports))
     {status="Settings are incomplete; ask your agent to repair setup"; return false;}
#ifdef GOAT_MONITOR_ONBOARDING_V149
   // Rejected snapshots must not change the accepted editor persistence mode.
   g_StudioEmptyDraft=empty_draft;
#endif
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
#ifdef GOAT_CONTROL_FEEDBACK_V149
   string feedback=GoatStudioControlText(owner);
   if(feedback!="") status=feedback;
#endif
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
      else if(key=="AdjustLots" || key=="IncludeBackOOS"
#ifdef GOAT_SEQUENCE_EXPORT_V148
              || key=="IncludeSequenceData"
#endif
             )
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
   g_StudioPendingId=id; g_StudioPendingHash=hash; g_StudioPendingCommand=command; g_StudioLastError="";
#ifdef GOAT_CONTROL_FEEDBACK_V149
   GoatStudioControlBegin(id,command);
#endif
   return true;
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
#ifdef GOAT_MONITOR_ONBOARDING_V149
   int width=(int)MathMax(160,cw-16);
#else
   int width=(int)MathMax(1000,cw-16);
#endif
#ifdef GOAT_MONITOR_ONBOARDING_V149
   int height=(int)MathMax(120,ch-52);
#else
   int height=(int)MathMax(480,ch-52);
#endif
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
#ifdef GOAT_MONITOR_ONBOARDING_V149
   if(!m_studioLoaded || g_StudioEmptyDraft || width<1000 || height<480)
     {ManagedControls(); return;}
   m_lblBatchControl.Text("BATCH CONTROL");
#endif
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
#ifdef GOAT_MONITOR_ONBOARDING_V149
   // "Delete All" has no managed handler, so it is hidden rather than shown dead.
   int gap=6,arrow=32,action=(qw-4*gap-2*arrow)/3;
   int x=qx;
   StageMove(m_btnDelQ,x,bottom,false,action,m_controlHeight);
#else
   int gap=6,arrow=32,action=(qw-5*gap-2*arrow)/4;
   int x=qx;
   StageMove(m_btnDelQ,x,bottom,true,action,m_controlHeight); x+=action+gap;
#endif
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
#ifdef GOAT_MONITOR_ONBOARDING_V149
   bool handoff=edit && g_StudioPendingId=="";
   edit=edit && !g_StudioEmptyDraft;
#endif
   m_btnStart.Text("TAKE CONTROL"); m_btnStart.Enable();
   m_btnStop.Text("GIVE TO AGENT");
   m_btnAddQueue.Text("SAVE SETTINGS"); m_btnSetPresets.Text("DISCARD EDITS");
   m_btnSetPresets.Enable();
   if(edit) {m_btnAddQueue.Enable(); m_btnStop.Enable();}
   else {m_btnAddQueue.Disable(); m_btnStop.Disable();}
#ifdef GOAT_MONITOR_ONBOARDING_V149
   if(handoff) m_btnStop.Enable(); else m_btnStop.Disable();
#endif
   // All other actions remain disabled by the monitor's base layout.
   if(edit)
     {
      m_cmbSymbol.Enable(); m_cmbPeriod.Enable(); m_dtFrom.Enable(); m_dtTo.Enable();
      m_cmbForward.Enable(); if(m_cmbForward.Select()=="Custom") m_dtForward.Enable();
      m_cmbDelay.Enable(); m_cmbModel.Enable(); m_edtDeposit.Enable(); m_edtCurrency.Enable();
      m_cmbLeverage.Enable(); m_edtSetsToExport.Enable(); m_dpBackOOS.Enable();
      m_edtMinScore.Enable(); m_edtMinARF.Enable(); m_edtTargetDD.Enable(); m_edtMinSR.Enable();
      m_chkAdjustLots.Enable(); m_chkVerifyOOS.Enable();
#ifdef GOAT_SEQUENCE_EXPORT_V148
      if(StringFind(GoatStudioFields(true),",IncludeSequenceData")>=0) m_chkSequenceData.Enable();
      else m_chkSequenceData.Disable();
#endif

     }
   else
     {
      m_cmbSymbol.Disable(); m_cmbPeriod.Disable(); m_dtFrom.Disable(); m_dtTo.Disable();
      m_cmbForward.Disable(); m_dtForward.Disable(); m_cmbDelay.Disable(); m_cmbModel.Disable();
      m_edtDeposit.Disable(); m_edtCurrency.Disable(); m_cmbLeverage.Disable();
      m_edtSetsToExport.Disable(); m_dpBackOOS.Disable(); m_edtMinScore.Disable();
      m_edtMinARF.Disable(); m_edtTargetDD.Disable(); m_edtMinSR.Disable();
      m_chkAdjustLots.Disable(); m_chkVerifyOOS.Disable();
#ifdef GOAT_SEQUENCE_EXPORT_V148
      m_chkSequenceData.Disable();
#endif

     }
   m_btnStart.Color(C'225,238,248'); m_btnSetPresets.Color(C'225,238,248');
   m_btnAddQueue.Color(edit ? C'225,238,248' : C'100,120,140');
   m_btnStop.Color(edit ? C'225,238,248' : C'100,120,140');
#ifdef GOAT_MONITOR_ONBOARDING_V149
   // Handoff buttons are not START/TERMINATE: "Take control" is a secondary outline
   // action, never the green go button; red stays reserved for stop/cancel.
   m_btnStart.ColorBackground(C'15,17,19'); m_btnStart.ColorBorder(C'201,163,91');
   m_btnStop.ColorBackground(C'15,17,19'); m_btnStop.ColorBorder(C'60,64,70');
#endif
   GoatStudioComboTheme(m_cmbSymbol,m_activeStage==0,edit);
   GoatStudioComboTheme(m_cmbPeriod,m_activeStage==0,edit);
   GoatStudioComboTheme(m_cmbForward,m_activeStage==1,edit);
   GoatStudioComboTheme(m_cmbDelay,m_activeStage==2,edit);
   GoatStudioComboTheme(m_cmbModel,m_activeStage==2,edit);
   GoatStudioComboTheme(m_cmbLeverage,m_activeStage==2,edit);
   if(m_activeStage!=1) {m_dtFrom.Hide(); m_dtTo.Hide(); m_dtForward.Hide();}
   if(m_activeStage!=3) {m_dpBackOOS.Hide(); m_chkAdjustLots.Hide(); m_chkVerifyOOS.Hide();}
#ifdef GOAT_SEQUENCE_EXPORT_V148
   if(m_activeStage!=3) m_chkSequenceData.Hide();
#endif

#ifdef GOAT_SEQUENCE_EXPORT_V148
   bool sequenceSupported=StringFind(GoatStudioFields(true),",IncludeSequenceData")>=0;
   m_lblSequenceCost.Text(sequenceSupported ? "Adds export time and disk use; off requires a later capture." : "This controller cannot change sequence-data export settings.");
#endif
   int selected=m_listQueue.Current();
   bool pending=selected>=0 && selected<ArraySize(g_StudioQueueStatuses) && g_StudioQueueStatuses[selected]=="pending";
   bool queue_edit=edit && g_StudioPendingId=="";
   if(queue_edit && GOATIsLowerHex(g_StudioSchemaHash,64)) m_btnSelectFile.Enable(); else m_btnSelectFile.Disable();
   m_btnSelectFile.Color(queue_edit ? C'225,238,248' : C'100,120,140');
   m_edtStrategy.Text(g_StudioHasStrategy ? g_StudioStrategyName : "Select a strategy SET file");
   m_btnDelQitem.Text("Remove"); m_btnMakePending.Text("Add to queue");
   if(queue_edit && g_StudioHasStrategy) m_btnMakePending.Enable(); else m_btnMakePending.Disable();
   if(queue_edit && pending)
     {m_btnDelQitem.Enable(); m_btnCancelSelected.Enable(); m_btnUpQitem.Enable(); m_btnDownQitem.Enable();}
   else
     {m_btnDelQitem.Disable(); m_btnCancelSelected.Disable(); m_btnUpQitem.Disable(); m_btnDownQitem.Disable();}
   m_btnMakePending.Color(queue_edit && g_StudioHasStrategy ? C'225,238,248' : C'100,120,140');
   color qcolor=queue_edit && pending ? C'225,238,248' : C'100,120,140';
   m_btnDelQitem.Color(qcolor); m_btnCancelSelected.Color(qcolor); m_btnUpQitem.Color(qcolor); m_btnDownQitem.Color(qcolor);
#ifdef GOAT_MONITOR_ONBOARDING_V149
   // Keep handoff visible without showing empty settings or off-screen actions.
   if(!m_studioLoaded || g_StudioEmptyDraft || D_Width<1000 || D_Height<480)
     {
      // CDialog::Add registers every form control in m_client_area.
      // c_Wnd_OPT is only a sibling backdrop, not their parent.
      for(int i=0;i<m_client_area.ControlsTotal();i++)
        {CWnd *child=m_client_area.Control(i); if(child!=NULL) child.Hide();}
      // Restore the client-area backdrop before the foreground controls.
      StageMove(c_Wnd_OPT,0,0,true,D_Width-16,D_Height-4);
      c_Wnd_Export.Hide();
      int w=(int)MathMax(100,D_Width-48);
      m_lblHeading.Text("GOAT / AGENT CONNECTION");
      StageMove(m_lblHeading,16,12,true,w,26);
      StageMove(m_edtBatchProgress,16,48,true,w,26);
      m_btnStop.Text("GIVE TO AGENT");
      m_btnStop.Color(handoff ? C'225,238,248' : C'100,120,140');
      StageMove(m_btnStop,16,86,true,w,36);
      m_btnStart.Text("TAKE CONTROL");
      StageMove(m_btnStart,16,130,m_studioOwner=="agent",w,32);
      // Say what is queued here, including an armed batch flag with nothing queued.
      m_lblBatchControl.Text(StringFind(m_lblQueue.Text(),"BATCH ")==0 ? m_lblQueue.Text()
         : (GlobalVariableGet("BatchOnGoing")!=0 && ArraySize(g_StudioQueueIds)==0
            ? "A batch flag is set, but nothing is queued here." : "No batch queued yet. Your agent prepares it."));
      StageMove(m_lblBatchControl,16,174,D_Height>=230,w,26);
      StageMove(m_edtBatchErrors,16,208,D_Height>=270,w,26);
      StageMove(m_listQueue,16,250,!g_StudioEmptyDraft && D_Height>=350,w,D_Height-274);
      m_listQueue.FitRows(m_rowHeight-1,Font_Size);
     }
#endif
#ifdef GOAT_CONTROL_FEEDBACK_V149
   // Apply after both layouts so compact reflow cannot erase click feedback.
   if(g_StudioPendingId!="")
     {
      m_btnStart.Disable(); m_btnStop.Disable();
      if(g_StudioPendingCommand=="control.grant_agent") m_btnStop.Text("CONNECTING...");
      if(g_StudioPendingCommand=="control.takeover") m_btnStart.Text("TAKING CONTROL...");
     }
   else if(m_studioOwner=="agent")
     {
      // A healthy state, shown as a status chip rather than a red disabled button.
      m_btnStop.Text("AGENT CONNECTED"); m_btnStop.Color(C'190,242,100'); m_btnStop.ColorBorder(C'190,242,100');
     }
   else if(m_studioOwner=="human" && g_StudioControlOutcome==2
           && g_StudioControlCommand=="control.takeover")
      m_btnStop.Text("GIVE BACK TO AGENT");
#endif
#ifdef GOAT_MONITOR_ONBOARDING_V149
   // The positive handoff is the primary action: lime fill, graphite text.
   if(handoff)
     {m_btnStop.ColorBackground(C'190,242,100'); m_btnStop.ColorBorder(C'190,242,100'); m_btnStop.Color(C'11,12,14');}
#endif
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

// Plain words for controller and native queue states; unknown states stay visible as-is.
string GoatStudioStatusWord(const string status)
  {
   if(status=="pending" || status=="queued") return "Waiting";
   if(status=="reserved" || status=="starting" || status=="running" || status=="ongoing") return "Running";
   if(status=="verifying") return "Verifying";
   if(status=="reconcile_required") return "Needs reconcile";
   if(status=="completed") return "Done";
   if(status=="failed") return "Failed";
   if(status=="error") return "Error";
   if(status=="cancelled") return "Cancelled";
   if(status=="unobserved") return "Not seen yet";
   return status;
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
      ids[n]=id; statuses[n]=status; labels[n]=GoatStudioStatusWord(status)+" | "+symbol+" "+period+" | "+id;
     }
   string batch_heading="";
   int batch=GOATJsonFindField(g_StudioSnapshot,tokens,state,"batch_view");
   if(batch>=0)
     {
      long total=0,done=0,failed=0,cancelled=0,remaining=0,active=0;
      if(GOATJsonGetInteger(g_StudioSnapshot,tokens,batch,"total",total)
         && GOATJsonGetInteger(g_StudioSnapshot,tokens,batch,"completed",done)
         && GOATJsonGetInteger(g_StudioSnapshot,tokens,batch,"failed",failed)
         && GOATJsonGetInteger(g_StudioSnapshot,tokens,batch,"cancelled",cancelled)
         && GOATJsonGetInteger(g_StudioSnapshot,tokens,batch,"remaining",remaining)
         && GOATJsonGetInteger(g_StudioSnapshot,tokens,batch,"active",active))
         // Fits MT5's 63-character edit cut with four-digit counts; running shows in the rows.
         batch_heading="BATCH "+(string)done+"/"+(string)total+" done | "+(string)remaining+" left | "+(string)failed+" errors | "+(string)cancelled+" cancelled";
      int members=GOATJsonFindField(g_StudioSnapshot,tokens,batch,"members");
      if(members>=0 && tokens[members].type==GOAT_JSON_ARRAY)
         for(int i=members+1;i<ArraySize(tokens);i++)
           {
            if(tokens[i].parent!=members) continue;
            long member_index=0,model=0; string symbol,period,status,strategy;
            if(!GOATJsonGetInteger(g_StudioSnapshot,tokens,i,"index",member_index)
               || !GOATJsonGetInteger(g_StudioSnapshot,tokens,i,"model",model)
               || !GOATJsonGetString(g_StudioSnapshot,tokens,i,"symbol",symbol)
               || !GOATJsonGetString(g_StudioSnapshot,tokens,i,"period",period)
               || !GOATJsonGetString(g_StudioSnapshot,tokens,i,"status",status)
               || !GOATJsonGetString(g_StudioSnapshot,tokens,i,"strategy",strategy)) continue;
            string model_label=(model==1 ? "OHLC" : model==4 ? "real ticks" : model==0 ? "every tick" : "open prices");
            int n=ArraySize(ids); ArrayResize(ids,n+1); ArrayResize(statuses,n+1); ArrayResize(labels,n+1);
            // Display-only children never address a parent queue command.
            ids[n]=""; statuses[n]="member";
            labels[n]="  "+(string)(member_index+1)+" of "+(string)total+" | "+GoatStudioStatusWord(status)+" | "+symbol+" "+period+" | "+model_label+" | "+strategy;
           }
     }
   string selected=""; int index=m_listQueue.Current();
   if(index>=0 && index<ArraySize(g_StudioQueueIds)) selected=g_StudioQueueIds[index];
   ArrayCopy(g_StudioQueueIds,ids); ArrayResize(g_StudioQueueIds,ArraySize(ids));
   ArrayCopy(g_StudioQueueStatuses,statuses); ArrayResize(g_StudioQueueStatuses,ArraySize(statuses));
   m_listQueue.ItemsClear();
   for(int i=0;i<ArraySize(ids);i++) {m_listQueue.AddItem(labels[i]); if(selected!="" && ids[i]==selected) m_listQueue.Select(i);}
   int pending_count=0,completed_count=0;
   for(int i=0;i<ArraySize(statuses);i++)
     {if(statuses[i]=="pending") pending_count++; if(statuses[i]=="completed") completed_count++;}
   m_lblQueue.Text(batch_heading!="" ? batch_heading : "QUEUE: "+(string)pending_count+" pending / "+(string)completed_count+" completed");
   Id(Id()); // ItemsClear/AddItem can recreate the scrollbar after initial Run().
   g_StudioQueueRendered=g_StudioSnapshot; m_listQueue.Show();
  }

void CStrategyTesterDialog::ManagedQueueSubmit(const string command,const string payload)
  {
   if(m_studioOwner!="human" || g_StudioPendingId!="" || !ManagedPersistDraft())
     {m_edtBatchErrors.Text("Can't edit the queue now; wait for the pending request"); return;}
   string id="ui-"+(string)ChartID()+"-"+(string)GetMicrosecondCount(),hash;
   if(!g_StudioBridge.SubmitHuman(id,command,payload,hash,g_StudioQueueRevision,g_StudioQueueGeneration))
     {m_edtBatchErrors.Text("Unable to submit queue edit"); return;}
   g_StudioPendingId=id; g_StudioPendingHash=hash; g_StudioPendingCommand=command; g_StudioLastError="";
   m_edtBatchErrors.Text("Queue change sent; waiting for the GOAT app"); ManagedControls();
  }
// Report is generated from the scoped output root, not an editable setting.
// Preserve every other byte, including actual tester/export edits and headers.
bool GoatStudioSameDraftSettings(const string current,const string baseline)
  {
   if(current==baseline) return true;
   int current_start=StringFind(current,"\nReport="),baseline_start=StringFind(baseline,"\nReport=");
   if(current_start<0 || baseline_start<0) return false;
   int current_value=current_start+8,baseline_value=baseline_start+8;
   int current_end=StringFind(current,"\n",current_value),baseline_end=StringFind(baseline,"\n",baseline_value);
   if(current_end<=current_value || baseline_end<=baseline_value
      || StringFind(current,"\nReport=",current_value)>=0
      || StringFind(baseline,"\nReport=",baseline_value)>=0) return false;
   return StringSubstr(current,0,current_value)==StringSubstr(baseline,0,baseline_value)
      && StringSubstr(current,current_end)==StringSubstr(baseline,baseline_end);
  }
void CStrategyTesterDialog::ManagedQueueEnqueue(void)
  {
   if(!GoatStudioSameDraftSettings(GetTESTERsettingsString(true)+GetExportSettingsString(),m_studioBaseline))
     {m_edtBatchErrors.Text("Save your settings before queuing a job"); return;}
   ManagedQueueSubmit("queue.enqueue","{\"job_id\":"+GoatStudioQuote("job-"+(string)ChartID()+"-"+(string)GetMicrosecondCount())+"}");
  }
void CStrategyTesterDialog::ManagedQueueCancel(void)
  {
   int i=m_listQueue.Current(); if(i<0 || i>=ArraySize(g_StudioQueueIds)) return;
   if(g_StudioQueueIds[i]=="") return;
   ManagedQueueSubmit("queue.cancel","{\"job_id\":"+GoatStudioQuote(g_StudioQueueIds[i])+"}");
  }
void CStrategyTesterDialog::ManagedQueueRemove(void)
  {
   int i=m_listQueue.Current(); if(i<0 || i>=ArraySize(g_StudioQueueIds)) return;
   if(g_StudioQueueIds[i]=="") return;
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

string CStrategyTesterDialog::ManagedDraftBody(void)
  {
   return "{\"schema_version\":1,\"terminal_id\":"+GoatStudioQuote(g_StudioBridge.TerminalId())
      +",\"run_id\":"+GoatStudioQuote(g_StudioBridge.RunId())
      +",\"revision\":"+(string)m_studioRevision+",\"generation\":"+(string)m_studioGeneration
      +",\"tester_ini\":"+GoatStudioQuote(GetTESTERsettingsString(true))
      +",\"export_ini\":"+GoatStudioQuote(GetExportSettingsString())
      +",\"baseline\":"+GoatStudioQuote(m_studioBaseline)
      +",\"submitted\":"+GoatStudioQuote(m_studioSubmitted)+"}";
  }

bool CStrategyTesterDialog::ManagedPersistDraft(void)
  {
   // Read-only agent mirrors must not serialize committed fields over a retained
   // human draft, including during refresh or dialog destruction.
   if(!GoatStudioHumanDraftIO(m_studioOwner=="human")) return true;
   if(!m_studioLoaded || !g_StudioBound || m_studioDraftFailed || g_StudioEditorLock==INVALID_HANDLE) return false;
#ifdef GOAT_MONITOR_ONBOARDING_V149
   // Empty setup must not persist stale UI defaults as user settings.
   if(g_StudioEmptyDraft) return !FileIsExist(g_StudioBridge.DraftPath());
#endif
   string body=ManagedDraftBody();
   // Restoring or displaying an editor is not a human edit. Retain the exact
   // old file bytes/format until its represented content or metadata changes.
   if(body==m_studioRetainedDraftBody) return true;
   string path=g_StudioBridge.DraftPath(),previous;
   if(GoatStudioReadUtf8(path,previous) && previous==body)
     {m_studioRetainedDraftBody=body; return true;}
   if(!GoatStudioWriteUtf8(path,body,true)) return false;
   m_studioRetainedDraftBody=body; return true;
  }

bool CStrategyTesterDialog::ManagedRestoreDraft(void)
  {
   if(!GoatStudioHumanDraftIO(m_studioOwner=="human")) return true;
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
   m_studioRetainedDraftBody=ManagedDraftBody();
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
#ifndef GOAT_MONITOR_ONBOARDING_V149
   // V1.49: the monitor timer owns one caption (account, build, mode); no flicker.
   Caption("GOAT / OPTIMIZATION STUDIO / SHARED SETTINGS / "+GOAT_BUILD_MARKER+" Q350-FILL");
#endif
#ifdef GOAT_MONITOR_ONBOARDING_V149
   ManagedResize();
#endif
   string tester,exports,owner,status; long revision,generation; bool saved=false;
   string current=GetTESTERsettingsString(true)+GetExportSettingsString();
   if(m_studioLoaded && !ManagedPersistDraft())
     {m_edtBatchErrors.Text("Unable to preserve local draft; existing file retained"); return;}
   if(!GoatStudioUIState(tester,exports,owner,revision,generation,status,saved))
     {m_studioOwner=""; m_edtBatchErrors.Text(status); m_edtBatchProgress.Text("Setup needs repair; your agent can inspect it"); ManagedControls(); ManagedObservation(status); return;}
#ifdef GOAT_MONITOR_ONBOARDING_V149
   if(g_StudioEmptyDraft && FileIsExist(g_StudioBridge.DraftPath()))
     {m_studioOwner=""; m_studioDraftFailed=true; m_edtBatchProgress.Text("Saved edits need recovery; ask your agent"); ManagedControls(); ManagedObservation("Empty state conflicts with saved draft"); return;}
#endif
   // Preserve and re-read retained edits when a human regains the editor. Agent
   // snapshot hydration never changes the on-disk draft or its old revision.
   if(owner=="human" && m_studioOwner!="human")
     {m_studioDraftChecked=false; m_studioDraftFailed=false;}
   m_studioOwner=owner;
   if(!ManagedRestoreDraft())
     {m_studioOwner=""; ManagedControls(); m_edtBatchErrors.Text("Editor busy or draft recovery failed; local file retained"); return;}
   current=GetTESTERsettingsString(true)+GetExportSettingsString();
   bool agent_mirror=(owner=="agent");
   if(saved && !agent_mirror)
     {
      // Edits made while saving stay dirty, but now build on our acknowledged revision.
      m_studioBaseline=m_studioSubmitted;
      m_studioRevision=revision; m_studioGeneration=generation;
     }
   bool dirty=m_studioLoaded && !GoatStudioSameDraftSettings(current,m_studioBaseline);
   if(GoatStudioHydrateSnapshot(agent_mirror,dirty,m_studioLoaded,
                               revision!=m_studioRevision || generation!=m_studioGeneration))
     {
#ifdef GOAT_MONITOR_ONBOARDING_V149
         if(!g_StudioEmptyDraft)
#endif
           {ApplyTesterSettingsToControls(tester); ApplyExportSettingsToControls(exports);}
         m_studioBaseline=GetTESTERsettingsString(true)+GetExportSettingsString();
         m_studioRevision=revision; m_studioGeneration=generation; m_studioLoaded=true;
     }
   else if(dirty) status+="; unsaved edits (not used yet)";
   // Under 60 characters: MT5 cuts status fields at 63. An empty agent draft has
   // no settings to show, so it never claims to be showing them.
   bool show_agent_settings=agent_mirror;
#ifdef GOAT_MONITOR_ONBOARDING_V149
   show_agent_settings=show_agent_settings && !g_StudioEmptyDraft;
#endif
   if(show_agent_settings)
     {
      status+=" (view only)";
      if(FileIsExist(g_StudioBridge.DraftPath())) status+="; your draft is kept";
     }
   m_edtBatchProgress.Text(status);
#ifdef GOAT_MONITOR_ONBOARDING_V149
   m_edtBatchErrors.Text(MQLInfoInteger(MQL_DLLS_ALLOWED) ? "Connecting an agent does not enable trading."
                         : "DLL imports are off; your agent can't start batches here.");
#else
   m_edtBatchErrors.Text("Managed settings / native execution not connected");
#endif
   if(!ManagedPersistDraft()) status="Unable to preserve local draft; do not close Studio";
   else if(g_StudioReceiptResolved)
     {
      if(!g_StudioBridge.AcknowledgePending(g_StudioPendingId,g_StudioPendingHash))
         status="Settings recovered; could not close the request record";
      else
        {
         g_StudioPendingId=""; g_StudioPendingHash=""; g_StudioPendingCommand="";
         g_StudioReceiptResolved=false;
        }
     }
   m_edtBatchProgress.Text(status);
   ManagedQueueRefresh();
#ifdef GOAT_MONITOR_ONBOARDING_V149
   ManagedResize();
#endif
   ManagedControls(); ManagedObservation(status); ChartRedraw(m_chart_id);
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
#ifdef GOAT_ORPHAN_RECOVERY_V149
   body+=" ,\"recovery_capability\":{\"protocol\":1,\"ea_version\":"+GoatStudioQuote(GOAT_VERSION_LABEL)
      +",\"monitor_instance\":"+GoatStudioQuote(GoatStudioRecoveryInstance())
      +",\"terminal_running\":"+(GlobalVariableGet("TerminalRunning")!=0 ? "true" : "false")+"}";
#endif
   ulong now=GetTickCount64();
   if(body==g_StudioLastObservation && now-g_StudioObservationMillis<5000) return;
   string published=body+",\"observed_terminal_utc\":"+GoatStudioQuote(TimeToString(TimeGMT(),TIME_DATE|TIME_SECONDS))+"}";
   if(GoatStudioWriteUtf8("GOATStudio\\ui-observation.json",published,true))
     {g_StudioLastObservation=body; g_StudioObservationMillis=now;}
#ifdef GOAT_ORPHAN_RECOVERY_V149
   // Observe only the current inert monitor; never replay or attribute an old request.
   if(g_GoatStudioReadOnlyMonitor && g_StudioBound && m_studioLoaded
      && GlobalVariableGet("BatchOnGoing")!=0) GoatStudioRecoveryObserveCurrent();
#endif
  }

void CStrategyTesterDialog::ManagedSave(void)
  {
   if(g_StudioPendingId!="") {m_edtBatchErrors.Text("Wait for the pending save to be confirmed"); return;}
   string tester=GetTESTERsettingsString(true);
   string exports=GetExportSettingsString();
   m_studioSubmitted=GetTESTERsettingsString(true)+exports;
   if(!ManagedPersistDraft()) {m_edtBatchErrors.Text("Unable to persist draft before submission"); return;}
   if(GoatStudioUISubmit("draft.replace_configuration",tester,exports,m_studioRevision,m_studioGeneration))
     {m_studioSubmitted=GetTESTERsettingsString(true)+exports; m_edtBatchErrors.Text("Settings submitted; waiting for validation");}
   else m_edtBatchErrors.Text("Not sent: app offline, request pending or invalid number");
  }
void CStrategyTesterDialog::ManagedTakeover(void)
  {
   if(m_studioOwner!="agent" || g_StudioPendingId!="") return;
   int confirmation=MessageBox("This stops the agent's research and cancels its permission. Continue?",
      "Take Control",MB_YESNO|MB_ICONWARNING|MB_DEFBUTTON2);
   if(confirmation!=IDYES)
     {m_edtBatchProgress.Text("Take control cancelled; agent remains connected"); ChartRedraw(m_chart_id); return;}
   if(!GoatStudioUISubmit("control.takeover","","",-1,-1))
     {
      m_edtBatchErrors.Text("Unable to request control");
#ifdef GOAT_CONTROL_FEEDBACK_V149
      GoatStudioControlFailure(g_StudioPendingId!="" ? "wait for the pending request" : "can't reach the GOAT app; is it open?");
#endif
     }
#ifdef GOAT_CONTROL_FEEDBACK_V149
   m_edtBatchProgress.Text(GoatStudioControlText(m_studioOwner));
   ManagedControls(); ChartRedraw(m_chart_id);
#endif
  }
void CStrategyTesterDialog::ManagedGrant(void)
  {
   if(!GoatStudioSameDraftSettings(GetTESTERsettingsString(true)+GetExportSettingsString(),m_studioBaseline))
     {
      m_edtBatchErrors.Text("Save or discard your edits before giving control to the agent");
#ifdef GOAT_CONTROL_FEEDBACK_V149
      GoatStudioControlFailure("save or discard your edits first");
      m_edtBatchProgress.Text(GoatStudioControlText(m_studioOwner)); ChartRedraw(m_chart_id);
#endif
      return;
     }
   if(!GoatStudioUISubmit("control.grant_agent","","",m_studioRevision,m_studioGeneration))
     {
      m_edtBatchErrors.Text("Unable to hand over control");
#ifdef GOAT_CONTROL_FEEDBACK_V149
      GoatStudioControlFailure(g_StudioPendingId!="" ? "wait for the pending request" : "can't reach the GOAT app; is it open?");
#endif
     }
#ifdef GOAT_CONTROL_FEEDBACK_V149
   m_edtBatchProgress.Text(GoatStudioControlText(m_studioOwner));
   ManagedControls(); ChartRedraw(m_chart_id);
#endif
  }
void CStrategyTesterDialog::ManagedReload(void)
  {
   if(g_StudioPendingId!="") {m_edtBatchErrors.Text("Wait for the pending request to be confirmed"); return;}
   if(m_studioDraftFailed) {m_edtBatchErrors.Text("Recovery file needs review before discarding it"); return;}
   m_studioLoaded=false; ManagedRefresh();
  }
#include "GOATStudioDispatch.mqh"
#endif
