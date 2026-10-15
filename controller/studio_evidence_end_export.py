"""Hand a batch's resolved evidence end to an EA build that cuts exports there.

``studio_evidence_end`` (PR #118) resolves AUTO (the latest fully closed Friday)
or validates an explicit closed broker day once, at prepare, and the batch plan
records it. When the bound monitor reports capability ``goat-evidence-end-v1``
(EA FU35 and later), prepare also writes that one explicit date as
``EvidenceEnd=YYYY.MM.DD`` into the batch's ``export_settings.GOAT``. The EA then
runs every export to EvidenceEnd + 1 day (MT5 ToDate is exclusive), so every
member's deals, equity rows and sequence frames end on the same day, and
``resume_batch`` successors keep the same date.

AUTO itself is never written for a batch: the EA would resolve it again when each
member exports, and a Friday close during a long batch would split the members'
timelines. Builds without the capability keep the PR #118 behaviour unchanged:
the policy records their own last-Friday end and OOS catch-up re-tests later.
Nothing here starts, stops or writes to MT5.
"""
from studio_evidence_end import CAPABILITY, ea_capability, mt5, parse_date

KEY = 'EvidenceEnd'
NATIVE_END = 'evidence_end_setting'


def native_policy(policy, capability):
    """The batch evidence-end policy for this EA capability observation."""
    if policy is None:
        return None
    if not isinstance(capability, dict) or capability.get('supported') is not True \
            or capability.get('capability') != CAPABILITY:
        return policy | dict(ea_capability=capability)
    value = mt5(parse_date(policy['target']))
    return policy | dict(native_export_end=NATIVE_END, native_end_if_exported_now=policy['target'],
                         ea_capability=capability, ea_setting=dict(key=KEY, value=value),
                         catch_up='This EA build ends every export at the evidence end (EvidenceEnd=' + value
                                  + '), so all members share one timeline; no catch-up is needed for this batch.')


def for_controller(controller, policy):
    """Read the bound monitor's capability; anything unreadable is unsupported, never assumed."""
    if policy is None:
        return None
    try:
        capability = ea_capability(controller.install, controller.local / 'ui-observation.json')
    except (AttributeError, KeyError, TypeError):
        capability = dict(supported=False, capability=CAPABILITY, basis='installation_unbound')
    return native_policy(policy, capability)


def stamp_effective(policy):
    """Add ``evidenceEnd`` (nominal) and ``evidenceEndEffective`` (last day covered) to a batch policy.

    With EvidenceEnd the EA exports to EvidenceEnd + 1 (exclusive), so the effective end is the
    staged day itself. Without it the EA passes its own last Friday as the exclusive ToDate, so the
    exports end the day before; when that is the Thursday before a nominal Friday the policy is
    stamped ``evidenceEndMode: legacy_thursday_cut`` and warns (Claude-Mac, goatai#1885 6008626040).
    """
    if policy is None:
        return None
    from datetime import timedelta
    from studio_evidence_end import FRIDAY, effective_end
    nominal = parse_date(policy['target'])
    if isinstance(policy.get('ea_setting'), dict):
        effective = parse_date(effective_end(mt5(parse_date(policy['ea_setting']['value']) + timedelta(days=1))))
    else:
        effective = parse_date(policy['native_end_if_exported_now'])
    result = policy | dict(evidenceEnd=nominal.isoformat(), evidenceEndEffective=effective.isoformat())
    if 'ea_setting' not in policy and nominal.weekday() == FRIDAY and effective == nominal - timedelta(days=1):
        result['evidenceEndMode'] = 'legacy_thursday_cut'
        result['warnings'] = list(policy.get('warnings') or []) + [
            'This EA build ends exports at its own last Friday, which MT5 excludes: the exports cover through Thursday %s, '
            'one day short of the nominal Friday %s. OOS catch-up brings them to the Friday.'
            % (effective.isoformat(), nominal.isoformat())]
    return result


def setting(native_batch):
    """The EvidenceEnd value staged for this native batch, or None for older builds."""
    evidence = (native_batch or {}).get('evidence_end')
    if not isinstance(evidence, dict) or 'ea_setting' not in evidence:
        return None
    if (evidence.get('native_export_end') != NATIVE_END
            or evidence['ea_setting'] != dict(key=KEY, value=mt5(parse_date(evidence.get('target'))))):
        raise ValueError('EvidenceEnd setting differs from the resolved evidence end')
    return evidence['ea_setting']['value']


def serialize(export_text, native_batch):
    """Append EvidenceEnd to serialized [Export] settings when this batch carries one."""
    value = setting(native_batch)
    return export_text if value is None else export_text + KEY + '=' + value + '\r\n'


def saved_value(export):
    """Pop a saved .goatbatch EvidenceEnd into the plan's evidence_end (validated again at prepare)."""
    value = export.pop(KEY, None)
    if value is None:
        return None
    if value.strip().lower() == 'auto':
        return 'auto'
    return parse_date(value).isoformat()
