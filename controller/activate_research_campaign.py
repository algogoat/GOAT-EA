"""Stage a reviewed Banker native batch; bootstrap/MT5 launches are separate.

This version requires an explicit private ownership inspection receipt and an
idle research terminal. It preserves prior controls without editing the prior
queue. A marker survives failures; reconcile instead of rerunning activation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import configparser
from campaign_ledger import sha
from native_control_transaction import NAMES, begin, contents, digest
from prepare_native_campaign import native_run_relative
from strategy_registry import inspect_set
from studio_settings import validate_export


def verify_export_policy(stage, plan, manifest):
    native=plan['native_batch']
    expected=validate_export(native.get('export_settings',dict(SetsToExport=2,
        MinScore=60.0,TargetDD=100,AdjustLots=False,BackOOSDate=native['back_oos_date'],
        MinARF=0.2,MinSR=2.5,IncludeBackOOS=True)))
    if 'export_settings' in manifest and validate_export(manifest['export_settings']) != expected:
        raise ValueError('Manifest export policy differs from plan')
    text=(Path(stage)/'export_settings.GOAT').read_bytes().decode('utf-16')
    parser=configparser.ConfigParser(interpolation=None,strict=True)
    parser.optionxform=str
    parser.read_string(text)
    if parser.sections()!=['Export'] or parser.defaults() or set(parser['Export'])!=set(expected):
        raise ValueError('Unexpected export settings structure')
    actual={}
    for key,value in expected.items():
        raw=parser['Export'][key]
        if type(value) is bool:
            if raw not in ('0','1'):raise ValueError('Invalid export boolean')
            actual[key]=raw=='1'
        elif key=='SetsToExport':actual[key]=int(raw)
        elif key=='BackOOSDate':actual[key]=raw
        else:actual[key]=float(raw)
    if validate_export(actual)!=expected:
        raise ValueError('Staged export settings differ from reviewed plan')
    batch=(Path(stage)/'portfolio.goatbatch').read_bytes().decode('utf-16')
    opening='[GOAT_EXPORT_SETTINGS]\r\n'; closing='[/GOAT_EXPORT_SETTINGS]'
    if batch.count(opening)!=1 or batch.count(closing)!=1:
        raise ValueError('Batch export section missing or duplicated')
    if batch.split(opening,1)[1].split(closing,1)[0] != text:
        raise ValueError('Batch export policy differs from staged export file')
    return expected

