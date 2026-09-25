"""Verify SET settings against source values and paired optimization pass inputs.

Does not prove runtime binary identity, replay coverage or performance metrics.
"""
import hashlib
from studio_strategy_settings import read_values, validate_strategy, numeric


def verify_export_inputs(source_raw, export_raw, schema, back_passes, forward_passes,
                         *, alias, standard_mode, adjusted_lots=None):
    source, exported = read_values(source_raw), read_values(export_raw)
    checked = validate_strategy(source, schema)
    if set(source) != set(exported):
        raise ValueError('Export input set differs from source')
    expected = dict(source)
    expected.update(EA_Desc=alias, Mode_Operation=str(standard_mode))
    if adjusted_lots is not None:
        expected['Lots_Input'] = str(adjusted_lots)
    axes = sorted(checked['axes'])
    if not axes:
        raise ValueError('Optimization axes required')
    if adjusted_lots is not None and 'Lots_Input' in axes:
        raise ValueError('Adjusted optimized lot input requires separate pass provenance')

    def value(name, text):
        definition = schema['inputs'][name]
        if definition['type'] in ('string', 'datetime'):
            return text
        return numeric(text, definition)

    fixed = []
    for name in source:
        if name in axes:
            value(name, exported[name])  # Reject nonfinite or malformed exports.
            continue
        original = expected[name]
        if schema['inputs'][name]['type'] != 'string':
            original = original.split('||')[0]
        if value(name, original) != value(name, exported[name]):
            raise ValueError('Fixed export input mismatch: '+name)
        fixed.append(name)
    matches = []
    for pass_id, row in forward_passes.items():
        if pass_id not in back_passes:
            continue
        back = back_passes[pass_id]
        if all(name in row and name in back
               and value(name, row[name]) == value(name, back[name]) == value(name, exported[name])
               for name in axes):
            matches.append(pass_id)
    if not matches:
        raise ValueError('Export axes match no paired optimization pass')
    return dict(status='SET_INPUTS_MATCH_PAIRED_PASSES', matching_pass_ids=sorted(matches),
                fixed_input_count=len(fixed), optimized_axes=axes,
                source_sha256=hashlib.sha256(source_raw).hexdigest(),
                export_sha256=hashlib.sha256(export_raw).hexdigest(),
                performance_verified=False, replay_coverage_verified=False,
                runtime_binary_verified=False)
