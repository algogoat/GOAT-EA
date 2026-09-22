// Production OnInit only: no cached admission, trading, or activation side effects.
bool GOATLicenseIdentityMatches(const long account,const string server)
  {
   return(!IsStopped() && account>0 && AccountInfoInteger(ACCOUNT_LOGIN)==account
          && AccountInfoString(ACCOUNT_SERVER)==server);
  }

bool GOATLicenseWait(const int milliseconds,const ulong deadline,const long account,const string server)
  {
   ulong until=GetTickCount64()+(ulong)milliseconds;
   while(GetTickCount64()<until)
     {
      ulong now=GetTickCount64();
      if(now>=deadline || !GOATLicenseIdentityMatches(account,server)) return false;
      Sleep((int)MathMin(100.0,(double)MathMin(until-now,deadline-now)));
     }
   return(GetTickCount64()<deadline && GOATLicenseIdentityMatches(account,server));
  }

int GOATLicenseAuthenticatedRequest(const long account,const string server,const bool initializing,
                                  const string url,char &body[],char &result[],string &response_headers,int &native_error)
  {
   native_error=0;
   bool retry=initializing && !MQLInfoInteger(MQL_TESTER) && !MQLInfoInteger(MQL_OPTIMIZATION)
              && !MQLInfoInteger(MQL_FORWARD);
   ulong deadline=GetTickCount64()+60000;
   uint spread=(uint)ChartID()^(uint)(ChartID()>>32)^(uint)account;
   spread*=2654435761;
   int jitter=(int)(spread%2001);
   int delay=(retry ? (int)(spread%7001) : 0);
   int attempts=(retry ? 4 : 1);
   int status=-2;
   for(int attempt=0;attempt<attempts;attempt++)
     {
      if(!GOATLicenseWait(delay,deadline,account,server)) return -2;
      string headers="";
      if(!GOATBuildAuthenticatedRequestHeaders(headers)) return 401;
      ulong now=GetTickCount64();
      if(now>=deadline || !GOATLicenseIdentityMatches(account,server)) return -2;
      int request_timeout=(int)MathMin((double)MathMax(1,timeout),(double)(deadline-now));
      ArrayResize(result,0); response_headers="";
      ResetLastError();
      status=WebRequest("POST",url,headers,request_timeout,body,result,response_headers);
      native_error=(status==-1 ? GetLastError() : 0);
      headers="";
      if(!GOATLicenseIdentityMatches(account,server) || GetTickCount64()>=deadline) return -2;
      bool transient=(status==1003 || status==408 || status==429 || (status>=500 && status<=599)
                      || (status==-1 && (native_error==5201 || native_error==5202 || native_error==5203)));
      if(!retry || !transient || attempt+1>=attempts) return status;
      delay=(2000<<attempt)+jitter;
      // Respect bounded numeric Retry-After; an unsupported date or long wait stops this init.
      if(StringLen(response_headers)>8192) return status;
      string retry_header_lines[];
      int count=StringSplit(response_headers,'\n',retry_header_lines);
      for(int line=0;line<count;line++)
        {
         string header=retry_header_lines[line]; StringToLower(header);
         if(StringFind(header,"retry-after:")!=0) continue;
         string seconds=StringSubstr(header,12); StringTrimLeft(seconds); StringTrimRight(seconds);
         if(StringLen(seconds)==0 || StringLen(seconds)>5) return status;
         for(int digit=0;digit<StringLen(seconds);digit++)
            if(StringGetCharacter(seconds,digit)<'0' || StringGetCharacter(seconds,digit)>'9') return status;
         long wait_ms=StringToInteger(seconds)*1000;
         if(wait_ms>=60000) return status;
         delay=(int)MathMax(delay,wait_ms);
        }
      ulong retry_at=GetTickCount64();
      if(retry_at>=deadline || (ulong)delay>=deadline-retry_at) return status;
      Print("GOAT license initialization retry ",attempt+2,"/",attempts,
            " status=",status," nativeError=",native_error," waitMs=",delay);
     }
   return status;
  }
