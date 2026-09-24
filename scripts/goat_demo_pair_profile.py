"""Pure saved-profile/config verification for the exact new35-member pair."""
import configparser,csv,hashlib,io,json,re,time
from pathlib import Path
from goat_demo_pair_connection import require as need
from goat_demo_pair_guard import raw as read

def digest(raw):return hashlib.sha256(raw).hexdigest()

def decode_text(raw):
    if raw.startswith(b'\xff\xfe'):return raw[2:].decode('utf-16-le'),'utf-16-le',b'\xff\xfe'
    if raw.startswith(b'\xfe\xff'):return raw[2:].decode('utf-16-be'),'utf-16-be',b'\xfe\xff'
    if raw.startswith(b'\xef\xbb\xbf'):return raw[3:].decode('utf-8'),'utf-8',b'\xef\xbb\xbf'
    return raw.decode('utf-8'),'utf-8',b''


def patch_common(raw, login, enabled):
    text,encoding,bom=decode_text(raw)
    need('\x00' not in text,'invalid_ini')
    newline='\r\n' if '\r\n' in text else '\n'
    need('\r' not in text.replace('\r\n',''),'mixed_newlines')
    if newline=='\r\n':need('\n' not in text.replace('\r\n',''),'mixed_newlines')
    parser=configparser.ConfigParser(interpolation=None,strict=True)
    parser.read_string(text)
    sections=parser.sections()
    need(len({s.casefold() for s in sections})==len(sections),'ambiguous_sections')
    need(not parser.defaults(),'ini_defaults_not_allowed')
    need('Common' in sections and 'Experts' in sections,'required_sections_missing')
    need(not any(s.casefold()=='startup' for s in sections),'startup_override')
    selectors=[v for s in sections for k,v in parser.items(s) if k.casefold()=='profilelast']
    need(selectors==['Default'],'default_profile_required')
    common=parser['Common'];experts=parser['Experts']
    need(common.get('Login',str(login))==str(login) and common.get('Server','Darwinex-Demo')=='Darwinex-Demo','saved_account_conflict')
    need(experts.get('Enabled')=='0','global_must_start_off')
    need(experts.get('AllowLiveTrading')=='1' and experts.get('AllowDllImport')=='1','expert_permissions_required')
    # Exact line replacement preserves opaque permission records and unrelated bytes.
    lines=text.splitlines(keepends=True);section='';changed=0
    for i,line in enumerate(lines):
        heading=re.fullmatch(r'\s*\[([^\]]+)\]\s*',line.rstrip('\r\n'))
        if heading:section=heading.group(1)
        elif section=='Experts' and re.match(r'^\s*Enabled\s*=',line,re.I):
            need(re.fullmatch(r'(\s*Enabled\s*=\s*)0(\s*)(\r?\n)?',line,re.I) is not None,'ambiguous_enabled_line')
            lines[i]=re.sub(r'(^\s*Enabled\s*=\s*)0',lambda m:m.group(1)+str(enabled),line,count=1,flags=re.I);changed+=1
    need(changed==1,'enabled_record_count')
    addition=[]
    if 'Login' not in common:addition.append('Login='+str(login)+newline)
    if 'Server' not in common:addition.append('Server=Darwinex-Demo'+newline)
    if addition:
        index=next(i for i,line in enumerate(lines) if re.fullmatch(r'\s*\[Common\]\s*',line.rstrip('\r\n')))
        need(lines[index].endswith(('\n','\r')),'unterminated_common_header')
        lines[index+1:index+1]=addition
    return bom+''.join(lines).encode(encoding)


def profile_claims(directory, reconnect, registration, audit):
    profile=directory/'MQL5/Profiles/Charts/Default'
    need(profile.is_dir() and not profile.is_symlink() and not profile.is_junction(),'default_profile_missing')
    paths=[]
    for path in profile.rglob('*'):
        need(len(paths)<1024,'profile_entry_bound');paths.append(path)
    need(len(registration['members'])==35 and len(audit['rows'])==35,'profile_members_required')
    expected={}
    for member,child in zip(registration['members'],audit['rows']):
        cid=child['chartId']
        need(type(cid) is int and cid>0 and cid not in expected and child['symbol']==member['symbol']
             and child['settingsMatch'] is True,'profile_audit_identity')
        expected[cid]=(member,effective_inputs(member,registration))
    claims=[];roles=[];seen=set()
    for path in sorted(paths):
        need(not path.is_symlink() and not path.is_junction(),'profile_alias')
        if path.is_file():
            need(len(claims)<512,'profile_file_bound')
            file_hash=reconnect.file_hash(path,2*1024*1024)
            if path.suffix.casefold()=='.chr':
                raw=read(path,2*1024*1024)
                need(digest(raw)==file_hash,'profile_changed_during_read')
                chart,values,role=chart_details(raw,directory)
                need(re.fullmatch('[1-9][0-9]*',chart.get('id','')) is not None,'profile_chart_id')
                cid=int(chart['id']);need(cid not in seen,'profile_duplicate_chart');seen.add(cid)
                roles.append(role)
                if role=='child':
                    need(cid in expected,'profile_unknown_child')
                    member,inputs=expected[cid]
                    need(chart.get('symbol')==member['symbol'] and chart.get('period_type')=='0'
                         and chart.get('period_size')=='1','profile_symbol_or_period')
                    need(set(values)==set(inputs) and all(input_equal(k,v,values[k]) for k,v in inputs.items()),
                         'profile_effective_inputs')
                else:need(cid not in expected,'profile_dashboard_child_collision')
            claims.append([path.relative_to(profile).as_posix(),file_hash])
    need(bool(claims),'empty_profile')
    need(roles.count('dashboard')==1 and roles.count('child')==35 and len(roles)==36,'profile_role_count')
    need(set(expected).issubset(seen),'profile_missing_child')
    return digest(json.dumps(claims,separators=(',',':'),ensure_ascii=True).encode()),claims


def chart_resume_role(raw, directory):
    return chart_details(raw,directory)[2]


def input_values(text):
    need(len(text)<=1000000 and '\x00' not in text,'profile_input_size')
    values={};lines=text.splitlines();need(len(lines)<=4096,'profile_input_lines')
    for line in lines:
        trimmed=line.strip()
        if not trimmed or trimmed.startswith(';') or (trimmed.startswith('===') and trimmed.endswith('=')):continue
        key,sep,value=line.partition('=');key=key.strip()
        need(bool(sep) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}',key) is not None
             and key not in values and len(value)<=4096 and len(values)<256,'profile_ambiguous_input')
        values[key]=value
    need(bool(values),'profile_empty_inputs');return values


def effective_inputs(member,registration):
    raw=read(member['path']);need(digest(raw)==member['sha256'],'source_set_changed')
    values=input_values(decode_text(raw)[0]);mode=registration['aiMode']
    need(mode in (0,2) and registration['aiThreshold']==50 and registration['aiProtocol']==2,'profile_policy')
    if mode==2:values.update(Mode_Bias='2',Bias_threshold='50',Bias_Protocol='2',Mode_Bias_Trades='0')
    for key,value in {'Studio_ReadOnlyMonitor':'false','Studio_MonitorRunPath':'','Dashboard_Resume_Saved':'false'}.items():
        need(values.get(key,value)==value,'profile_live_input_default');values[key]=value
    need(values.get('Mode_Operation')=='9','profile_source_child_required')
    return values


def input_equal(name,expected,actual):
    # Match the native GoatChildAuditValue contract: no epsilon or float coercion.
    if expected==actual:return True
    if name in ('EA_Desc','Active_Time_ASIA','Active_Time_EU','Active_Time_US','Studio_MonitorRunPath'):return False
    if name=='Download_StartDate':
        dates=[]
        for value in (expected,actual):
            if len(value)==10:value+=' 00:00:00'
            if len(value)==16:value+=':00'
            dates.append(value)
        return len(dates[0])==19 and dates[0]==dates[1]
    decimals=[]
    for value in (expected,actual):
        if len(value)>128 or re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)',value) is None:return False
        negative=value.startswith('-');value=value.lstrip('+-');whole,_,fraction=value.partition('.')
        whole=whole.lstrip('0') or '0';fraction=fraction.rstrip('0')
        decimals.append(('-' if negative and (whole!='0' or fraction) else '')+whole+('.'+fraction if fraction else ''))
    return decimals[0]==decimals[1]


def chart_details(raw, directory):
    text,_,_=decode_text(raw)
    need(len(text)<=2000000 and '\x00' not in text,'profile_chart_size')
    stack=[];chart={};expert={};input_lines=[];experts=inputs=0;closed=False
    lines=text.splitlines();need(len(lines)<=65536,'profile_chart_lines')
    for line in lines:
        trimmed=line.strip()
        if not trimmed:continue
        if trimmed.startswith('<'):
            match=re.fullmatch(r'<(/?)([A-Za-z_][A-Za-z0-9_]*)>',trimmed)
            need(match is not None,'profile_chart_tag');closing,tag=match.groups()
            if closing:
                need(bool(stack) and stack[-1]==tag,'profile_chart_structure');stack.pop()
                if tag=='chart':closed=True
            else:
                need(not closed and len(stack)<64 and (bool(stack) or tag=='chart')
                     and not (stack and tag=='chart'),'profile_chart_structure')
                if tag=='expert':
                    experts+=1;need(stack==['chart'] and experts==1,'profile_expert_count')
                elif 'expert' in stack:
                    inputs+=1;need(tag=='inputs' and stack==['chart','expert'] and inputs==1,'profile_inputs_count')
                stack.append(tag)
            continue
        need(bool(stack) and not closed,'profile_chart_structure')
        if stack==['chart','expert','inputs']:input_lines.append(line)
        elif stack in (['chart'],['chart','expert']):
            target=chart if stack==['chart'] else expert
            key,sep,value=line.partition('=');key=key.strip()
            need(bool(sep) and key not in target,'profile_ambiguous_metadata');target[key]=value
    need(closed and not stack and experts==1 and inputs==1,'profile_chart_structure')
    expected='Experts\\GOAT Experiment\\GOAT V1.48.ex5'
    allowed=(expected,str(directory)+'\\MQL5\\'+expected)
    need(expert.get('path','').replace('/','\\') in allowed and expert.get('expertmode')=='5'
         and expert.get('name')=='GOAT V1.48','profile_expert_identity_or_permission')
    values=input_values('\n'.join(input_lines))
    mode=values.get('Mode_Operation');resume=values.get('Dashboard_Resume_Saved')
    if mode=='8':
        need(resume=='true','dashboard_resume_must_be_true');return chart,values,'dashboard'
    need(mode=='9' and resume=='false','child_resume_must_be_false');return chart,values,'child'


def verify_dashboard(raw, registration, audit):
    text,_,_=decode_text(raw)
    rows=list(csv.reader(io.StringIO(text),delimiter='\t',quoting=csv.QUOTE_NONE))
    need(len(rows)==36 and rows[0]==['#GOAT_AI_LAUNCH_V147_2',str(registration['aiMode']),str(registration['aiThreshold']),str(registration['aiProtocol'])],'dashboard_policy_or_count')
    for row,member,child in zip(rows[1:],registration['members'],audit['rows']):
        need(len(row)==9 and row[0]==member['path'] and row[2]==member['symbol']
             and row[7]==str(child['chartId']) and row[8]==str(child['magic']),'dashboard_member_identity')


def verify_enabled_persistence(row, path, expected_sha256, now=None):
    # Closed-start evidence only. Globals legitimately change after MT5 starts;
    # this is never a live-readiness check or permission to restore their bytes.
    need(path is not None and re.fullmatch('[a-f0-9]{64}',expected_sha256 or '') is not None,
         'enabled_persistence_proof_required')
    raw=read(path);need(digest(raw)==expected_sha256,'enabled_persistence_proof_hash')
    from goat_demo_pair_connection import unique_object,canonical,file_hash
    proof=json.loads(raw,object_pairs_hook=unique_object)
    fields={'schema','terminal','account','directory','buildId','eaSha256','profileSha256','commonIniSha256',
            'registrationSha256','pairedProofSha256','createdAtUtc','process','shutdownId','globalsSha256',
            'dashboardStatePath','dashboardStateSha256'}
    need(type(proof) is dict and set(proof)==fields and proof['schema']=='goat-demo-pair-persistence-v1',
         'enabled_persistence_schema')
    for key in ('terminal','directory','buildId','eaSha256','profileSha256','commonIniSha256'):
        need(proof[key]==row[key],'enabled_persistence_binding')
    need(row['savedAlgoEnabled'] is True and proof['account']==row['login'],'enabled_persistence_account')
    for key in ('registrationSha256','pairedProofSha256','globalsSha256','dashboardStateSha256'):
        need(isinstance(proof[key],str) and re.fullmatch('[a-f0-9]{64}',proof[key]) is not None
             and proof[key]!='0'*64,'enabled_persistence_digest')
    stamp=proof['createdAtUtc'];now=time.time() if now is None else now
    need(type(stamp) in (int,float) and 0<=now-stamp<=600,'enabled_persistence_expired')
    directory=Path(row['directory']);state=Path(proof['dashboardStatePath'])
    need(state.is_absolute() and state.parent.name=='GOAT'
         and state.name=='dashboard_state_'+directory.name+'.tsv','enabled_persistence_state_scope')
    need(type(proof['process']) is dict and canonical(proof['process'].get('path',''))==canonical(directory/'terminal64.exe')
         and re.fullmatch('[a-f0-9]{32}',proof['shutdownId'] or '') is not None,'enabled_persistence_process')
    need(file_hash(directory/'bases/gvariables.dat',32*1024*1024)==proof['globalsSha256'],'enabled_persistence_globals_changed')
    need(file_hash(state,2*1024*1024)==proof['dashboardStateSha256'],'enabled_persistence_dashboard_changed')
    return proof
