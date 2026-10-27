"""EA OnInit refusal parity for SET validation (beta.38).

`EA_INIT_RULES` mirrors every `OnInit` refusal in `GOAT V1.49.mq5` that depends only on input values,
so a SET the EA would refuse at initialization is refused by `validate_strategy` first (strategy-create,
template intake, build-set, queue, drafts). Every other `OnInit` refusal is listed in `NOT_PORTED` with the
reason it depends on the symbol, broker, account, files, chart or run context. A static test parses the
.mq5 and fails when a refusal is in neither table, so a new EA init rule cannot be missed silently.

Optimization ranges: a rule is evaluated over every value each input it reads can take: the SET's current
value plus every value of an active `start||step||stop||Y` ladder (a dormant `N` tuple runs with its first
field, exactly as MT5 reads it). Any failing combination refuses: an init-failing optimization pass
produces nothing, and an exported or template SET must never fail init. Inputs are bound lazily in the
order the MQL condition reads them, so an input a short-circuited condition never reads is never expanded.
More than `MAX_COMBINATIONS` evaluations for one rule refuses with a message naming the ladders to narrow.

`TESTER_INIT_RULES` are refusals that also need the strategy-tester context (valid on a live chart, refused in
every tester pass). They are not part of validate-set; batch prepare applies them (`check_tester_init`,
`TESTER_INIT_REFUSED`) before anything is staged. The static test counts OnInit `ExpertRemove()` paths too.

Arithmetic mirrors MQL: double inputs are IEEE doubles (Python float), ints and enums are ints, and enum
values are resolved by label from the schema's `enum_choices`. V1.48 carries the same rules (at other line numbers).

Runtime refusals that never end OnInit are not listed: B46's CID guard (`GoatCidGuardEvaluate`, reasons
`orphan_suspected` and `cid_duplicate`; B47 also freezes a running sequence's adds under `cid_duplicate`) refuses new
sequences on a live chart from the terminal's CID records, open charts, claim files and the
account's open positions, never from a SET's values, and initialization still succeeds.
"""
from datetime import datetime
from decimal import Decimal, localcontext
from fractions import Fraction
import re

from studio_strategy_settings import numeric

EA_SOURCE = 'GOAT V1.49.mq5'
EA_INIT_CODE = 'EA_INIT_REFUSED'
TESTER_INIT_CODE = 'TESTER_INIT_REFUSED'
EA_INIT_SCHEMA_CODE = 'EA_INIT_SCHEMA_UNRECOGNISED'
MAX_COMBINATIONS = 10_000
GOAT_INTERFACE_MARKER = 'Mode_Lots'   # same marker check_risk_sizing uses: compact test schemas carry no rules


class _Need(Exception):
    def __init__(self, name):
        super().__init__(name)
        self.name = name


class _TooMany(Exception):
    pass


class _View:
    """What a predicate sees: v['Input'] is the typed value, v.choice('Input', 'Label') the enum value."""
    def __init__(self, bound, choices):
        self._bound, self._choices = bound, choices

    def __getitem__(self, name):
        if name not in self._bound:
            raise _Need(name)
        return self._bound[name][0]

    def choice(self, name, label):
        return self._choices[name][label]

    def has(self, name, label):
        return label in self._choices.get(name, {})


# ---- MQL helpers --------------------------------------------------------------------------------------------
def _mql_split_count(text, separator):
    """StringSplit's return value: 0 for an empty string, else the number of substrings (empty ones included)."""
    return 0 if text == '' else len(text.split(separator))


def _bad_session(text):
    # GOAT V1.49.mq5:4004-4009. parts/hm are declared `string parts[2], hm[2]`; the documented StringSplit
    # count is mirrored (see the PR inventory for the static-array caveat).
    if _mql_split_count(text, '-') != 2:
        return True
    start, end = text.split('-')
    return _mql_split_count(start, ':') != 2 or _mql_split_count(end, ':') != 2


_TRIM = ' \t\r\n'


def _desc_keys(text):
    """ExtractFunctionKeysFromInputString (GOAT V1.49.mq5:8136): key/value pairs of the `@{...}` section."""
    at = text.find('@')
    if at < 0:
        return []
    opening = text.find('{', at)
    if opening < 0:
        return []
    closing = text.find('}', opening)
    if closing < 0:
        return []
    inner = text[opening+1:closing].strip(_TRIM)
    tokens, current, in_s, in_d = [], '', False, False
    for ch in inner:
        if ch == "'" and not in_d:
            in_s = not in_s; current += ch; continue
        if ch == '"' and not in_s:
            in_d = not in_d; current += ch; continue
        if not in_s and not in_d and ch == ',':
            tokens.append(current); current = ''; continue
        current += ch
    tokens.append(current)
    pairs = []
    for token in tokens:
        token = token.strip(_TRIM)
        if not token or '=' not in token:
            continue
        key, value = token.split('=', 1)
        key, value = key.strip(_TRIM), value.strip(_TRIM)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in '\'"':
            value = value[1:-1]
        pairs.append((key, value))
    return pairs


_DATE = re.compile(r'\d{4}\.\d{2}\.\d{2}(?: \d{2}:\d{2}(?::\d{2})?)?')


def _mql_time(value):
    """StringToTime for the controller's own `yyyy.mm.dd[ hh:mi[:ss]]` form; None when the text is in any
    other form, whose StringToTime result cannot be reproduced exactly (the rule then does not refuse)."""
    if not _DATE.fullmatch(value):
        return None
    fmt = '%Y.%m.%d' + (' %H:%M' if ' ' in value else '') + (':%S' if value.count(':') == 2 else '')
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


def _export_dates(desc):
    """(is EXPORT, {name: datetime|0|None}) as OnInit lines 3916-3945 read them from EA_Desc."""
    pairs = _desc_keys(desc)
    mode = ''
    for name, value in pairs:
        if 'mode' in name or 'Mode' in name or 'MODE' in name:
            mode = value
    dates = dict(dt_BOOS_end=0, dt_FOOS_start=0, dt_FWD_start=0, dt_FWD_end=0)
    for name, value in pairs:
        if name in dates:
            dates[name] = _mql_time(value)
    return mode == 'EXPORT', dates


def _export_rule(first, second, check):
    """An EXPORT-mode date rule over two EA_Desc keys; a value StringToTime may read differently never refuses."""
    def predicate(v):
        export, dates = _export_dates(v['EA_Desc'])
        if not export or dates[first] is None or dates[second] is None:
            return False
        return check(dates[first], dates[second])
    return predicate


def _set(value):
    return value != 0   # the EA's datetime globals start at 0 = not given


def _foos_not_after_boos(boos, foos):
    return _set(boos) and _set(foos) and foos <= boos


def _fwd_half_given(start, end):
    return (_set(start) or _set(end)) and (not _set(start) or not _set(end))


def _fwd_end_before_start(start, end):
    return _set(start) and _set(end) and end < start


# ---- the lot/exit/RRR chain (GOAT V1.49.mq5:4088-4104, 4354-4427) --------------------------------------------
def _risk_per_seq(v):
    return v['Mode_Lots'] == v.choice('Mode_Lots', 'RiskperSeq')


def _peak_smart(v):
    return v['Mode_Lots_Prog'] == v.choice('Mode_Lots_Prog', 'Lots_Prog_PeakSmart')


def _rrr_on(v):
    return v['Mode_RRR'] != v.choice('Mode_RRR', 'RRR_Disabled')


def _tp_size(v):
    return v['TP_Pips'] * v['Lock_Profit_Size']          # TP_Pips_ = TP_Pips*LP_Size_ (line 4093)


def _lp_tp_both_disabled(v):
    """Line 4427 after the RRR block may have derived TP, SL or LP, and lines 4425-4426 zero sizes under 1."""
    lp = v['Lock_Profit_Size']
    tp = v['TP_Pips'] * lp
    if _rrr_on(v):
        rrr = v['RRR']
        if rrr <= 0:
            return False                                  # refused earlier (4385/4386); 4427 is not reached
        sl = v['SL_Pips']
        if v['Mode_RRR'] == v.choice('Mode_RRR', 'RRR_SL_TP'):
            if sl != 0:
                if tp != 0:
                    return False                          # refused at 4391
                tp = sl * rrr
            elif tp == 0:
                return False                              # refused at 4397
        elif v['Mode_RRR'] == v.choice('Mode_RRR', 'RRR_SL_LP'):
            if sl != 0:
                if lp != 0:
                    return False                          # refused at 4404
                lp = sl * rrr
            elif lp == 0:
                return False                              # refused at 4410
    if -1.0 < lp < 1.0:
        lp = 0
    if -1.0 < tp < 1.0:
        tp = 0
    return lp == 0 and tp == 0


def _rule(rule_id, lines, anchor, inputs, enums, condition, alert, predicate, note=None):
    return dict(id=rule_id, source=EA_SOURCE, lines=tuple(lines), anchor=anchor, inputs=tuple(inputs),
                enums=enums, condition=condition, alert=alert, predicate=predicate, note=note)


def _download_removes_ea(v):
    """OnInit lines 3963-3996: a News download removes the EA at 3978 (unless NewsBias), any Bias download at 3952."""
    mode = v['Mode_Download']
    news = mode in (v.choice('Mode_Download', 'Download_News'), v.choice('Mode_Download', 'Download_NewsBias'))
    bias = mode in (v.choice('Mode_Download', 'Download_Bias'), v.choice('Mode_Download', 'Download_NewsBias'))
    return (news and mode != v.choice('Mode_Download', 'Download_NewsBias')) or bias


def _tester_control_tower_bias(v):
    """OnInit 3877: test context && Mode_Bias!=Bias_Disabled && GOATUsingControlTowerBias() (GOATAIWireV2.mqh:640);
    the DemoRaw protocol only exists, and only counts, when the build defines GOAT_AI_WIRE_V2_DEMO_RAW_SUPPORTED,
    which the schema shows by declaring that enum label."""
    if v['Mode_Bias'] == v.choice('Mode_Bias', 'Bias_Disabled'):
        return False
    protocol = v['Bias_Protocol']
    return (protocol == v.choice('Bias_Protocol', 'BiasProtocol_ControlTowerV2')
            or (v.has('Bias_Protocol', 'BiasProtocol_ControlTowerV2DemoRaw')
                and protocol == v.choice('Bias_Protocol', 'BiasProtocol_ControlTowerV2DemoRaw')))


SESSION_INPUTS = ('Active_Time_ASIA', 'Active_Time_EU', 'Active_Time_US')
RRR_CHAIN = ('Mode_RRR', 'RRR', 'SL_Pips', 'TP_Pips', 'Lock_Profit_Size')

# In OnInit order: the first rule that fails is the one the EA reports.
EA_INIT_RULES = (
    _rule('EXPORT_FOOS_NOT_AFTER_BOOS', [3950], 'dt_Fwrd_OOS<=dt_Back_OOS', ['EA_Desc'], {},
          'EA_Desc @{mode=EXPORT}: dt_BOOS_end!=0 && dt_FOOS_start!=0 && dt_FOOS_start<=dt_BOOS_end',
          'EXPORT: dt_FOOS_start:<date> must be after dt_BOOS_end',
          _export_rule('dt_BOOS_end', 'dt_FOOS_start', _foos_not_after_boos)),
    _rule('EXPORT_FWD_HALF_GIVEN', [3951], '(dt_FWD_start!=0 || dt_FWD_end!=0) && (dt_FWD_start==0 || dt_FWD_end==0)',
          ['EA_Desc'], {}, 'EA_Desc @{mode=EXPORT}: exactly one of dt_FWD_start/dt_FWD_end set',
          'EXPORT: dt_FWD_start and dt_FWD_end must both be provided',
          _export_rule('dt_FWD_start', 'dt_FWD_end', _fwd_half_given)),
    _rule('EXPORT_FWD_END_BEFORE_START', [3952], 'dt_FWD_end<dt_FWD_start', ['EA_Desc'], {},
          'EA_Desc @{mode=EXPORT}: dt_FWD_start!=0 && dt_FWD_end!=0 && dt_FWD_end<dt_FWD_start',
          'EXPORT: dt_FWD_end:<date> must be after dt_FWD_start',
          _export_rule('dt_FWD_start', 'dt_FWD_end', _fwd_end_before_start)),
    _rule('DATA_DOWNLOAD_MODE_REMOVES_EA', [3978, 3995], 'History download is not allowed in this mode', ['Mode_Download'],
          {'Mode_Download': ['Download_Disabled', 'Download_News', 'Download_Bias', 'Download_NewsBias']},
          'Mode_Download in (Download_News, Download_Bias, Download_NewsBias): ExpertRemove() in OnInit',
          'News History download is not allowed in this mode / Bias History download is not allowed in this mode',
          _download_removes_ea,
          note=('In the tester the EA prints that and removes itself; on a live chart it downloads the data files and '
                'then removes itself (ExpertRemove, GOAT V1.49.mq5:3978/3995). Mode_Download is the "Data Download '
                'Mode for Backtest" data tool, never a strategy setting: use Download_Disabled.')),
    _rule('SESSION_FORMAT', [4004, 4006, 4009], 'Session format must be HH:MM-HH:MM', SESSION_INPUTS, {},
          'Active_Time_ASIA/EU/US: StringSplit(s,\'-\')!=2, or either half StringSplit(h,\':\')!=2',
          'Session format must be HH:MM-HH:MM', lambda v: any(_bad_session(v[name]) for name in SESSION_INPUTS)),
    _rule('RISK_PER_SEQUENCE_RISK_TOO_LOW', [4358], 'Mode_Lots == RiskperSeq && Risk<10', ['Mode_Lots', 'Risk'],
          {'Mode_Lots': ['RiskperSeq']}, 'Mode_Lots==RiskperSeq && Risk<10',
          'Initialization Stopped Manually: You have selected Risk per Sequence but your Risk Amount is too low.',
          lambda v: _risk_per_seq(v) and v['Risk'] < 10),
    _rule('MLPS_HARD_CLOSE_RISK_TOO_LOW', [4359], 'Sequence_MLPS_Hard_Close && Risk<10.0',
          ['Sequence_MLPS_Hard_Close', 'Risk'], {}, 'Sequence_MLPS_Hard_Close && Risk<10.0',
          'Initialization Failed: Sequence MLPS hard close requires Risk/MLPS amount of at least 10.',
          lambda v: v['Sequence_MLPS_Hard_Close'] and v['Risk'] < 10.0),
    _rule('SMART_PEAK_RISK_TOO_LOW', [4365], 'Smart Peak requires Risk/MLPS amount of at least 10',
          ['Mode_Lots_Prog', 'Risk'], {'Mode_Lots_Prog': ['Lots_Prog_PeakSmart']},
          'Mode_Lots_Prog==Lots_Prog_PeakSmart && Risk<10.0',
          'Initialization Failed: Smart Peak requires Risk/MLPS amount of at least 10.',
          lambda v: _peak_smart(v) and v['Risk'] < 10.0),
    _rule('SMART_PEAK_PERCENT_RANGE', [4370],
          'Peak_Smart_Release_PC<0.0 || Peak_Smart_Release_PC>100.0 || Peak_Smart_Max_Close_PC<0.0 || Peak_Smart_Max_Close_PC>100.0',
          ['Mode_Lots_Prog', 'Peak_Smart_Release_PC', 'Peak_Smart_Max_Close_PC'], {'Mode_Lots_Prog': ['Lots_Prog_PeakSmart']},
          'Mode_Lots_Prog==Lots_Prog_PeakSmart && (Peak_Smart_Release_PC or Peak_Smart_Max_Close_PC outside 0..100)',
          'Initialization Failed: Smart Peak inputs must use 0-100 percent ranges.',
          lambda v: _peak_smart(v) and (v['Peak_Smart_Release_PC'] < 0.0 or v['Peak_Smart_Release_PC'] > 100.0
                                        or v['Peak_Smart_Max_Close_PC'] < 0.0 or v['Peak_Smart_Max_Close_PC'] > 100.0)),
    _rule('SMART_RESCUE_MAX_ADDS_BELOW_MINUS_ONE', [4373], 'Bias_Exit_Max_Exposure_Adds<-1',
          ['Bias_Exit_Max_Exposure_Adds'], {}, 'Bias_Exit_Max_Exposure_Adds<-1',
          'Initialization Failed: Smart Rescue max positive adds cannot be less than -1.',
          lambda v: v['Bias_Exit_Max_Exposure_Adds'] < -1),
    _rule('SMART_RESCUE_NEEDS_RISK_PER_SEQUENCE', [4379], 'Mode_Lots!=RiskperSeq || Risk<=0.0',
          ['Mode_Bias_Exit', 'Mode_Lots', 'Risk'],
          {'Mode_Bias_Exit': ['BiasExit_SmartRescue'], 'Mode_Lots': ['RiskperSeq']},
          'Mode_Bias_Exit==BiasExit_SmartRescue && (Mode_Lots!=RiskperSeq || Risk<=0.0)',
          'Initialization Failed: Smart Rescue requires Risk per Sequence lot sizing and Risk > 0.',
          lambda v: v['Mode_Bias_Exit'] == v.choice('Mode_Bias_Exit', 'BiasExit_SmartRescue')
          and (not _risk_per_seq(v) or v['Risk'] <= 0.0)),
    _rule('RRR_NEGATIVE', [4385], 'if(RRR<0)', ['Mode_RRR', 'RRR'], {'Mode_RRR': ['RRR_Disabled']},
          'Mode_RRR!=RRR_Disabled && RRR<0', 'Initialization Failed: Risk/Reward ratio cannot be negative',
          lambda v: _rrr_on(v) and v['RRR'] < 0),
    _rule('RRR_ZERO', [4386], 'if(RRR==0)', ['Mode_RRR', 'RRR'], {'Mode_RRR': ['RRR_Disabled']},
          'Mode_RRR!=RRR_Disabled && RRR==0', 'Initialization Failed: Risk/Reward ratio is enabled but RRR=0',
          lambda v: _rrr_on(v) and v['RRR'] == 0),
    _rule('RRR_SL_TP_BOTH_SET', [4391], 'Risk/Reward mode is SL/TP, but neither TP nor SL is zero',
          ['Mode_RRR', 'SL_Pips', 'TP_Pips', 'Lock_Profit_Size'], {'Mode_RRR': ['RRR_SL_TP']},
          'Mode_RRR==RRR_SL_TP && SL_Pips!=0 && TP_Pips*Lock_Profit_Size!=0',
          'Initialization Failed: Risk/Reward mode is SL/TP, but neither TP nor SL is zero',
          lambda v: v['Mode_RRR'] == v.choice('Mode_RRR', 'RRR_SL_TP') and v['SL_Pips'] != 0 and _tp_size(v) != 0),
    _rule('RRR_SL_TP_BOTH_ZERO', [4397], 'Risk/Reward mode is SL/TP, but both TP and SL are zero',
          ['Mode_RRR', 'SL_Pips', 'TP_Pips', 'Lock_Profit_Size'], {'Mode_RRR': ['RRR_SL_TP']},
          'Mode_RRR==RRR_SL_TP && SL_Pips==0 && TP_Pips*Lock_Profit_Size==0',
          'Initialization Failed: Risk/Reward mode is SL/TP, but both TP and SL are zero',
          lambda v: v['Mode_RRR'] == v.choice('Mode_RRR', 'RRR_SL_TP') and v['SL_Pips'] == 0 and _tp_size(v) == 0),
    _rule('RRR_SL_LP_BOTH_SET', [4404], 'Risk/Reward mode is SL/LP, but neither LP nor SL is zero',
          ['Mode_RRR', 'SL_Pips', 'Lock_Profit_Size'], {'Mode_RRR': ['RRR_SL_LP']},
          'Mode_RRR==RRR_SL_LP && SL_Pips!=0 && Lock_Profit_Size!=0',
          'Initialization Failed: Risk/Reward mode is SL/LP, but neither LP nor SL is zero',
          lambda v: v['Mode_RRR'] == v.choice('Mode_RRR', 'RRR_SL_LP') and v['SL_Pips'] != 0 and v['Lock_Profit_Size'] != 0),
    _rule('RRR_SL_LP_BOTH_ZERO', [4410], 'Risk/Reward mode is SL/LP, but both LP and SL are zero',
          ['Mode_RRR', 'SL_Pips', 'Lock_Profit_Size'], {'Mode_RRR': ['RRR_SL_LP']},
          'Mode_RRR==RRR_SL_LP && SL_Pips==0 && Lock_Profit_Size==0',
          'Initialization Failed: Risk/Reward mode is SL/LP, but both LP and SL are zero',
          lambda v: v['Mode_RRR'] == v.choice('Mode_RRR', 'RRR_SL_LP') and v['SL_Pips'] == 0 and v['Lock_Profit_Size'] == 0),
    _rule('GRID_SIZE_TOO_SMALL', [4422], 'Grid_Size >-0.5 && Grid_Size <0.5', ['Grid_Size'], {},
          'Grid_Size>-0.5 && Grid_Size<0.5', 'Initialization Failed: Pip Gap Size too small or zero',
          lambda v: -0.5 < v['Grid_Size'] < 0.5),
    _rule('LP_AND_TP_BOTH_DISABLED', [4427], 'LP_Size_  ==0   && TP_Pips_  ==0', RRR_CHAIN,
          {'Mode_RRR': ['RRR_Disabled', 'RRR_SL_TP', 'RRR_SL_LP']},
          'after the RRR block and the |x|<1 -> 0 normalisation of lines 4425-4426: LP_Size_==0 && TP_Pips_==0',
          'Initialization Failed: Both LP and TP cannot be zero/disabled.', _lp_tp_both_disabled),
)

# OnInit refusals that depend on input values plus the strategy-tester context only. A SET can be valid on a live
# chart and still refused in every tester pass, so validate-set (live and tester SETs alike) does not apply these;
# batch prepare (studio_batch.prepare_batch) does, before anything is staged.
TESTER_INIT_RULES = (
    _rule('TESTER_CONTROL_TOWER_BIAS', [3880], 'Live Control Tower bias is unavailable in tester',
          ['Mode_Bias', 'Bias_Protocol'],
          {'Mode_Bias': ['Bias_Disabled'], 'Bias_Protocol': ['BiasProtocol_ControlTowerV2']},
          '(MQL_TESTER || MQL_OPTIMIZATION || MQL_FORWARD) && Mode_Bias!=Bias_Disabled && Bias_Protocol is '
          'BiasProtocol_ControlTowerV2 or BiasProtocol_ControlTowerV2DemoRaw',
          'Live Control Tower bias is unavailable in tester, optimization, and forward contexts. Select '
          'BiasProtocol_LegacyRecorded or disable AI bias.', _tester_control_tower_bias),
)

# Every other OnInit refusal, with why validate-set cannot decide it from the SET's values alone.
_STUDIO_SINPUTS = ('Studio_ReadOnlyMonitor/Studio_MonitorRunPath are sinputs declared in the .mq5, not in the '
                   'input header, so they are not in the controller schema; validate_strategy refuses a SET that '
                   'names them (unknown input) and the EA default (false) never fires this rule')
NOT_PORTED = (
    dict(lines=(3855,), anchor='StringFind(Studio_MonitorRunPath,"GOAT\\\\")!=0', condition='read-only monitor run path outside GOAT\\', reason=_STUDIO_SINPUTS),
    dict(lines=(3857,), anchor='Read-only Studio requires chart operation mode Optimization Studio',
         condition='Studio_ReadOnlyMonitor && (Mode_Operation!=Operation_Batch || MQL_TESTER)', reason=_STUDIO_SINPUTS + '; also run context (tester)'),
    dict(lines=(3868,), anchor='Name Mismatch: The Bot/EA cannot be renamed',
         condition='EA file renamed (EA_Name != Key+" V"+version): Alert then ExpertRemove()',
         reason='build identity (the .ex5 file name), not an input value'),
    dict(lines=(3885,), anchor='Legacy recorded bias is historical/test-only',
         condition='Bias_Protocol==BiasProtocol_LegacyRecorded && live chart', reason='run context: valid in the tester, refused live'),
    dict(lines=(3893,), anchor='Demo raw AI bias is restricted to demo accounts',
         condition='Mode_Bias!=Bias_Disabled && DemoRaw protocol && live && account is not demo', reason='account trade mode'),
    dict(lines=(3902,), anchor='GOATDeviceActivationBegin(AccountInfoInteger(ACCOUNT_LOGIN),GOAT_BUILD_ID)',
         condition='live, no credential, device activation cannot begin', reason='account login and credential state'),
    dict(lines=(3912,), anchor='GOAT AI wire v2 checksum self-test failed', condition='AI wire v2 self-test fails', reason='build/runtime self-test'),
    dict(lines=(3948,), anchor='dt_Back_OOS<TimeCurrent()', condition='EXPORT && dt_BOOS_end before the test start',
         reason='tester start date (TimeCurrent) is in the tester configuration, not the SET'),
    dict(lines=(3949,), anchor='dt_Fwrd_OOS<TimeCurrent()', condition='EXPORT && dt_FOOS_start before the test start',
         reason='tester start date (TimeCurrent) is in the tester configuration, not the SET'),
    dict(lines=(3961,), anchor='TimeCurrent()>Expiry', condition='build expired', reason='current time vs build expiry'),
    dict(lines=(4123,), anchor='Export is only allowed in back testing mode', condition='EXPORT on a live chart',
         reason='run context (live chart)'),
    dict(lines=(4137, 4141, 4142, 4144), anchor='Operation_Report',
         condition='live, licensed, Mode_Operation==Operation_Report: report dialog then always INIT_FAILED',
         reason='run context (live chart + license); the report tool ends init by design'),
    dict(lines=(4151,), anchor='Allow DLL imports for GOAT', condition='Studio/Dashboard without DLL imports', reason='terminal setting'),
    dict(lines=(4208,), anchor='Tester GUI creation Failed', condition='Studio GUI creation fails', reason='chart/GUI runtime'),
    dict(lines=(4229,), anchor='Dashboard resume refused: saved state and first chart are required', condition='dashboard resume without saved state', reason='chart and saved dashboard state'),
    dict(lines=(4246,), anchor='Wrong Chart Position', condition='dashboard not on the first chart, user declines', reason='chart layout and user choice'),
    dict(lines=(4269, 4270), anchor='Dashboard Launch Cancelled',
         condition='user cancels dashboard resume prompt (4270: unreachable ExpertRemove after the return)', reason='user choice'),
    dict(lines=(4280,), anchor='No valid .set files found', condition='dashboard finds no SETs/config', reason='files on disk'),
    dict(lines=(4288,), anchor='Dashboard GUI creation Failed', condition='dashboard GUI creation fails', reason='chart/GUI runtime'),
    dict(lines=(4338,), anchor='GOATDeviceActivationBegin(AccountInfoInteger(ACCOUNT_LOGIN),GOAT_BUILD_ID,true)',
         condition='credential rejected and replacement cannot begin', reason='license service response'),
    dict(lines=(4344,), anchor='GOAT license service is temporarily unavailable', condition='license service unavailable', reason='license service response'),
    dict(lines=(4349,), anchor='Sleep(20000)', condition='license invalid', reason='license service response'),
    dict(lines=(4467,), anchor='iATR failed', condition='iATR handle invalid', reason='symbol/indicator runtime'),
    dict(lines=(4475,), anchor='iMA-on-ATR failed', condition='iMA-on-ATR handle invalid', reason='symbol/indicator runtime'),
    dict(lines=(4546,), anchor='Exporting CSV/SET is not allowed in Optimization mode', condition='EXPORT in optimization/forward',
         reason='run context (optimization)'),
    dict(lines=(4547,), anchor='GoatSeqClaimAttempt()', condition='sequence export attempt already claimed', reason='files on disk'),
    dict(lines=(4555,), anchor='GoatSeqPathFits', condition='sequence export path too long', reason='symbol name, terminal paths'),
    dict(lines=(4560,), anchor='Failed to open/create the CSV file', condition='export CSV cannot be opened', reason='file system'),
)


# ---- evaluation ---------------------------------------------------------------------------------------------
def _typed(number, definition):
    kind = definition['type']
    if kind in ('double', 'float'):
        return float(number)
    if kind == 'bool':
        return bool(number)
    return int(number)


def _decimal_text(number):
    if number.denominator == 1:
        return str(number.numerator)
    with localcontext() as context:
        context.prec = 60
        text = format((Decimal(number.numerator) / Decimal(number.denominator)).normalize(), 'f')
    return text


def _display(text, definition):
    choices = definition.get('enum_choices')
    if choices:
        labels = [label for label, value in choices.items() if str(value) == text]
        if labels:
            return text + ' (' + labels[0] + ')'
    return text


def _domain(encoded, definition):
    """Every (typed value, SET text) MT5 can run this input with: the current value, then an active ladder."""
    if definition['type'] == 'string':
        yield encoded, encoded
        return
    parts = encoded.split('||')
    current = numeric(parts[0], definition)
    yield _typed(current, definition), _display(parts[0], definition)
    if len(parts) == 5 and parts[4] == 'Y':
        start, step = numeric(parts[1], definition), numeric(parts[2], definition, step=True)
        stop = numeric(parts[3], definition)
        count = int((stop-start)/step)+1
        for index in range(count):
            value = start+index*step
            if value != current:
                yield _typed(value, definition), _display(_decimal_text(value), definition)


def _active_ladder(encoded, definition):
    parts = encoded.split('||')
    return definition['type'] != 'string' and len(parts) == 5 and parts[4] == 'Y'


def _first_failure(rule, encoded, definitions, choices):
    evaluated = 0

    def explore(bound):
        nonlocal evaluated
        try:
            failed = rule['predicate'](_View(bound, choices))
        except _Need as need:
            for value in _domain(encoded[need.name], definitions[need.name]):
                hit = explore({**bound, need.name: value})
                if hit is not None:
                    return hit
            return None
        evaluated += 1
        if evaluated > MAX_COMBINATIONS:
            raise _TooMany(sorted(bound))
        return bound if failed else None

    return explore({})


def applicable_rules(schema, table=EA_INIT_RULES):
    """The rules this schema can express. Fails closed on a GOAT interface that lost a rule's input or enum label."""
    inputs = schema['inputs']
    goat = GOAT_INTERFACE_MARKER in inputs
    rules = []
    for rule in table:
        missing = [name for name in rule['inputs'] if name not in inputs]
        labels = [name + '.' + label for name, wanted in rule['enums'].items() if name in inputs
                  for label in wanted if label not in (inputs[name].get('enum_choices') or {})]
        if not missing and not labels:
            rules.append(rule)
        elif goat:
            raise ValueError(EA_INIT_SCHEMA_CODE + ': this input schema has no ' + ', '.join(missing + labels)
                             + ' for EA init rule ' + rule['id'] + ' (' + EA_SOURCE + ':' + _lines(rule)
                             + '); the rule cannot be checked, so nothing is accepted')
    return rules


def _lines(rule):
    return ','.join(str(line) for line in rule['lines'])


def _enforce(table, values, schema, code, refused, where=''):
    definitions = schema['inputs']
    rules = applicable_rules(schema, table)
    if not rules:
        return
    from studio_template_tools import schema_default
    choices = {name: definition.get('enum_choices') or {} for name, definition in definitions.items()}
    for rule in rules:
        encoded = {name: values[name] if name in values else schema_default(name, definitions[name], schema.get('defines'))
                   for name in rule['inputs']}
        try:
            failure = _first_failure(rule, encoded, definitions, choices)
        except _TooMany:
            ladders = sorted(name for name in rule['inputs'] if _active_ladder(encoded[name], definitions[name]))
            raise ValueError(code + ': ' + where + rule['id'] + ' (' + EA_SOURCE + ':' + _lines(rule) + ') cannot be '
                             'checked: the optimization ranges of ' + ', '.join(ladders) + ' give more than '
                             + format(MAX_COMBINATIONS, ',') + ' combinations for this EA init rule; narrow them') from None
        if failure is not None:
            combination = ', '.join(name + '=' + shown for name, (_, shown) in failure.items())   # in the order the EA reads them
            ranged = [name for name in failure if _active_ladder(encoded[name], definitions[name])]
            reach = (' (reachable through the optimization range of ' + ', '.join(ranged) + ')') if ranged else ''
            note = (' ' + rule['note']) if rule.get('note') else ''
            raise ValueError(code + ': ' + where + refused + ' Rule ' + rule['id'] + ' ('
                             + EA_SOURCE + ':' + _lines(rule) + ') fails for ' + combination + reach
                             + '. EA alert: "' + rule['alert'] + '"' + note)


def check_ea_init(values, schema):
    """Refuse a SET that GOAT's OnInit would refuse from its input values alone, for any reachable combination."""
    _enforce(EA_INIT_RULES, values, schema, EA_INIT_CODE, 'the EA refuses this SET at initialization.')


def check_tester_init(values, schema, *, where=''):
    """Batch prepare only (P-beta38-prepare-tester-ai-bias): refuse a SET whose OnInit refuses it in the strategy
    tester (tester, optimization and forward passes) although it is valid on a live chart. Same reachable-value
    evaluation as check_ea_init; validate-set and live paths do not call this."""
    _enforce(TESTER_INIT_RULES, values, schema, TESTER_INIT_CODE,
             'the EA refuses this SET in the strategy tester (every optimization pass would end at OnInit with no '
             'result); it stays valid on a live chart.', where)
