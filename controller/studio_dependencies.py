"""Partial, source-pinned optimization dependency audit for GOAT.

Only indicator mode gates are audited here. Passing does not prove every axis
changes trading behavior, and MustCheck switches are deliberately excluded: they
also participate in a shared signal-update trigger outside these mode guards.
"""
import hashlib
from fractions import Fraction
from studio_strategy_settings import numeric


GROUPS = {
    'RSI_Mode': ('RSI_Disabled', ('RSI_TF_', 'RSI_Period', 'RSI_Price', 'RSI_Level')),
    'EMA_Mode': ('Trade_Disabled', ('EMA_TF_', 'EMA_Method', 'EMA_Price', 'EMA_Count', 'EMA_Period', 'EMA_Exponent')),
    'ADX_Mode': ('Trade_Disabled', ('ADX_TF_', 'ADX_Period', 'ADX_Level')),
    'BB_Mode': ('BB_Disabled', ('BB_TF_', 'BB_Period', 'BB_Deviation')),
    'MACD_Mode': ('Trade_Disabled', ('MACD_Mode_Trend', 'MACD_TF_', 'MACD_Fast', 'MACD_Slow', 'MACD_Signal', 'MACD_Deviations', 'MACD_Price')),
    'RSI2_Mode': ('RSI_Disabled', ('RSI2_TF_', 'RSI2_Period', 'RSI2_Price', 'RSI2_Level')),
}


def audit_dependencies(validated, schema, policy):
    """Consume structurally validated values; never enumerate numeric search spaces."""
    if validated['source_sha256'] != policy['header_sha256']:
        raise ValueError('Dependency policy/header mismatch')
    findings, covered = [], set()
    for rule in policy['rules']:
        name, controller = rule['input'], rule['controller']
        if name not in validated['axes']:
            continue
        covered.add(name)
        parts = validated['values'][controller].split('||')
        definition = schema['inputs'][controller]
        disabled = Fraction(rule['disabled'])
        if controller in validated['axes']:
            start, step, stop = (numeric(parts[1],definition),
                                 numeric(parts[2],definition,step=True),
                                 numeric(parts[3],definition))
            contains_disabled = start <= disabled <= stop and ((disabled-start)/step).denominator == 1
            entirely_disabled = contains_disabled and validated['axes'][controller] == 1
        else:
            contains_disabled = numeric(parts[0],definition) == disabled
            entirely_disabled = contains_disabled
        if contains_disabled:
            findings.append(dict(input=name, controller=controller,
                severity='error' if entirely_disabled else 'warning',
                code='inactive_axis' if entirely_disabled else 'conditionally_inactive_axis',
                message=f'{name} is inactive '+('throughout the search' if entirely_disabled else 'when the indicator mode is disabled')))
    return dict(coverage=policy['coverage'],main_sha256=policy['main_sha256'],
                checked_axes=sorted(covered),
                unchecked_axes=sorted(set(validated['axes'])-covered),findings=findings,
                execution_ready=False)
