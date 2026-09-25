"""Validated explicit tester draft; no defaults inherited from terminal state."""
from datetime import datetime
import math
from pathlib import PureWindowsPath
import re

FIELDS = {'Expert', 'Symbol', 'Period', 'Model', 'ExecutionMode', 'Optimization',
          'OptimizationCriterion', 'FromDate', 'ToDate', 'ForwardMode', 'ForwardDate',
          'Deposit', 'Currency', 'Leverage', 'UseLocal', 'UseRemote', 'UseCloud', 'Visual'}
PERIODS = {'M1','M2','M3','M4','M5','M6','M10','M12','M15','M20','M30',
           'H1','H2','H3','H4','H6','H8','H12','D1','W1','MN1'}


def validate_tester(value):
    if not isinstance(value, dict) or set(value) != FIELDS:
        raise ValueError('Explicit complete tester settings required; unknown fields rejected')
    result = dict(value)
    for name in ('Expert','Symbol','Period','FromDate','ToDate','ForwardDate','Currency','Leverage'):
        text = value[name]
        if not isinstance(text, str) or any(c in text for c in '\r\n\x00;='):
            raise ValueError('Unsafe configuration text: '+name)
    expert = PureWindowsPath(value['Expert'])
    if not value['Expert'] or expert.drive or expert.root or '..' in expert.parts or expert.suffix.lower() != '.ex5':
        raise ValueError('Expert must be a relative EX5 path')
    if not value['Symbol'].strip() or value['Period'] not in PERIODS:
        raise ValueError('Symbol/timeframe required')
    if not re.fullmatch('[A-Z]{3}', value['Currency']):
        raise ValueError('Three-letter currency required')
    if not re.fullmatch(r'1:[1-9][0-9]*', value['Leverage']):
        raise ValueError('Leverage must use 1:N syntax')
    choices = {'Model':{0,1,2,4}, 'Optimization':{2}, 'OptimizationCriterion':{6},
               'ForwardMode':{0,1,2,3,4}, 'UseLocal':{1}, 'UseRemote':{0},
               'UseCloud':{0}, 'Visual':{0}}
    for name, allowed in choices.items():
        if type(value[name]) is not int or value[name] not in allowed:
            raise ValueError('Unsupported setting: '+name)
    if type(value['ExecutionMode']) is not int or not -1 <= value['ExecutionMode'] <= 600000:
        raise ValueError('Invalid execution delay')
    if type(value['Deposit']) not in (int,float) or not math.isfinite(value['Deposit']) or value['Deposit'] <= 0:
        raise ValueError('Positive finite deposit required')
    def date(text):
        if not re.fullmatch(r'\d{4}\.\d{2}\.\d{2}',text):
            raise ValueError('Date must be YYYY.MM.DD')
        return datetime.strptime(text, '%Y.%m.%d')
    start, end = date(value['FromDate']), date(value['ToDate'])
    if start >= end:
        raise ValueError('End must follow start')
    if value['ForwardMode'] == 4:
        if not start < date(value['ForwardDate']) < end:
            raise ValueError('Custom forward date must be within window')
    elif value['ForwardDate'] != '':
        raise ValueError('ForwardDate must be empty unless mode is custom')
    return result


def serialize_tester(value):
    value = validate_tester(value)
    return '[Tester]\r\n' + ''.join(f'{key}={value[key]}\r\n' for key in sorted(value)
                                    if key != 'ForwardDate' or value[key])


def validate_export(value, tester=None):
    fields = {'SetsToExport','MinScore','TargetDD','AdjustLots','BackOOSDate',
              'MinARF','MinSR','IncludeBackOOS','IncludeSequenceData'}
    if isinstance(value,dict) and 'IncludeSequenceData' not in value:
        value = value | {'IncludeSequenceData':True}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('Complete export settings required')
    if type(value['SetsToExport']) is not int or value['SetsToExport'] < 2:
        raise ValueError('GOAT requires at least two exports')
    # Reject values that native code/UI would silently clamp on reload.
    for key, floor in {'MinScore':60,'TargetDD':100,'MinARF':0.2,'MinSR':2.5}.items():
        number = value[key]
        if type(number) not in (int,float) or not math.isfinite(number) or number < floor:
            raise ValueError(f'{key} must be finite and at least {floor}')
    for key in ('AdjustLots','IncludeBackOOS','IncludeSequenceData'):
        if type(value[key]) is not bool:
            raise ValueError('Boolean required: '+key)
    date = value['BackOOSDate']
    if not isinstance(date,str) or not re.fullmatch(r'\d{4}\.\d{2}\.\d{2}',date):
        raise ValueError('BOOS date must be YYYY.MM.DD')
    start = datetime.strptime(date,'%Y.%m.%d')
    if tester is not None:
        validate_tester(tester)
        if value['IncludeBackOOS'] and start >= datetime.strptime(tester['FromDate'],'%Y.%m.%d'):
            raise ValueError('Included BOOS must start before optimization')
    return dict(value)


def serialize_export(value, tester=None):
    value = validate_export(value,tester)
    return '[Export]\r\n'+''.join(f'{key}={int(v) if type(v) is bool else v}\r\n'
                                   for key,v in sorted(value.items()))
