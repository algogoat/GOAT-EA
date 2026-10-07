"""Pure writer for the profile-staged demo deploy (beta.25, goatai#1885 6033450916).

deploy-load writes every chart of the deploy into one MT5 profile, GOAT-Deploy-<id16>:
chart01.chr holds the Portfolio Dashboard and chart02..chart(N+1).chr hold one child each,
in plan order, with an <expert> block built from the member's frozen SET exactly as the
dashboard's BuildTemplate built its template (Dashboard.mqh@78f3b30:3037-3082) plus
GoatApplyAILaunchPolicy (GOAT_DashboardAILaunchPolicy.mqh). MT5 loads them all at
start-up and the dashboard adopts each child it finds; nothing is applied at runtime.

Nothing here touches the disk or MT5. The bytes are pinned by the shared golden fixtures
in controller/contracts/profile-fixtures (the beta.26 MQL writer must reproduce them), and
the interface with the EA is controller/contracts/profile-deploy.md.

Trading stays off by construction: no file written here ever carries an Enabled or an
AllowLiveTrading key. The only "off" switch is the terminal's Algo Trading, which the startup
ini sets with [Experts] Enabled=0 (D1); expertmode is the literal 5 BuildTemplate used.
"""
import hashlib
import re
from pathlib import Path, PureWindowsPath

PROFILE_PREFIX = 'GOAT-Deploy-'
PROFILE_FORMAT = 'profile-staged-v1'
# D1 (goatai#1885 6033450916): the literal BuildTemplate emitted. The value-1 bit is the per-program
# Allow Algo Trading, so children can start trading only on the human's single Algo Trading gesture.
EXPERT_MODE = '5'
DASHBOARD_SLOT = 1
# The dashboard chart never trades; these are the six values of beta.24's PRESET, in its order.
DASHBOARD_INPUTS = ('Mode_Operation=8', 'Dashboard_Resume_Saved=true', 'Mode_Bias=1', 'Bias_Protocol=2',
                    'Bias_threshold=50', 'EA_Desc=GOAT Dashboard')
# MT5 stores a chart period as (unit, count): 0 = minutes, 1 = hours (ENUM_TIMEFRAMES bits 14-15).
# MT5's own saves on this PC show M1 (0,1), M30 (0,30), H1 (1,1), H4 (1,4) and a daily chart as (1,24):
# D1 is 24 hours, not unit 2 (2 is weeks).
PERIODS = {'M1': (0, 1), 'M5': (0, 5), 'M15': (0, 15), 'M30': (0, 30), 'H1': (1, 1), 'H4': (1, 4), 'D1': (1, 24)}
AI_POLICY_NAMES = ('Mode_Bias', 'Bias_threshold', 'Bias_Protocol', 'Mode_Bias_Trades')
# StringTrimLeft/StringTrimRight remove spaces, tabs and line feeds.
TRIM = ' \t\r\n'
SYMBOL = re.compile(r'[A-Za-z0-9_.#-]{1,64}')
MAX_INPUT_LINES = 4096

PERIOD_REFUSED = 'SET_PERIOD_UNSUPPORTED'
SET_LINE_REFUSED = 'SET_LINE_UNSUPPORTED'
SET_EMPTY = 'SET_NO_INPUTS'
DUPLICATE_MEMBER_SETTINGS = 'DUPLICATE_MEMBER_SETTINGS'


def period_token(file_name):
    """The chart period of a member: the whole token after the first comma of the SET name, up to the first
    character that is not A-Z or 0-9 ('GOAT V1.49 EURUSD,M15_x.set' -> 'M15'). The dashboard's adoption reads
    the same token (GoatAdoptSetPeriod, B43). beta.24's TF() read only two characters, so it opened M15 SETs on
    M1 charts; that reader is gone with the template path. No chart period is ever implicit."""
    comma = file_name.find(',')
    token = re.match(r'[A-Z0-9]*', file_name[comma + 1:]).group() if comma >= 0 else ''
    if token not in PERIODS:
        raise ValueError(PERIOD_REFUSED + ': ' + file_name + ' names the chart period ' + (repr(token) if token else 'nowhere')
                         + '; a deploy supports ' + ', '.join(PERIODS))
    return token


def decode_set(raw):
    if raw.startswith(b'\xff\xfe'):
        return raw[2:].decode('utf-16-le')
    return raw.decode('utf-8-sig')


def _refuse_line(reason, line):
    raise ValueError(SET_LINE_REFUSED + ': ' + reason + ' (' + repr(line[:60]) + ')')


def set_input_lines(raw):
    """BuildTemplate's input lines for one SET: each line trimmed, kept when it has a key before its
    first '=', in file order. Comment lines that hold '=' are kept, as the dashboard keeps them.

    Line ends are CRLF or LF; anything both writers could read differently is refused."""
    text = decode_set(raw)
    if '\x00' in text:
        _refuse_line('a NUL character', text[:60])
    pieces = re.split(r'\r\n|\n', text)
    if len(pieces) > MAX_INPUT_LINES + 1:
        raise ValueError(SET_LINE_REFUSED + ': more than ' + str(MAX_INPUT_LINES) + ' lines')
    lines = []
    for piece in pieces:
        if '\r' in piece:
            _refuse_line('a carriage return that does not end a line', piece)
        line = piece.strip(TRIM)
        if not line or line.find('=') <= 0:
            continue
        if line[0].isspace() or line[-1].isspace():
            _refuse_line('whitespace other than spaces and tabs around the line', line)
        if any(c in '<>' or (ord(c) < 32 and c != '\t') or ord(c) == 127 for c in line):
            _refuse_line('a control character or < or > in an input line', line)
        lines.append(line)
    if not lines:
        raise ValueError(SET_EMPTY + ': the SET has no readable inputs, and a chart is never started on EA defaults')
    return lines


def _ai_value(mode, threshold, name, source, protocol):
    """GoatAILaunchInputValue."""
    if mode not in (1, 2):
        return source
    if name == 'Mode_Bias':
        return '0' if mode == 1 else '2'
    if name == 'Bias_threshold':
        return str(threshold)
    if name == 'Bias_Protocol':
        return '2' if protocol == 2 else '1'
    if name == 'Mode_Bias_Trades':
        return '0'
    return source


def apply_ai_policy(lines, mode, threshold, protocol):
    """GoatApplyAILaunchPolicy: the four AI inputs are replaced in place, then any missing ones appended in order."""
    if mode not in (1, 2):
        return list(lines)
    found, result = set(), []
    for line in lines:
        split = line.find('=')
        if split > 0:
            name, value = line[:split], line[split + 1:]
            if name in AI_POLICY_NAMES:
                found.add(name)
            line = name + '=' + _ai_value(mode, threshold, name, value, protocol)
        result.append(line)
    result.extend(name + '=' + _ai_value(mode, threshold, name, '', protocol) for name in AI_POLICY_NAMES if name not in found)
    return result


def effective_input_lines(raw, policy):
    return apply_ai_policy(set_input_lines(raw), policy['aiMode'], policy['aiThreshold'], policy['aiProtocol'])


def expert_identity(ea_relative_path):
    """(name, path) as MT5 stores them: the file stem, and the path relative to MQL5."""
    relative = PureWindowsPath(ea_relative_path)
    text = str(relative)
    if (relative.is_absolute() or relative.suffix.lower() != '.ex5' or '..' in relative.parts or not relative.stem
            or any(c in text for c in '\r\n<>\x00=') or '/' in ea_relative_path):
        raise ValueError('Unsupported EA path for a deploy profile: ' + repr(ea_relative_path))
    return relative.stem, 'Experts\\' + text


def expert_block(ea_relative_path, input_lines):
    """The <expert> lines exactly as BuildTemplate wrote them."""
    name, path = expert_identity(ea_relative_path)
    for line in input_lines:
        if line.find('=') <= 0 or any(c in line for c in '\r\n<>\x00'):
            raise ValueError(SET_LINE_REFUSED + ': ' + repr(line[:60]))
    return ['<expert>', 'name=' + name, 'path=' + path, 'expertmode=' + EXPERT_MODE, '<inputs>', *input_lines, '</inputs>', '</expert>']


def chart_text_lines(symbol, period, ea_relative_path, input_lines):
    if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
        raise ValueError('Unsupported chart symbol: ' + repr(symbol))
    unit, count = PERIODS[period]
    # The frame of studio_onboarding.monitor_chart, which MT5 loads at start-up (Banker, T3). No id=:
    # MT5 assigns it at load; no objects and no order.wnd: MT5 adds them.
    return (['<chart>', 'symbol=' + symbol, 'period_type=' + str(unit), 'period_size=' + str(count), 'scale=8', 'mode=1',
             'grid=0', 'scroll=1', 'one_click=0', 'windows_total=1']
            + expert_block(ea_relative_path, input_lines)
            + ['<window>', 'height=100.000000', 'objects=0', '<indicator>', 'name=Main', 'path=', 'apply=1', 'show_data=1',
               '</indicator>', '</window>', '</chart>'])


def encode_chart(lines):
    """MT5's own chart encoding: UTF-16LE with a BOM and CRLF line ends."""
    return b'\xff\xfe' + ('\r\n'.join(lines) + '\r\n').encode('utf-16-le')


def chart_file_name(slot):
    if type(slot) is not int or not 1 <= slot <= 101:
        raise ValueError('Invalid chart slot')
    return 'chart%02d.chr' % slot


def dashboard_chart(symbol, ea_relative_path):
    return encode_chart(chart_text_lines(symbol, 'M1', ea_relative_path, list(DASHBOARD_INPUTS)))


def child_chart(member, ea_relative_path, policy):
    """member: dict(name=<SET file name>, symbol=..., raw=<SET bytes>)."""
    return encode_chart(chart_text_lines(member['symbol'], period_token(member['name']), ea_relative_path,
                                         effective_input_lines(member['raw'], policy)))


def profile_files(ea_relative_path, policy, members):
    """Every chart file of the deploy profile: the dashboard first, then one child per member in plan order."""
    if not 1 <= len(members) <= 100:
        raise ValueError('A deploy profile holds 1 to 100 members')
    files = {chart_file_name(DASHBOARD_SLOT): dashboard_chart(members[0]['symbol'], ea_relative_path)}
    for slot, member in enumerate(members, start=DASHBOARD_SLOT + 1):
        files[chart_file_name(slot)] = child_chart(member, ea_relative_path, policy)
    return files


def profile_name(deployment_id):
    return PROFILE_PREFIX + deployment_id[:16]


# ------------------------------------------------------------------ audit-rule ports

def _audit_identifier(name):
    return re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,127}', name) is not None


def audit_inputs(lines):
    """GoatChildAuditInputs: comment lines and native group headings skipped, keys trimmed, duplicates refused."""
    names = {}
    for line in lines:
        trimmed = line.strip(TRIM)
        if not trimmed or trimmed.startswith(';') or (trimmed.startswith('===') and trimmed.endswith('=')):
            continue
        split = line.find('=')
        key = line[:split].strip(TRIM) if split >= 1 else ''
        value = line[split + 1:]
        if split < 1 or not _audit_identifier(key) or key in names or len(names) >= 256 or len(value) > 4096:
            raise ValueError('Inputs are not auditable: ' + repr(line[:60]))
        names[key] = value
    if not names:
        raise ValueError('Inputs are not auditable: none')
    return names


def _audit_decimal(value):
    """GoatChildAuditDecimal; '' when the text is not a plain decimal."""
    if not 1 <= len(value) <= 128 or re.fullmatch(r'[+-]?[0-9]*\.?[0-9]*', value) is None or not re.search('[0-9]', value):
        return ''
    negative = value.startswith('-')
    body = value.lstrip('+-') if value[:1] in '+-' else value
    whole, _, fraction = body.partition('.')
    whole = whole.lstrip('0') or '0'
    fraction = fraction.rstrip('0')
    return ('-' if negative and (whole != '0' or fraction) else '') + whole + ('.' + fraction if fraction else '')


def audit_value_key(name, value):
    """A canonical form such that two values are equal under GoatChildAuditValue exactly when their keys are equal."""
    if name in ('EA_Desc', 'Active_Time_ASIA', 'Active_Time_EU', 'Active_Time_US', 'Studio_MonitorRunPath'):
        return ('text', value)
    if name == 'Download_StartDate':
        date = value + (' 00:00:00' if len(value) == 10 else '')
        date = date + (':00' if len(date) == 16 else '')
        return ('date', date) if len(date) == 19 else ('text', value)
    decimal = _audit_decimal(value)
    return ('decimal', decimal) if decimal else ('text', value)


def audit_equal(name, expected, actual):
    return expected == actual or audit_value_key(name, expected) == audit_value_key(name, actual)


def member_identity(symbol, period, input_lines):
    """What adoption tells members apart by: symbol, period and the audited effective inputs."""
    values = audit_inputs(input_lines)
    return symbol, period, tuple(sorted((name, audit_value_key(name, value)) for name, value in values.items()))


def refuse_duplicates(members, policy):
    seen = {}
    for member in members:
        key = member_identity(member['symbol'], period_token(member['name']), effective_input_lines(member['raw'], policy))
        if key in seen:
            raise ValueError(DUPLICATE_MEMBER_SETTINGS + ': ' + seen[key] + ' and ' + member['name'] + ' would start identical '
                             'charts (same symbol, period and inputs), so the dashboard could not tell them apart')
        seen[key] = member['name']


# ------------------------------------------------------------------ MT5-saved charts

def decode_chart(raw):
    if raw.startswith(b'\xff\xfe'):
        if len(raw) % 2:
            raise ValueError('Odd UTF-16 chart file')
        return raw[2:].decode('utf-16-le')
    return raw.decode('utf-8-sig')


def parse_chart(raw):
    """Read a chart file or template: the top-level chart keys, the expert keys and the input lines."""
    text = decode_chart(raw)
    if len(text) > 4_000_000 or '\x00' in text:
        raise ValueError('Unreadable chart file')
    chart, expert, inputs, stack, experts = {}, {}, [], [], 0
    for line in re.split(r'\r\n|\n', text):
        trimmed = line.strip(TRIM)
        if not trimmed:
            continue
        tag = re.fullmatch(r'<(/?)([A-Za-z_][A-Za-z0-9_]*)>', trimmed)
        if tag:
            closing, name = tag.groups()
            if closing:
                if not stack or stack[-1] != name:
                    raise ValueError('Chart file structure')
                stack.pop()
            else:
                if (not stack and name != 'chart') or (stack and name == 'chart'):
                    raise ValueError('Chart file structure')
                experts += name == 'expert'
                stack.append(name)
            continue
        if stack == ['chart', 'expert', 'inputs']:
            inputs.append(line)
        elif stack in (['chart'], ['chart', 'expert']):
            key, sep, value = line.partition('=')
            target = chart if stack == ['chart'] else expert
            if not sep or key in target:
                raise ValueError('Ambiguous chart key ' + repr(key[:40]))
            target[key] = value
    if stack or experts > 1:
        raise ValueError('Chart file structure')
    return dict(chart=chart, expert=expert, inputs=inputs, has_expert=experts == 1)


def saved_profile_links(files, state_raw):
    """Read-only check of an MT5-saved deploy profile against the dashboard state it saved with it.

    Every row the dashboard linked (cid>0 and magic>0) must name exactly one chart file whose id= is
    that cid, with the row's symbol and a GOAT child (Mode_Operation=9). Returns one entry per row."""
    by_id = {}
    for name, raw in files.items():
        parsed = parse_chart(raw)
        chart_id = parsed['chart'].get('id', '')
        if re.fullmatch('[1-9][0-9]{0,18}', chart_id):
            if chart_id in by_id:
                raise ValueError('Two saved charts share id ' + chart_id)
            by_id[chart_id] = (name, parsed)
    text = decode_set(state_raw)
    rows = [line.split('\t') for line in re.split(r'\r\n|\n', text) if line]
    if not rows or not rows[0][0].startswith('#GOAT_AI_LAUNCH_V147_'):
        raise ValueError('Not a dashboard state file')
    result = []
    for index, row in enumerate(rows[1:]):
        if len(row) < 9:
            raise ValueError('Dashboard state row ' + str(index) + ' is short')
        cid, magic = row[7], row[8]
        entry = dict(index=index, symbol=row[2], cid=cid, magic=magic, chart=None)
        if cid not in ('', '0') and magic not in ('', '0'):
            if cid not in by_id:
                raise ValueError('Row ' + str(index) + ' names chart ' + cid + ', which no saved chart file carries')
            name, parsed = by_id[cid]
            values = audit_inputs(parsed['inputs']) if parsed['has_expert'] else {}
            if parsed['chart'].get('symbol') != row[2] or values.get('Mode_Operation') != '9':
                raise ValueError('Saved chart ' + name + ' is not row ' + str(index) + "'s GOAT child")
            entry['chart'] = name
        result.append(entry)
    return result


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def tree_manifest(folder, *, limit=1024, max_bytes=16 * 1024 * 1024):
    """{relative posix path: sha256} for every file under folder (bounded). None when it is not a plain folder."""
    folder = Path(folder)
    if not folder.is_dir() or folder.is_symlink():
        return None
    manifest = {}
    for path in sorted(folder.rglob('*')):
        if path.is_symlink():
            raise ValueError('A profile file is a link: ' + path.name)
        if path.is_file():
            if len(manifest) >= limit or path.stat().st_size > max_bytes:
                raise ValueError('The profile folder is larger than GOAT reads')
            manifest[path.relative_to(folder).as_posix()] = sha256(path.read_bytes())
    return manifest
