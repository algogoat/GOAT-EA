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

from studio_strategy_settings import APPENDED_GROUPS, numeric

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
    # GOAT V1.49.mq5:4620-4625. parts/hm are declared `string parts[2], hm[2]`; the documented StringSplit
    # count is mirrored (see the PR inventory for the static-array caveat).
    if _mql_split_count(text, '-') != 2:
        return True
    start, end = text.split('-')
    return _mql_split_count(start, ':') != 2 or _mql_split_count(end, ':') != 2


_TRIM = ' \t\r\n'


def _desc_keys(text):
    """ExtractFunctionKeysFromInputString (GOAT V1.49.mq5:11007): key/value pairs of the `@{...}` section."""
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
    """(is EXPORT, {name: datetime|0|None}) as OnInit lines 4531-4561 read them from EA_Desc."""
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


# ---- the lot/exit/RRR chain (GOAT V1.49.mq5:4704-4720, 4921-4995) --------------------------------------------
def _risk_per_seq(v):
    return v['Mode_Lots'] == v.choice('Mode_Lots', 'RiskperSeq')


def _peak_smart(v):
    return v['Mode_Lots_Prog'] == v.choice('Mode_Lots_Prog', 'Lots_Prog_PeakSmart')


def _rrr_on(v):
    return v['Mode_RRR'] != v.choice('Mode_RRR', 'RRR_Disabled')


def _tp_size(v):
    return v['TP_Pips'] * v['Lock_Profit_Size']          # TP_Pips_ = TP_Pips*LP_Size_ (line 4709)


def _lp_tp_both_disabled(v):
    """Line 5044 after the RRR block may have derived TP, SL or LP, and lines 5042-5043 zero sizes under 1."""
    lp = v['Lock_Profit_Size']
    tp = v['TP_Pips'] * lp
    if _rrr_on(v):
        rrr = v['RRR']
        if rrr <= 0:
            return False                                  # refused earlier (4953/4954); 4995 is not reached
        sl = v['SL_Pips']
        if v['Mode_RRR'] == v.choice('Mode_RRR', 'RRR_SL_TP'):
            if sl != 0:
                if tp != 0:
                    return False                          # refused at 4959
                tp = sl * rrr
            elif tp == 0:
                return False                              # refused at 4965
        elif v['Mode_RRR'] == v.choice('Mode_RRR', 'RRR_SL_LP'):
            if sl != 0:
                if lp != 0:
                    return False                          # refused at 4972
                lp = sl * rrr
            elif lp == 0:
                return False                              # refused at 4978
    if -1.0 < lp < 1.0:
        lp = 0
    if -1.0 < tp < 1.0:
        tp = 0
    return lp == 0 and tp == 0


def _rule(rule_id, lines, anchor, inputs, enums, condition, alert, predicate, note=None):
    return dict(id=rule_id, source=EA_SOURCE, lines=tuple(lines), anchor=anchor, inputs=tuple(inputs),
                enums=enums, condition=condition, alert=alert, predicate=predicate, note=note)


def _download_removes_ea(v):
    """OnInit lines 4579-4612: a News download removes the EA at 4594 (unless NewsBias), any Bias download at 4611."""
    mode = v['Mode_Download']
    news = mode in (v.choice('Mode_Download', 'Download_News'), v.choice('Mode_Download', 'Download_NewsBias'))
    bias = mode in (v.choice('Mode_Download', 'Download_Bias'), v.choice('Mode_Download', 'Download_NewsBias'))
    return (news and mode != v.choice('Mode_Download', 'Download_NewsBias')) or bias


def _tester_control_tower_bias(v):
    """OnInit 4443: test context && Mode_Bias!=Bias_Disabled && GOATUsingControlTowerBias() (GOATAIWireV2.mqh:640);
    the DemoRaw protocol only exists, and only counts, when the build defines GOAT_AI_WIRE_V2_DEMO_RAW_SUPPORTED,
    which the schema shows by declaring that enum label."""
    if v['Mode_Bias'] == v.choice('Mode_Bias', 'Bias_Disabled'):
        return False
    protocol = v['Bias_Protocol']
    return (protocol == v.choice('Bias_Protocol', 'BiasProtocol_ControlTowerV2')
            or (v.has('Bias_Protocol', 'BiasProtocol_ControlTowerV2DemoRaw')
                and protocol == v.choice('Bias_Protocol', 'BiasProtocol_ControlTowerV2DemoRaw')))


def _bad_ny_session(text):
    """B50 (A0), GOAT V1.49.mq5:5104-5115: NY_Session is HH:MM-HH:MM, hours 0-23 written with one or two digits,
    minutes 0-59 with two (the EA round-trips each part through StringToInteger/IntegerToString), start != end."""
    if _mql_split_count(text, '-') != 2:
        return True
    minutes = []
    for half in text.split('-'):
        if _mql_split_count(half, ':') != 2:
            return True
        hours, mins = half.split(':')
        if not re.fullmatch(r'[0-9]{1,2}', hours) or not re.fullmatch(r'[0-9]{2}', mins):
            return True
        if int(hours) > 23 or int(mins) > 59:
            return True
        minutes.append(int(hours) * 60 + int(mins))
    return minutes[0] == minutes[1]


def _single(v):
    return v['Engine_Mode'] == v.choice('Engine_Mode', 'Engine_Single')


# B54 (docs/b54/BREAKOUT_ENTRIES_SPEC.md 4.6, GOAT V1.49.mq5:5171-5199): the breakout entries' families and ORB's window.
def _brk(v):
    return v['BRK_Mode'] != v.choice('BRK_Mode', 'BRK_Disabled')


def _orb(v):
    return v['ORB_Mode'] != v.choice('ORB_Mode', 'ORB_Disabled')


def _orb_lim(v):
    """Spec 4.1/4.4: Lim, 17:00 NY in minutes after the anchor's midnight: 1020 under the New York anchor, 1260 (21:00
    London, while the US is on DST and the EU is not) under the London anchor."""
    return 1260 if v['ORB_Clock'] == v.choice('ORB_Clock', 'ORB_Clock_London') else 1020


ORB_TFS = ('TF_M1', 'TF_M5', 'TF_M15', 'TF_H1')


def _orb_minutes(v):
    """ORB_TF_'s minutes, which its enum value names (TF_M1=1 ... TF_H1=60), or None for a timeframe ORB_TF_NOT_M1_TO_H1
    refuses first (the EA never reaches the window rules with one; ORB_Start_Minute%0 is never computed)."""
    tf = v['ORB_TF_']
    return tf if tf in {v.choice('ORB_TF_', label) for label in ORB_TFS} else None


def _orb_misaligned(v, name):
    minutes = _orb_minutes(v)
    return minutes is not None and v[name] % minutes != 0


SESSION_INPUTS = ('Active_Time_ASIA', 'Active_Time_EU', 'Active_Time_US')
RRR_CHAIN = ('Mode_RRR', 'RRR', 'SL_Pips', 'TP_Pips', 'Lock_Profit_Size')

# In OnInit order: the first rule that fails is the one the EA reports.
EA_INIT_RULES = (
    _rule('EXPORT_FOOS_NOT_AFTER_BOOS', [4566], 'dt_Fwrd_OOS<=dt_Back_OOS', ['EA_Desc'], {},
          'EA_Desc @{mode=EXPORT}: dt_BOOS_end!=0 && dt_FOOS_start!=0 && dt_FOOS_start<=dt_BOOS_end',
          'EXPORT: dt_FOOS_start:<date> must be after dt_BOOS_end',
          _export_rule('dt_BOOS_end', 'dt_FOOS_start', _foos_not_after_boos)),
    _rule('EXPORT_FWD_HALF_GIVEN', [4567], '(dt_FWD_start!=0 || dt_FWD_end!=0) && (dt_FWD_start==0 || dt_FWD_end==0)',
          ['EA_Desc'], {}, 'EA_Desc @{mode=EXPORT}: exactly one of dt_FWD_start/dt_FWD_end set',
          'EXPORT: dt_FWD_start and dt_FWD_end must both be provided',
          _export_rule('dt_FWD_start', 'dt_FWD_end', _fwd_half_given)),
    _rule('EXPORT_FWD_END_BEFORE_START', [4568], 'dt_FWD_end<dt_FWD_start', ['EA_Desc'], {},
          'EA_Desc @{mode=EXPORT}: dt_FWD_start!=0 && dt_FWD_end!=0 && dt_FWD_end<dt_FWD_start',
          'EXPORT: dt_FWD_end:<date> must be after dt_FWD_start',
          _export_rule('dt_FWD_start', 'dt_FWD_end', _fwd_end_before_start)),
    _rule('DATA_DOWNLOAD_MODE_REMOVES_EA', [4594, 4611], 'History download is not allowed in this mode', ['Mode_Download'],
          {'Mode_Download': ['Download_Disabled', 'Download_News', 'Download_Bias', 'Download_NewsBias']},
          'Mode_Download in (Download_News, Download_Bias, Download_NewsBias): ExpertRemove() in OnInit',
          'News History download is not allowed in this mode / Bias History download is not allowed in this mode',
          _download_removes_ea,
          note=('In the tester the EA prints that and removes itself; on a live chart it downloads the data files and '
                'then removes itself (ExpertRemove, GOAT V1.49.mq5:4594/4562). Mode_Download is the "Data Download '
                'Mode for Backtest" data tool, never a strategy setting: use Download_Disabled.')),
    _rule('SESSION_FORMAT', [4620, 4622, 4625], 'Session format must be HH:MM-HH:MM', SESSION_INPUTS, {},
          'Active_Time_ASIA/EU/US: StringSplit(s,\'-\')!=2, or either half StringSplit(h,\':\')!=2',
          'Session format must be HH:MM-HH:MM', lambda v: any(_bad_session(v[name]) for name in SESSION_INPUTS)),
    _rule('RISK_PER_SEQUENCE_RISK_TOO_LOW', [4974], 'Mode_Lots == RiskperSeq && Risk<10', ['Mode_Lots', 'Risk'],
          {'Mode_Lots': ['RiskperSeq']}, 'Mode_Lots==RiskperSeq && Risk<10',
          'Initialization Stopped Manually: You have selected Risk per Sequence but your Risk Amount is too low.',
          lambda v: _risk_per_seq(v) and v['Risk'] < 10),
    _rule('MLPS_HARD_CLOSE_RISK_TOO_LOW', [4976], 'Sequence_MLPS_Hard_Close && Risk<10.0',
          ['Sequence_MLPS_Hard_Close', 'Risk'], {}, 'Sequence_MLPS_Hard_Close && Risk<10.0',
          'Initialization Failed: Sequence MLPS hard close requires Risk/MLPS amount of at least 10.',
          lambda v: v['Sequence_MLPS_Hard_Close'] and v['Risk'] < 10.0),
    _rule('SMART_PEAK_RISK_TOO_LOW', [4982], 'Smart Peak requires Risk/MLPS amount of at least 10',
          ['Mode_Lots_Prog', 'Risk'], {'Mode_Lots_Prog': ['Lots_Prog_PeakSmart']},
          'Mode_Lots_Prog==Lots_Prog_PeakSmart && Risk<10.0',
          'Initialization Failed: Smart Peak requires Risk/MLPS amount of at least 10.',
          lambda v: _peak_smart(v) and v['Risk'] < 10.0),
    _rule('SMART_PEAK_PERCENT_RANGE', [4987],
          'Peak_Smart_Release_PC<0.0 || Peak_Smart_Release_PC>100.0 || Peak_Smart_Max_Close_PC<0.0 || Peak_Smart_Max_Close_PC>100.0',
          ['Mode_Lots_Prog', 'Peak_Smart_Release_PC', 'Peak_Smart_Max_Close_PC'], {'Mode_Lots_Prog': ['Lots_Prog_PeakSmart']},
          'Mode_Lots_Prog==Lots_Prog_PeakSmart && (Peak_Smart_Release_PC or Peak_Smart_Max_Close_PC outside 0..100)',
          'Initialization Failed: Smart Peak inputs must use 0-100 percent ranges.',
          lambda v: _peak_smart(v) and (v['Peak_Smart_Release_PC'] < 0.0 or v['Peak_Smart_Release_PC'] > 100.0
                                        or v['Peak_Smart_Max_Close_PC'] < 0.0 or v['Peak_Smart_Max_Close_PC'] > 100.0)),
    _rule('SMART_RESCUE_MAX_ADDS_BELOW_MINUS_ONE', [4990], 'Bias_Exit_Max_Exposure_Adds<-1',
          ['Bias_Exit_Max_Exposure_Adds'], {}, 'Bias_Exit_Max_Exposure_Adds<-1',
          'Initialization Failed: Smart Rescue max positive adds cannot be less than -1.',
          lambda v: v['Bias_Exit_Max_Exposure_Adds'] < -1),
    _rule('SMART_RESCUE_NEEDS_RISK_PER_SEQUENCE', [4996], 'Mode_Lots!=RiskperSeq || Risk<=0.0',
          ['Mode_Bias_Exit', 'Mode_Lots', 'Risk'],
          {'Mode_Bias_Exit': ['BiasExit_SmartRescue'], 'Mode_Lots': ['RiskperSeq']},
          'Mode_Bias_Exit==BiasExit_SmartRescue && (Mode_Lots!=RiskperSeq || Risk<=0.0)',
          'Initialization Failed: Smart Rescue requires Risk per Sequence lot sizing and Risk > 0.',
          lambda v: v['Mode_Bias_Exit'] == v.choice('Mode_Bias_Exit', 'BiasExit_SmartRescue')
          and (not _risk_per_seq(v) or v['Risk'] <= 0.0)),
    _rule('RRR_NEGATIVE', [5002], 'if(RRR<0)', ['Mode_RRR', 'RRR'], {'Mode_RRR': ['RRR_Disabled']},
          'Mode_RRR!=RRR_Disabled && RRR<0', 'Initialization Failed: Risk/Reward ratio cannot be negative',
          lambda v: _rrr_on(v) and v['RRR'] < 0),
    _rule('RRR_ZERO', [5003], 'if(RRR==0)', ['Mode_RRR', 'RRR'], {'Mode_RRR': ['RRR_Disabled']},
          'Mode_RRR!=RRR_Disabled && RRR==0', 'Initialization Failed: Risk/Reward ratio is enabled but RRR=0',
          lambda v: _rrr_on(v) and v['RRR'] == 0),
    _rule('RRR_SL_TP_BOTH_SET', [5008], 'Risk/Reward mode is SL/TP, but neither TP nor SL is zero',
          ['Mode_RRR', 'SL_Pips', 'TP_Pips', 'Lock_Profit_Size'], {'Mode_RRR': ['RRR_SL_TP']},
          'Mode_RRR==RRR_SL_TP && SL_Pips!=0 && TP_Pips*Lock_Profit_Size!=0',
          'Initialization Failed: Risk/Reward mode is SL/TP, but neither TP nor SL is zero',
          lambda v: v['Mode_RRR'] == v.choice('Mode_RRR', 'RRR_SL_TP') and v['SL_Pips'] != 0 and _tp_size(v) != 0),
    _rule('RRR_SL_TP_BOTH_ZERO', [5014], 'Risk/Reward mode is SL/TP, but both TP and SL are zero',
          ['Mode_RRR', 'SL_Pips', 'TP_Pips', 'Lock_Profit_Size'], {'Mode_RRR': ['RRR_SL_TP']},
          'Mode_RRR==RRR_SL_TP && SL_Pips==0 && TP_Pips*Lock_Profit_Size==0',
          'Initialization Failed: Risk/Reward mode is SL/TP, but both TP and SL are zero',
          lambda v: v['Mode_RRR'] == v.choice('Mode_RRR', 'RRR_SL_TP') and v['SL_Pips'] == 0 and _tp_size(v) == 0),
    _rule('RRR_SL_LP_BOTH_SET', [5021], 'Risk/Reward mode is SL/LP, but neither LP nor SL is zero',
          ['Mode_RRR', 'SL_Pips', 'Lock_Profit_Size'], {'Mode_RRR': ['RRR_SL_LP']},
          'Mode_RRR==RRR_SL_LP && SL_Pips!=0 && Lock_Profit_Size!=0',
          'Initialization Failed: Risk/Reward mode is SL/LP, but neither LP nor SL is zero',
          lambda v: v['Mode_RRR'] == v.choice('Mode_RRR', 'RRR_SL_LP') and v['SL_Pips'] != 0 and v['Lock_Profit_Size'] != 0),
    _rule('RRR_SL_LP_BOTH_ZERO', [5027], 'Risk/Reward mode is SL/LP, but both LP and SL are zero',
          ['Mode_RRR', 'SL_Pips', 'Lock_Profit_Size'], {'Mode_RRR': ['RRR_SL_LP']},
          'Mode_RRR==RRR_SL_LP && SL_Pips==0 && Lock_Profit_Size==0',
          'Initialization Failed: Risk/Reward mode is SL/LP, but both LP and SL are zero',
          lambda v: v['Mode_RRR'] == v.choice('Mode_RRR', 'RRR_SL_LP') and v['SL_Pips'] == 0 and v['Lock_Profit_Size'] == 0),
    _rule('GRID_SIZE_TOO_SMALL', [5039], 'Grid_Size >-0.5 && Grid_Size <0.5', ['Grid_Size'], {},
          'Grid_Size>-0.5 && Grid_Size<0.5', 'Initialization Failed: Pip Gap Size too small or zero',
          lambda v: -0.5 < v['Grid_Size'] < 0.5),
    _rule('LP_AND_TP_BOTH_DISABLED', [5044], 'LP_Size_  ==0   && TP_Pips_  ==0', RRR_CHAIN,
          {'Mode_RRR': ['RRR_Disabled', 'RRR_SL_TP', 'RRR_SL_LP']},
          'after the RRR block and the |x|<1 -> 0 normalisation of lines 5042-5043: LP_Size_==0 && TP_Pips_==0',
          'Initialization Failed: Both LP and TP cannot be zero/disabled.', _lp_tp_both_disabled),
    # B50 (A0): the single-trade engine and the New York clock (GOAT V1.49.mq5:5093-5132). A schema without these
    # appended inputs belongs to a build without the rules (applicable_rules).
    _rule('SINGLE_SL_ATR_NOT_POSITIVE', [5097], 'Engine_Mode==Engine_Single && Single_SL_ATR<=0.0',
          ['Engine_Mode', 'Single_SL_ATR'], {'Engine_Mode': ['Engine_Single']},
          'Engine_Mode==Engine_Single && Single_SL_ATR<=0.0',
          'Initialization Failed: the single-trade engine needs Single_SL_ATR > 0.',
          lambda v: _single(v) and v['Single_SL_ATR'] <= 0.0),
    _rule('SINGLE_TP_NEGATIVE', [5098], 'Single_TP_ATR<0.0 || Single_TP_R<0.0', ['Single_TP_ATR', 'Single_TP_R'], {},
          'Single_TP_ATR<0.0 || Single_TP_R<0.0',
          'Initialization Failed: Single_TP_ATR and Single_TP_R cannot be negative.',
          lambda v: v['Single_TP_ATR'] < 0.0 or v['Single_TP_R'] < 0.0),
    _rule('SINGLE_TIME_STOP_BARS_NEGATIVE', [5099], 'Single_Time_Stop_Bars<0', ['Single_Time_Stop_Bars'], {},
          'Single_Time_Stop_Bars<0', 'Initialization Failed: Single_Time_Stop_Bars cannot be negative.',
          lambda v: v['Single_Time_Stop_Bars'] < 0),
    _rule('ROLLOVER_BLOCK_NEGATIVE', [5100], 'Rollover_Block_Minutes<0', ['Rollover_Block_Minutes'], {},
          'Rollover_Block_Minutes<0', 'Initialization Failed: Rollover_Block_Minutes cannot be negative.',
          lambda v: v['Rollover_Block_Minutes'] < 0),
    _rule('SERVER_UTC_OFFSET_RANGE', [5101], 'Server_UTC_Offset<-12 || Server_UTC_Offset>14', ['Server_UTC_Offset'], {},
          'Server_UTC_Offset<-12 || Server_UTC_Offset>14',
          'Initialization Failed: Server_UTC_Offset must be between -12 and 14.',
          lambda v: v['Server_UTC_Offset'] < -12 or v['Server_UTC_Offset'] > 14),
    _rule('SINGLE_WITH_SMART_RESCUE', [5103], 'Engine_Mode==Engine_Single && Mode_Bias_Exit==BiasExit_SmartRescue',
          ['Engine_Mode', 'Mode_Bias_Exit'], {'Engine_Mode': ['Engine_Single'], 'Mode_Bias_Exit': ['BiasExit_SmartRescue']},
          'Engine_Mode==Engine_Single && Mode_Bias_Exit==BiasExit_SmartRescue (Claude-Mac ruling 4)',
          'Initialization Failed: Smart Rescue cannot run with the single-trade engine (it would move the single\'s stop '
          'to rescue levels).',
          lambda v: _single(v) and v['Mode_Bias_Exit'] == v.choice('Mode_Bias_Exit', 'BiasExit_SmartRescue')),
    _rule('NY_SESSION_FORMAT', [5115], 'NY_Session must be HH:MM-HH:MM', ['NY_Session'], {},
          'NY_Session not HH:MM-HH:MM (hours 0-23, two-digit minutes 0-59), or start==end',
          'Initialization Failed: NY_Session must be HH:MM-HH:MM with different start and end times.',
          lambda v: _bad_ny_session(v['NY_Session'])),
    # B51 (beta-1a, beta-1b, section 8.3): the random-direction benchmark, the single's break-even and trailing and its partial close (GOAT V1.49.mq5:5133-5152). A schema without these appended inputs
    # (B50-alpha and earlier) belongs to a build without the rules (applicable_rules, APPENDED_GROUPS).
    _rule('RANDOM_DIRECTION_WITHOUT_SINGLE', [5138], 'Random_Direction && Engine_Mode!=Engine_Single',
          ['Random_Direction', 'Engine_Mode'], {'Engine_Mode': ['Engine_Single']},
          'Random_Direction && Engine_Mode!=Engine_Single',
          'Initialization Failed: Random_Direction needs the single-trade engine (Engine_Mode=Engine_Single).',
          lambda v: bool(v['Random_Direction']) and not _single(v)),
    _rule('RANDOM_SEED_NEGATIVE', [5139], 'Random_Seed<0', ['Random_Seed'], {}, 'Random_Seed<0',
          'Initialization Failed: Random_Seed cannot be negative.', lambda v: v['Random_Seed'] < 0),
    _rule('RANDOM_DIRECTION_ONE_DIRECTION', [5140], 'Random_Direction && Mode_Trade!=Long_and_Short',
          ['Random_Direction', 'Mode_Trade'], {'Mode_Trade': ['Long_and_Short']},
          'Random_Direction && Mode_Trade!=Long_and_Short (review of GOAT-EA#286, P2-3)',
          'Initialization Failed: Random_Direction needs Mode_Trade=Long_and_Short (a coin flip needs both sides).',
          lambda v: bool(v['Random_Direction']) and v['Mode_Trade'] != v.choice('Mode_Trade', 'Long_and_Short')),
    _rule('RANDOM_DIRECTION_WITHOUT_FLAT_ONLY', [5141], 'Random_Direction && !Single_Flat_Only',
          ['Random_Direction', 'Single_Flat_Only'], {},
          'Random_Direction && !Single_Flat_Only (re-review of GOAT-EA#286: the same eligibility for both arms)',
          'Initialization Failed: Random_Direction needs Single_Flat_Only=true (the same eligibility for both arms).',
          lambda v: bool(v['Random_Direction']) and not v['Single_Flat_Only']),
    _rule('SINGLE_FLAT_ONLY_WITHOUT_SINGLE', [5142], 'Single_Flat_Only && Engine_Mode!=Engine_Single',
          ['Single_Flat_Only', 'Engine_Mode'], {'Engine_Mode': ['Engine_Single']},
          'Single_Flat_Only && Engine_Mode!=Engine_Single',
          'Initialization Failed: Single_Flat_Only needs the single-trade engine (Engine_Mode=Engine_Single).',
          lambda v: bool(v['Single_Flat_Only']) and not _single(v)),
    # B52 (the final build's review, P3): Gate_AtFirstOrder rechecks the bias on the side the signal reads, but the
    # benchmark's draw can pick the other side, so the random single could open against its bias.
    _rule('RANDOM_DIRECTION_WITH_FIRST_ORDER_GATE', [5170], 'Random_Direction && Gate_Recheck==Gate_AtFirstOrder',
          ['Random_Direction', 'Gate_Recheck'], {'Gate_Recheck': ['Gate_AtFirstOrder']},
          'Random_Direction && Gate_Recheck==Gate_AtFirstOrder (review of the final build, P3)',
          'Initialization Failed: Random_Direction cannot run with Gate_Recheck=Gate_AtFirstOrder (the first-order gate reads '
          "the signal's side; the draw can pick the other).",
          lambda v: bool(v['Random_Direction']) and v['Gate_Recheck'] == v.choice('Gate_Recheck', 'Gate_AtFirstOrder')),
    _rule('SINGLE_BE_TRAIL_NEGATIVE', [5144], 'Single_BE_ATR<0.0 || Single_Trail_Start_ATR<0.0 || Single_Trail_ATR<0.0',
          ['Single_BE_ATR', 'Single_Trail_Start_ATR', 'Single_Trail_ATR'], {},
          'Single_BE_ATR<0.0 || Single_Trail_Start_ATR<0.0 || Single_Trail_ATR<0.0',
          'Initialization Failed: Single_BE_ATR, Single_Trail_Start_ATR and Single_Trail_ATR cannot be negative.',
          lambda v: v['Single_BE_ATR'] < 0.0 or v['Single_Trail_Start_ATR'] < 0.0 or v['Single_Trail_ATR'] < 0.0),
    _rule('SINGLE_TRAIL_START_WITHOUT_DISTANCE', [5145], 'Single_Trail_Start_ATR>0.0 && !(Single_Trail_ATR>0.0)',
          ['Single_Trail_Start_ATR', 'Single_Trail_ATR'], {},
          'Single_Trail_Start_ATR>0.0 && !(Single_Trail_ATR>0.0) (review of GOAT-EA#287, P3-10)',
          'Initialization Failed: Single_Trail_Start_ATR needs Single_Trail_ATR > 0 (a trailing start without a distance).',
          lambda v: v['Single_Trail_Start_ATR'] > 0.0 and not v['Single_Trail_ATR'] > 0.0),
    _rule('SINGLE_EXITS_WITHOUT_SINGLE', [5146],
          'Engine_Mode!=Engine_Single && (Single_BE_ATR>0.0 || Single_Trail_Start_ATR>0.0 || Single_Trail_ATR>0.0)',
          ['Engine_Mode', 'Single_BE_ATR', 'Single_Trail_Start_ATR', 'Single_Trail_ATR'], {'Engine_Mode': ['Engine_Single']},
          'Engine_Mode!=Engine_Single && (Single_BE_ATR>0.0 || Single_Trail_Start_ATR>0.0 || Single_Trail_ATR>0.0) (review of GOAT-EA#287, P3-10)',
          'Initialization Failed: Single_BE_ATR, Single_Trail_Start_ATR and Single_Trail_ATR need the single-trade engine (Engine_Mode=Engine_Single).',
          lambda v: not _single(v) and (v['Single_BE_ATR'] > 0.0 or v['Single_Trail_Start_ATR'] > 0.0 or v['Single_Trail_ATR'] > 0.0)),
    _rule('SINGLE_PARTIAL_NEGATIVE', [5147], 'Single_Partial_ATR<0.0 || Single_Partial_Fraction<0.0',
          ['Single_Partial_ATR', 'Single_Partial_Fraction'], {},
          'Single_Partial_ATR<0.0 || Single_Partial_Fraction<0.0',
          'Initialization Failed: Single_Partial_ATR and Single_Partial_Fraction cannot be negative.',
          lambda v: v['Single_Partial_ATR'] < 0.0 or v['Single_Partial_Fraction'] < 0.0),
    _rule('SINGLE_PARTIAL_FRACTION_NOT_BELOW_ONE', [5148], 'Single_Partial_Fraction>=1.0',
          ['Single_Partial_Fraction'], {},
          'Single_Partial_Fraction>=1.0',
          'Initialization Failed: Single_Partial_Fraction must be below 1 (closing it all is not a partial close).',
          lambda v: v['Single_Partial_Fraction'] >= 1.0),
    _rule('SINGLE_PARTIAL_INCOMPLETE', [5149], '(Single_Partial_ATR>0.0)!=(Single_Partial_Fraction>0.0)',
          ['Single_Partial_ATR', 'Single_Partial_Fraction'], {},
          '(Single_Partial_ATR>0.0)!=(Single_Partial_Fraction>0.0)',
          'Initialization Failed: Single_Partial_ATR and Single_Partial_Fraction need each other (a trigger and a fraction).',
          lambda v: (v['Single_Partial_ATR'] > 0.0) != (v['Single_Partial_Fraction'] > 0.0)),
    _rule('SINGLE_PARTIAL_BE_WITHOUT_PARTIAL', [5150], 'Single_Partial_BE && !(Single_Partial_ATR>0.0)',
          ['Single_Partial_BE', 'Single_Partial_ATR'], {},
          'Single_Partial_BE && !(Single_Partial_ATR>0.0)',
          'Initialization Failed: Single_Partial_BE needs Single_Partial_ATR > 0 (no partial close, nothing to move the stop on).',
          lambda v: bool(v['Single_Partial_BE']) and not v['Single_Partial_ATR'] > 0.0),
    _rule('SINGLE_PARTIAL_WITHOUT_SINGLE', [5151], 'Engine_Mode!=Engine_Single && Single_Partial_ATR>0.0',
          ['Engine_Mode', 'Single_Partial_ATR'], {'Engine_Mode': ['Engine_Single']},
          'Engine_Mode!=Engine_Single && Single_Partial_ATR>0.0 (the two rules above refuse the fraction and Single_Partial_BE without it)',
          'Initialization Failed: Single_Partial_ATR, Single_Partial_Fraction and Single_Partial_BE need the single-trade engine (Engine_Mode=Engine_Single).',
          lambda v: not _single(v) and v['Single_Partial_ATR'] > 0.0),
    _rule('SINGLE_PARTIAL_NEEDS_POSITION_JOIN', [5152], 'Single_Partial_ATR>0.0 && Ledger_Mode!=Ledger_PositionJoin',
          ['Single_Partial_ATR', 'Ledger_Mode'], {'Ledger_Mode': ['Ledger_PositionJoin']},
          'Single_Partial_ATR>0.0 && Ledger_Mode!=Ledger_PositionJoin',
          'Initialization Failed: Single_Partial_ATR needs Ledger_Mode=Ledger_PositionJoin (Ledger_Legacy would drop the partial\'s profit from the sequence).',
          lambda v: v['Single_Partial_ATR'] > 0.0 and v['Ledger_Mode'] != v.choice('Ledger_Mode', 'Ledger_PositionJoin')),
    # B54 (spec 4.6, GOAT V1.49.mq5:5171-5199): the breakout entries. A schema without the B54 group (B53 and earlier)
    # belongs to a build without these rules (applicable_rules, APPENDED_GROUPS). A family's ranges apply while it is on.
    _rule('BRK_WITHOUT_SINGLE', [5177], 'BRK_Mode!=BRK_Disabled && Engine_Mode!=Engine_Single',
          ['BRK_Mode', 'Engine_Mode'], {'BRK_Mode': ['BRK_Disabled'], 'Engine_Mode': ['Engine_Single']},
          'BRK_Mode!=BRK_Disabled && Engine_Mode!=Engine_Single (spec 4.6)',
          'Initialization Failed: BRK_Mode needs the single-trade engine (Engine_Mode=Engine_Single).',
          lambda v: _brk(v) and not _single(v)),
    _rule('ORB_WITHOUT_SINGLE', [5178], 'ORB_Mode!=ORB_Disabled && Engine_Mode!=Engine_Single',
          ['ORB_Mode', 'Engine_Mode'], {'ORB_Mode': ['ORB_Disabled'], 'Engine_Mode': ['Engine_Single']},
          'ORB_Mode!=ORB_Disabled && Engine_Mode!=Engine_Single (spec 4.6)',
          'Initialization Failed: ORB_Mode needs the single-trade engine (Engine_Mode=Engine_Single).',
          lambda v: _orb(v) and not _single(v)),
    _rule('BRK_WITH_ORB', [5179], 'BRK_Mode!=BRK_Disabled && ORB_Mode!=ORB_Disabled',
          ['BRK_Mode', 'ORB_Mode'], {'BRK_Mode': ['BRK_Disabled'], 'ORB_Mode': ['ORB_Disabled']},
          'BRK_Mode!=BRK_Disabled && ORB_Mode!=ORB_Disabled (ruling 15: one family per SET)',
          'Initialization Failed: BRK_Mode and ORB_Mode cannot both be on (one breakout family per SET).',
          lambda v: _brk(v) and _orb(v)),
    _rule('BRK_BARS_RANGE', [5180], 'BRK_Mode==BRK_NBar && (BRK_Bars<2 || BRK_Bars>500)',
          ['BRK_Mode', 'BRK_Bars'], {'BRK_Mode': ['BRK_NBar']},
          'BRK_Mode==BRK_NBar && (BRK_Bars<2 || BRK_Bars>500) (spec 3.1 A3)',
          'Initialization Failed: BRK_Bars must be between 2 and 500 with BRK_Mode=BRK_NBar.',
          lambda v: v['BRK_Mode'] == v.choice('BRK_Mode', 'BRK_NBar') and (v['BRK_Bars'] < 2 or v['BRK_Bars'] > 500)),
    _rule('BRK_BUFFER_RANGE', [5181], 'BRK_Mode!=BRK_Disabled && (BRK_Buffer_ATR<0.0 || BRK_Buffer_ATR>5.0)',
          ['BRK_Mode', 'BRK_Buffer_ATR'], {'BRK_Mode': ['BRK_Disabled']},
          'BRK_Mode!=BRK_Disabled && (BRK_Buffer_ATR<0.0 || BRK_Buffer_ATR>5.0) (spec 3.1 A4)',
          'Initialization Failed: BRK_Buffer_ATR must be between 0 and 5.',
          lambda v: _brk(v) and (v['BRK_Buffer_ATR'] < 0.0 or v['BRK_Buffer_ATR'] > 5.0)),
    _rule('BRK_PRIOR_DAY_ON_D1', [5182], 'BRK_Mode==BRK_PriorDay && BRK_TF_==TF_D1',
          ['BRK_Mode', 'BRK_TF_'], {'BRK_Mode': ['BRK_PriorDay'], 'BRK_TF_': ['TF_D1']},
          'BRK_Mode==BRK_PriorDay && BRK_TF_==TF_D1 (spec 3.1 A2; TF_Cur on a D1 chart is NOT_PORTED, 5134)',
          'Initialization Failed: BRK_Mode=BRK_PriorDay needs a trigger timeframe below D1 (BRK_TF_=TF_D1 is the prior '
          "day's own timeframe).",
          lambda v: v['BRK_Mode'] == v.choice('BRK_Mode', 'BRK_PriorDay') and v['BRK_TF_'] == v.choice('BRK_TF_', 'TF_D1')),
    _rule('ORB_TF_NOT_M1_TO_H1', [5185], 'ORB_TF_!=TF_M1 && ORB_TF_!=TF_M5 && ORB_TF_!=TF_M15 && ORB_TF_!=TF_H1',
          ['ORB_Mode', 'ORB_TF_'], {'ORB_Mode': ['ORB_Disabled'], 'ORB_TF_': list(ORB_TFS)},
          'ORB_Mode!=ORB_Disabled && ORB_TF_ not TF_M1/TF_M5/TF_M15/TF_H1 (spec 4.1 B3; TF_Cur is refused: the range must '
          'be counted in minutes the SET names)',
          'Initialization Failed: ORB_TF_ must be TF_M1, TF_M5, TF_M15 or TF_H1 (the range is counted in its minutes).',
          lambda v: _orb(v) and _orb_minutes(v) is None),
    _rule('ORB_START_RANGE', [5186], 'ORB_Start_Minute<0 || ORB_Start_Minute>(ORB_Clock==ORB_Clock_London ? 1260 : 1020)-5',
          ['ORB_Mode', 'ORB_Start_Minute', 'ORB_Clock', 'ORB_TF_'],
          {'ORB_Mode': ['ORB_Disabled'], 'ORB_Clock': ['ORB_Clock_London'], 'ORB_TF_': list(ORB_TFS)},
          'ORB_Mode!=ORB_Disabled && (ORB_Start_Minute<0 || ORB_Start_Minute>Lim-5 || ORB_Start_Minute % ORB_TF_ minutes != 0) '
          '(spec 4.1 B4)',
          'Initialization Failed: ORB_Start_Minute must be between 0 and Lim-5 (Lim is 1020 under ORB_Clock_NewYork, 1260 '
          "under ORB_Clock_London) and a multiple of ORB_TF_'s minutes.",
          lambda v: _orb(v) and (v['ORB_Start_Minute'] < 0 or v['ORB_Start_Minute'] > _orb_lim(v) - 5
                                 or _orb_misaligned(v, 'ORB_Start_Minute'))),
    _rule('ORB_RANGE_MINUTES', [5187], 'ORB_Range_Minutes<5 || ORB_Range_Minutes>240',
          ['ORB_Mode', 'ORB_Range_Minutes', 'ORB_TF_', 'ORB_Start_Minute', 'ORB_Clock'],
          {'ORB_Mode': ['ORB_Disabled'], 'ORB_Clock': ['ORB_Clock_London'], 'ORB_TF_': list(ORB_TFS)},
          'ORB_Mode!=ORB_Disabled && (ORB_Range_Minutes<5 || ORB_Range_Minutes>240 || ORB_Range_Minutes % ORB_TF_ minutes != 0 '
          '|| ORB_Start_Minute+ORB_Range_Minutes>=Lim) (spec 4.1 B5)',
          "Initialization Failed: ORB_Range_Minutes must be between 5 and 240, a multiple of ORB_TF_'s minutes, and end "
          'before Lim (ORB_Start_Minute+ORB_Range_Minutes < Lim).',
          lambda v: _orb(v) and (v['ORB_Range_Minutes'] < 5 or v['ORB_Range_Minutes'] > 240
                                 or _orb_misaligned(v, 'ORB_Range_Minutes')
                                 or v['ORB_Start_Minute'] + v['ORB_Range_Minutes'] >= _orb_lim(v))),
    _rule('ORB_ENTRY_WINDOW', [5188], 'ORB_Entry_Minutes<0 || ORB_Entry_Minutes>(ORB_Clock==ORB_Clock_London ? 1260 : 1020) || ORB_Start_Minute+ORB_Range_Minutes+ORB_Entry_Minutes>',
          ['ORB_Mode', 'ORB_Entry_Minutes', 'ORB_Start_Minute', 'ORB_Range_Minutes', 'ORB_Clock'],
          {'ORB_Mode': ['ORB_Disabled'], 'ORB_Clock': ['ORB_Clock_London']},
          'ORB_Mode!=ORB_Disabled && (ORB_Entry_Minutes<0 || ORB_Entry_Minutes>Lim '
          '|| ORB_Start_Minute+ORB_Range_Minutes+ORB_Entry_Minutes>Lim) (spec 4.1 B6; B6 is bounded before the sum, which a '
          '32-bit int could wrap: Claude-Mac 6764975563)',
          'Initialization Failed: ORB_Entry_Minutes must be between 0 and Lim, and the entry window must end by Lim '
          '(ORB_Start_Minute+ORB_Range_Minutes+ORB_Entry_Minutes <= Lim).',
          lambda v: _orb(v) and (v['ORB_Entry_Minutes'] < 0 or v['ORB_Entry_Minutes'] > _orb_lim(v)
                                 or v['ORB_Start_Minute'] + v['ORB_Range_Minutes'] + v['ORB_Entry_Minutes'] > _orb_lim(v))),
    _rule('ORB_BUFFER_RANGE', [5189], 'ORB_Mode!=ORB_Disabled && (ORB_Buffer_ATR<0.0 || ORB_Buffer_ATR>5.0)',
          ['ORB_Mode', 'ORB_Buffer_ATR'], {'ORB_Mode': ['ORB_Disabled']},
          'ORB_Mode!=ORB_Disabled && (ORB_Buffer_ATR<0.0 || ORB_Buffer_ATR>5.0) (spec 4.1 B7)',
          'Initialization Failed: ORB_Buffer_ATR must be between 0 and 5.',
          lambda v: _orb(v) and (v['ORB_Buffer_ATR'] < 0.0 or v['ORB_Buffer_ATR'] > 5.0)),
    _rule('ORB_RANGE_FILTER_NEGATIVE', [5190], 'ORB_Min_Range_ATR<0.0 || ORB_Max_Range_ATR<0.0',
          ['ORB_Mode', 'ORB_Min_Range_ATR', 'ORB_Max_Range_ATR'], {'ORB_Mode': ['ORB_Disabled']},
          'ORB_Mode!=ORB_Disabled && (ORB_Min_Range_ATR<0.0 || ORB_Max_Range_ATR<0.0) (spec 4.1 B8, B9)',
          'Initialization Failed: ORB_Min_Range_ATR and ORB_Max_Range_ATR cannot be negative (0 = off).',
          lambda v: _orb(v) and (v['ORB_Min_Range_ATR'] < 0.0 or v['ORB_Max_Range_ATR'] < 0.0)),
    _rule('ORB_RANGE_FILTER_ORDER', [5191], 'ORB_Max_Range_ATR<=ORB_Min_Range_ATR',
          ['ORB_Mode', 'ORB_Min_Range_ATR', 'ORB_Max_Range_ATR'], {'ORB_Mode': ['ORB_Disabled']},
          'ORB_Mode!=ORB_Disabled && ORB_Min_Range_ATR>0.0 && ORB_Max_Range_ATR>0.0 && ORB_Max_Range_ATR<=ORB_Min_Range_ATR '
          '(spec 4.1 B9)',
          'Initialization Failed: ORB_Max_Range_ATR must be above ORB_Min_Range_ATR when both are on.',
          lambda v: _orb(v) and v['ORB_Min_Range_ATR'] > 0.0 and v['ORB_Max_Range_ATR'] > 0.0
          and v['ORB_Max_Range_ATR'] <= v['ORB_Min_Range_ATR']),
    # B54 (ruling on GOAT-EA#303, condition 3): a mode value whose signal term the tree did not have yet was refused here and
    # in the EA (INIT_FAILED) until the commit that added its term removed both (the inventory test keeps them in step). PR
    # A's BRK signal commit removed BRK_NBar's and BRK_PriorDay's, and PR B's ORB signal commit ORB_Breakout's: none is left.
)

# OnInit refusals that depend on input values plus the strategy-tester context only. A SET can be valid on a live
# chart and still refused in every tester pass, so validate-set (live and tester SETs alike) does not apply these;
# batch prepare (studio_batch.prepare_batch) and the seed lane (studio_seed._freeze) do, before anything is staged.
TESTER_INIT_RULES = (
    _rule('TESTER_CONTROL_TOWER_BIAS', [4495], 'Live Control Tower bias is unavailable in tester',
          ['Mode_Bias', 'Bias_Protocol'],
          {'Mode_Bias': ['Bias_Disabled'], 'Bias_Protocol': ['BiasProtocol_ControlTowerV2']},
          '(MQL_TESTER || MQL_OPTIMIZATION || MQL_FORWARD) && Mode_Bias!=Bias_Disabled && Bias_Protocol is '
          'BiasProtocol_ControlTowerV2 or BiasProtocol_ControlTowerV2DemoRaw',
          'Live Control Tower bias is unavailable in tester, optimization, and forward contexts. Select '
          'BiasProtocol_LegacyRecorded or disable AI bias.', _tester_control_tower_bias),
    # B50 (A0, GOAT-EA#273 P3): the New York clock under a fixed or EU DST server model applies the US DST rules of
    # 2007 on, so a test starting before 2007.03.11 is refused. It also needs the test start (FromDate, a tester
    # setting): check_tester_init applies it only when given a FromDate before that day.
    dict(_rule('NY_CLOCK_TEST_BEFORE_2007', [5102], "TimeCurrent()<D'2007.03.11'", ['Clock_Mode', 'Server_Clock_Model'],
               {'Clock_Mode': ['Clock_NewYork'], 'Server_Clock_Model': ['ServerClock_NYClose']},
               'MQL_TESTER && FromDate<2007.03.11 && Clock_Mode==Clock_NewYork && Server_Clock_Model!=ServerClock_NYClose',
               'Initialization Failed: the New York clock with a fixed or EU DST server model needs a test start on or '
               'after 2007.03.11 (the US DST rules it applies).',
               lambda v: v['Clock_Mode'] == v.choice('Clock_Mode', 'Clock_NewYork')
               and v['Server_Clock_Model'] != v.choice('Server_Clock_Model', 'ServerClock_NYClose')),
         from_date_before='2007.03.11'),
    # B54 (spec 4.4): the opening range's anchors apply the US DST rules of 2007 on, as the New York clock does: the New
    # York anchor under a fixed or EU DST server model, and the London anchor under every model (NYClose derives UTC
    # through the 2007 US rule too).
    dict(_rule('ORB_NY_TEST_BEFORE_2007', [5193], 'ORB_Clock==ORB_Clock_NewYork && Server_Clock_Model!=ServerClock_NYClose',
               ['ORB_Mode', 'ORB_Clock', 'Server_Clock_Model'],
               {'ORB_Mode': ['ORB_Disabled'], 'ORB_Clock': ['ORB_Clock_NewYork'], 'Server_Clock_Model': ['ServerClock_NYClose']},
               'MQL_TESTER && FromDate<2007.03.11 && ORB_Mode!=ORB_Disabled && ORB_Clock==ORB_Clock_NewYork && '
               'Server_Clock_Model!=ServerClock_NYClose (spec 4.4)',
               'Initialization Failed: ORB_Clock_NewYork with a fixed or EU DST server model needs a test start on or after '
               '2007.03.11 (the US DST rules it applies).',
               lambda v: _orb(v) and v['ORB_Clock'] == v.choice('ORB_Clock', 'ORB_Clock_NewYork')
               and v['Server_Clock_Model'] != v.choice('Server_Clock_Model', 'ServerClock_NYClose')),
         from_date_before='2007.03.11'),
    dict(_rule('ORB_LONDON_TEST_BEFORE_2007', [5194], 'ORB_Clock==ORB_Clock_London && MQLInfoInteger(MQL_TESTER)',
               ['ORB_Mode', 'ORB_Clock'], {'ORB_Mode': ['ORB_Disabled'], 'ORB_Clock': ['ORB_Clock_London']},
               'MQL_TESTER && FromDate<2007.03.11 && ORB_Mode!=ORB_Disabled && ORB_Clock==ORB_Clock_London (spec 4.4)',
               'Initialization Failed: ORB_Clock_London needs a test start on or after 2007.03.11 under every server model '
               '(its UTC comes through the 2007 US DST rules).',
               lambda v: _orb(v) and v['ORB_Clock'] == v.choice('ORB_Clock', 'ORB_Clock_London')),
         from_date_before='2007.03.11'),
)

# Every other OnInit refusal, with why validate-set cannot decide it from the SET's values alone.
_STUDIO_SINPUTS = ('Studio_ReadOnlyMonitor/Studio_MonitorRunPath are sinputs declared in the .mq5, not in the '
                   'input header, so they are not in the controller schema; validate_strategy refuses a SET that '
                   'names them (unknown input) and the EA default (false) never fires this rule')
NOT_PORTED = (
    dict(lines=(4470,), anchor='StringFind(Studio_MonitorRunPath,"GOAT\\\\")!=0', condition='read-only monitor run path outside GOAT\\', reason=_STUDIO_SINPUTS),
    dict(lines=(4472,), anchor='Read-only Studio requires chart operation mode Optimization Studio',
         condition='Studio_ReadOnlyMonitor && (Mode_Operation!=Operation_Batch || MQL_TESTER)', reason=_STUDIO_SINPUTS + '; also run context (tester)'),
    dict(lines=(4483,), anchor='Name Mismatch: The Bot/EA cannot be renamed',
         condition='EA file renamed (EA_Name != Key+" V"+version): Alert then ExpertRemove()',
         reason='build identity (the .ex5 file name), not an input value'),
    dict(lines=(4500,), anchor='Legacy recorded bias is historical/test-only',
         condition='Bias_Protocol==BiasProtocol_LegacyRecorded && live chart', reason='run context: valid in the tester, refused live'),
    dict(lines=(4508,), anchor='Demo raw AI bias is restricted to demo accounts',
         condition='Mode_Bias!=Bias_Disabled && DemoRaw protocol && live && account is not demo', reason='account trade mode'),
    dict(lines=(4517,), anchor='GOATDeviceActivationBegin(AccountInfoInteger(ACCOUNT_LOGIN),GOAT_BUILD_ID)',
         condition='live, no credential, device activation cannot begin', reason='account login and credential state'),
    dict(lines=(4527,), anchor='GOAT AI wire v2 checksum self-test failed', condition='AI wire v2 self-test fails', reason='build/runtime self-test'),
    dict(lines=(4564,), anchor='dt_Back_OOS<TimeCurrent()', condition='EXPORT && dt_BOOS_end before the test start',
         reason='tester start date (TimeCurrent) is in the tester configuration, not the SET'),
    dict(lines=(4565,), anchor='dt_Fwrd_OOS<TimeCurrent()', condition='EXPORT && dt_FOOS_start before the test start',
         reason='tester start date (TimeCurrent) is in the tester configuration, not the SET'),
    dict(lines=(4577,), anchor='TimeCurrent()>Expiry', condition='build expired (B49b F1: on a live trading chart manage-only instead; see 5233)',
         reason='current time vs build expiry'),
    dict(lines=(4739,), anchor='Export is only allowed in back testing mode', condition='EXPORT on a live chart',
         reason='run context (live chart)'),
    dict(lines=(4753, 4757, 4758, 4760), anchor='Operation_Report',
         condition='live, licensed, Mode_Operation==Operation_Report: report dialog then always INIT_FAILED',
         reason='run context (live chart + license); the report tool ends init by design'),
    dict(lines=(4767,), anchor='Allow DLL imports for GOAT', condition='Studio/Dashboard without DLL imports', reason='terminal setting'),
    dict(lines=(4824,), anchor='Tester GUI creation Failed', condition='Studio GUI creation fails', reason='chart/GUI runtime'),
    dict(lines=(4845,), anchor='Dashboard resume refused: saved state and first chart are required', condition='dashboard resume without saved state', reason='chart and saved dashboard state'),
    dict(lines=(4862,), anchor='Wrong Chart Position', condition='dashboard not on the first chart, user declines', reason='chart layout and user choice'),
    dict(lines=(4885, 4886), anchor='Dashboard Launch Cancelled',
         condition='user cancels dashboard resume prompt (4837: unreachable ExpertRemove after the return)', reason='user choice'),
    dict(lines=(4896,), anchor='No valid .set files found', condition='dashboard finds no SETs/config', reason='files on disk'),
    dict(lines=(4904,), anchor='Dashboard GUI creation Failed', condition='dashboard GUI creation fails', reason='chart/GUI runtime'),
    dict(lines=(4954,), anchor='GOATDeviceActivationBegin(AccountInfoInteger(ACCOUNT_LOGIN),GOAT_BUILD_ID,true)',
         condition='credential rejected and replacement cannot begin', reason='license service response'),
    dict(lines=(4960,), anchor='GOAT license service is temporarily unavailable', condition='license service unavailable', reason='license service response'),
    dict(lines=(4965,), anchor='Sleep(20000)', condition='license invalid', reason='license service response'),
    # B49b (F6): the EA now refuses what validate_strategy already refused, so it is decided before these rules run.
    # B52 (Codex GOAT-EA#296 4502334956): the grid engine's only, as check_risk_sizing's single_only() exempts a SET that reaches
    # only Engine_Single (GoatSingleOpen sizes RiskperSeq from the single's own stop).
    dict(lines=(4975,), anchor='Engine_Mode!=Engine_Single && Mode_Lots == RiskperSeq && Max_Seq_Trades<=1',
         condition='Engine_Mode!=Engine_Single && Mode_Lots==RiskperSeq && Max_Seq_Trades<=1',
         reason='decided first by studio_strategy_settings.check_risk_sizing (RISK_PER_SEQUENCE_NEEDS_TWO_TRADES), over every '
                'reachable value, before check_ea_init runs; a SET that reaches only Engine_Single passes both'),
    dict(lines=(5084,), anchor='iATR failed', condition='iATR handle invalid', reason='symbol/indicator runtime'),
    dict(lines=(5092,), anchor='iMA-on-ATR failed', condition='iMA-on-ATR handle invalid', reason='symbol/indicator runtime'),
    # B50 (A0): the single-trade engine's account and indicator refusals.
    dict(lines=(5118,), anchor='ACCOUNT_MARGIN_MODE_RETAIL_HEDGING', condition='Engine_Single on a netting account',
         reason='account margin mode'),
    dict(lines=(5122,), anchor='iATR failed (single-trade engine)', condition='Engine_Single: iATR handle invalid',
         reason='symbol/indicator runtime'),
    dict(lines=(5130,), anchor='iMA-on-ATR failed (single-trade engine)', condition='Engine_Single: iMA-on-ATR handle invalid',
         reason='symbol/indicator runtime'),
    # B51 (beta-1a): the benchmark never trades a live chart; validate-set serves live and tester SETs alike.
    dict(lines=(5143,), anchor='Random_Direction is a strategy-tester benchmark', condition='Random_Direction on a live chart',
         reason='run context (live chart)'),
    # B52 (the final build's review, P1): the New York clock's day end, Friday close and no-tick exits are not yet
    # integrated with B49b's live protections, so this build refuses it on a live chart; the tester runs it as before.
    dict(lines=(5169,), anchor='the New York clock is tester-only in this build', condition='Clock_Mode==Clock_NewYork on a live chart',
         reason='run context (live chart)'),
    # B51 (section 8.4): Engine_Single refuses a live account positively read as not demo; a SET cannot show the account.
    dict(lines=(5160,), anchor='b51_account==GOAT_ACCOUNT_NOT_DEMO', condition='Engine_Single outside the tester on an account read as not demo',
         reason='run context (account mode, connection)'),
    # B54 (spec 4.6): the rules that read the chart's timeframe, and ORB on a live chart (ruling 7).
    dict(lines=(5183,), anchor='BRK_TF_==TF_Cur && PeriodSeconds(PERIOD_CURRENT)>=PeriodSeconds(PERIOD_D1)',
         condition='BRK_Mode==BRK_PriorDay && BRK_TF_==TF_Cur on a chart of D1 or longer',
         reason='the chart timeframe (the tester Period or the live chart), not a SET value; BRK_PRIOR_DAY_ON_D1 refuses TF_D1 itself'),
    dict(lines=(5184,), anchor='Signal_Sample_Period==M_Current && PeriodSeconds(TF2TF(BRK_TF_))<PeriodSeconds(PERIOD_CURRENT)',
         condition='BRK_Mode!=BRK_Disabled && Signal_Sample_Period==M_Current && BRK_TF_ shorter than the chart timeframe (spec 3.3)',
         reason='the chart timeframe (the tester Period or the live chart), not a SET value'),
    dict(lines=(5192,), anchor='Signal_Sample_Period==M_Current && PeriodSeconds(TF2TF(ORB_TF_))<PeriodSeconds(PERIOD_CURRENT)',
         condition='ORB_Mode!=ORB_Disabled && Signal_Sample_Period==M_Current && ORB_TF_ shorter than the chart timeframe (spec 4.3)',
         reason='the chart timeframe (the tester Period or the live chart), not a SET value'),
    dict(lines=(5195,), anchor='ORB_Mode is tester-only in B54', condition='ORB_Mode!=ORB_Disabled on a live chart (ruling 7)',
         reason='run context (live chart)'),
    # B49b (F7 SIG-01): every enabled signal indicator's handle, as ATR's.
    dict(lines=(5215,), anchor='iRSI failed', condition='RSI enabled, iRSI handle invalid', reason='symbol/indicator runtime'),
    dict(lines=(5216,), anchor='iMA (EMA ', condition='EMA enabled, an iMA ladder handle invalid', reason='symbol/indicator runtime'),
    dict(lines=(5217,), anchor='iADX failed', condition='ADX enabled, iADX handle invalid', reason='symbol/indicator runtime'),
    dict(lines=(5218,), anchor='iBands failed', condition='BB enabled, iBands handle invalid', reason='symbol/indicator runtime'),
    dict(lines=(5219,), anchor='iCustom MACD failed', condition='MACD enabled, the compiled MACD indicator cannot load',
         reason='symbol/indicator runtime (the indicator file)'),
    dict(lines=(5220,), anchor='iRSI (RSI2) failed', condition='RSI2 enabled, iRSI handle invalid', reason='symbol/indicator runtime'),
    # B49b (F1 full): live trading charts only (GoatManageOnlyLive); in the tester manage-only is never set.
    dict(lines=(5283,), anchor='manage_only_init==INIT_FAILED',
         condition='live, a refused licence or an expired build (or a rejected credential whose replacement cannot begin) with no open basket to manage',
         reason='license service response and build expiry on a live chart'),
    dict(lines=(5289,), anchor='Exporting CSV/SET is not allowed in Optimization mode', condition='EXPORT in optimization/forward',
         reason='run context (optimization)'),
    dict(lines=(5290,), anchor='GoatSeqClaimAttempt()', condition='sequence export attempt already claimed', reason='files on disk'),
    dict(lines=(5298,), anchor='GoatSeqPathFits', condition='sequence export path too long', reason='symbol name, terminal paths'),
    dict(lines=(5303,), anchor='Failed to open/create the CSV file', condition='export CSV cannot be opened', reason='file system'),
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
        # B50 (A0): a schema that declares none of B50's inputs is a build without them, so without their rules (V1.48,
        # B49a). One that declares some but lost one a rule reads fails closed below, like any other lost input.
        # B51 (beta-1a): the same per appended group (APPENDED_GROUPS), so a B50-alpha schema skips B51's rules.
        absent = {name for group in APPENDED_GROUPS if not any(name in inputs for name in group) for name in group}
        # Section 8.3: any, not all: a rule of an absent group may also read an older input its schema predates (a V1.48
        # schema has neither Single_Partial_ATR nor Ledger_Mode). A lost input of a present group is never in absent.
        if any(name in absent for name in missing):
            continue
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


def check_tester_init(values, schema, *, where='', from_date=None):
    """Batch prepare (P-beta38-prepare-tester-ai-bias) and the seed lane (studio_seed._freeze, GOAT-EA#317: one set of
    SET validators for a seed plan and the Prove batch built from it): refuse a SET whose OnInit refuses it in the
    strategy tester (tester, optimization and forward passes) although it is valid on a live chart. Same reachable-value
    evaluation as check_ea_init; validate-set and live paths do not call this. A rule that also reads the test start
    (from_date_before) applies when `from_date` (the tester FromDate, YYYY.MM.DD) is before its day."""
    if from_date is not None and not re.fullmatch(r'\d{4}\.\d{2}\.\d{2}', str(from_date)):
        raise ValueError(TESTER_INIT_CODE + ': ' + where + 'unreadable tester FromDate ' + repr(from_date))
    table = tuple(rule for rule in TESTER_INIT_RULES
                  if 'from_date_before' not in rule or (from_date is not None and str(from_date) < rule['from_date_before']))
    _enforce(table, values, schema, TESTER_INIT_CODE,
             'the EA refuses this SET in the strategy tester (every optimization pass would end at OnInit with no '
             'result); it stays valid on a live chart.', where)
