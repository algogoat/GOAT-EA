"""Pure saved-profile/config verification for the exact new35-member pair."""
import configparser,csv,hashlib,io,json,re
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


def profile_claims(directory, reconnect):
    profile=directory/'MQL5/Profiles/Charts/Default'
    need(profile.is_dir() and not profile.is_symlink() and not profile.is_junction(),'default_profile_missing')
    paths=[]
    for path in profile.rglob('*'):
        need(len(paths)<1024,'profile_entry_bound');paths.append(path)
    claims=[];roles=[]
    for path in sorted(paths):
        need(not path.is_symlink() and not path.is_junction(),'profile_alias')
        if path.is_file():
            need(len(claims)<512,'profile_file_bound')
            file_hash=reconnect.file_hash(path,2*1024*1024)
            if path.suffix.casefold()=='.chr':
                raw=read(path,2*1024*1024)
                need(digest(raw)==file_hash,'profile_changed_during_read')
                roles.append(chart_resume_role(raw,directory))
            claims.append([path.relative_to(profile).as_posix(),file_hash])
    need(bool(claims),'empty_profile')
    need(roles.count('dashboard')==1 and roles.count('child')==35 and len(roles)==36,'profile_role_count')
    return digest(json.dumps(claims,separators=(',',':'),ensure_ascii=True).encode()),claims


def chart_resume_role(raw, directory):
    text,_,_=decode_text(raw)
    experts=re.findall(r'(?ms)^\s*<expert>\s*\r?\n(.*?)^\s*</expert>\s*$',text)
    need(len(experts)==1 and len(re.findall(r'(?m)^\s*<expert>\s*$',text))==1,'profile_expert_count')
    expert=experts[0]
    inputs=re.findall(r'(?ms)^\s*<inputs>\s*\r?\n(.*?)^\s*</inputs>\s*$',expert)
    need(len(inputs)==1 and len(re.findall(r'(?m)^\s*<inputs>\s*$',expert))==1,'profile_inputs_count')
    metadata=expert[:expert.index('<inputs>')]
    paths=re.findall(r'(?m)^path=(.*?)\r?$',metadata)
    modes=re.findall(r'(?m)^expertmode=(.*?)\r?$',metadata)
    names=re.findall(r'(?m)^name=(.*?)\r?$',metadata)
    expected='Experts\\GOAT Experiment\\GOAT V1.48.ex5'
    allowed=(expected,str(directory)+'\\MQL5\\'+expected)
    need(len(paths)==1 and paths[0].replace('/','\\') in allowed
         and modes==['5'] and names==['GOAT V1.48'],'profile_expert_identity_or_permission')
    values={}
    for line in inputs[0].splitlines():
        if not line.strip() or line.lstrip().startswith(';') or line.startswith('==='):continue
        key,sep,value=line.partition('=')
        need(bool(sep) and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key) and key not in values,'profile_ambiguous_input')
        values[key]=value
    mode=values.get('Mode_Operation');resume=values.get('Dashboard_Resume_Saved')
    if mode=='8':
        need(resume=='true','dashboard_resume_must_be_true');return 'dashboard'
    need(mode=='9' and resume=='false','child_resume_must_be_false');return 'child'


def verify_dashboard(raw, registration, audit):
    text,_,_=decode_text(raw)
    rows=list(csv.reader(io.StringIO(text),delimiter='\t',quoting=csv.QUOTE_NONE))
    need(len(rows)==36 and rows[0]==['#GOAT_AI_LAUNCH_V147_2',str(registration['aiMode']),str(registration['aiThreshold']),str(registration['aiProtocol'])],'dashboard_policy_or_count')
    for row,member,child in zip(rows[1:],registration['members'],audit['rows']):
        need(len(row)==9 and row[0]==member['path'] and row[2]==member['symbol']
             and row[7]==str(child['chartId']) and row[8]==str(child['magic']),'dashboard_member_identity')
