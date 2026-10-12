"""Deploy timing profiles (goat-deploy-timing-v1): the reviewed waits of deploy-load, deploy-stop and close-terminal.

Remote deploy v0 (goatai docs/remote-deploy-design.md section 3.1, approved for beta.38 by Claude-Mac, goatai#2350
6129098775). A cold 36-chart start on a VPS needs longer waits than the pinned desktop constants; the Exp 03 prototype
overrode module constants by hand. The waits are now a validated parameter instead, never a code edit.

This is the Python port of goatai tools/remote-deploy/deploy_timing_profile.cjs, the reference validator the app runner
shares. The two must give the same verdict for every profile: same fields, bounds, refusal codes and order of checks,
the same 1.5x margin over measured evidence, the same budget, runner timeout and resume rule. The shared goldens are in
controller/contracts/deploy-timing-fixtures/. Contract: controller/contracts/deploy-timing-profile.md.

Pure apart from load_profile, which reads one bounded JSON file. No MT5, network or process access.
"""
import hashlib
import json
import math
from pathlib import Path
import re

from studio_refusal import Refusal

SCHEMA = 'goat-deploy-timing-v1'
# studio_agent_mailbox.portfolio_request refuses a timeout outside 1..90 s.
PORTFOLIO_REQUEST_CAP_SECONDS = 90
# studio_demo_deploy.registration_for: expiresAtUtc = now + 14400 (4 h).
REGISTRATION_SECONDS = 14400
# load() asks apply_policy with timeout=60.
APPLY_POLICY_SECONDS = 60
# A profile wait must cover its measured duration with this margin, or it is refused as too tight.
MIN_MARGIN = 1.5
# Field -> inclusive bounds, in the reference's order (the first broken rule is the one reported).
FIELDS = (
    ('closeWaitSeconds', 10, 600),
    ('launchObserveSeconds', 5, 120),
    ('dashboardWaitSeconds', 60, 1200),
    ('childStartWaitSeconds', 60, 1200),
    ('linkRequestSeconds', 1, PORTFOLIO_REQUEST_CAP_SECONDS),
    ('ackWaitSeconds', 30, 600),
    ('auditWaitSeconds', 30, 600),
)
FIELD_NAMES = tuple(name for name, _, _ in FIELDS)
# What each measured duration must be covered by.
EVIDENCE = (
    ('closeSeconds', 'closeWaitSeconds'),
    ('coldStartSeconds', 'dashboardWaitSeconds'),
    ('coldLinkSeconds', 'childStartWaitSeconds'),
)
ID = re.compile(r'[a-z0-9][a-z0-9-]{0,62}')
MAX_FILE_BYTES = 16384

# The pinned controller (desktop) and the 2026-10-12 Exp 03 VPS measurements (36-chart profile, 35 children).
PROFILES = {
    'desktop': dict(schema=SCHEMA, id='desktop', closeWaitSeconds=30, launchObserveSeconds=30, dashboardWaitSeconds=180,
                    childStartWaitSeconds=240, linkRequestSeconds=20, ackWaitSeconds=90, auditWaitSeconds=90, evidence=None),
    'vps-cold-36': dict(schema=SCHEMA, id='vps-cold-36', closeWaitSeconds=180, launchObserveSeconds=30, dashboardWaitSeconds=480,
                        childStartWaitSeconds=480, linkRequestSeconds=85, ackWaitSeconds=90, auditWaitSeconds=90,
                        evidence=dict(measuredUtc='2026-10-12', charts=36, closeSeconds=79, coldStartSeconds=190, coldLinkSeconds=88)),
}
DEFAULT_ID = 'desktop'


class TimingRefusal(Refusal):
    """A refused profile. Still a ValueError (the CLI's REFUSED), with the reference's code as refusal_code."""

    def __init__(self, code, message, **fields):
        super().__init__(code + ': ' + message, code, **fields)


def _is_object(value):
    return isinstance(value, dict)


def _is_number(value):
    """JavaScript typeof value === 'number' for a JSON value (a bool is not a number)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_integer(value):
    """JavaScript Number.isInteger: 90 and 90.0 are integers, 90.5, NaN, Infinity and true are not."""
    return _is_number(value) and math.isfinite(value) and float(value).is_integer()


def budget_seconds(profile):
    """The whole deploy-load from close to audit, in seconds, when every wait runs to its end."""
    return (profile['closeWaitSeconds'] + profile['launchObserveSeconds'] + profile['dashboardWaitSeconds']
            + profile['childStartWaitSeconds'] + APPLY_POLICY_SECONDS + profile['ackWaitSeconds'] + profile['auditWaitSeconds'])


def validate_profile(profile):
    """Returns the profile unchanged, or raises a TimingRefusal naming the first broken rule (the reference's order)."""
    if not _is_object(profile):
        raise TimingRefusal('TIMING_INVALID', 'a timing profile is an object')
    allowed = {'schema', 'id', 'evidence', *FIELD_NAMES}
    extra = next((key for key in profile if key not in allowed), None)
    if extra is not None:
        raise TimingRefusal('TIMING_INVALID', 'unknown field ' + str(extra))
    if profile.get('schema') != SCHEMA:
        raise TimingRefusal('TIMING_SCHEMA', 'schema must be ' + SCHEMA)
    if not isinstance(profile.get('id'), str) or not ID.fullmatch(profile['id']):
        raise TimingRefusal('TIMING_INVALID', 'id must be 1-63 of a-z 0-9 -')
    for field, low, high in FIELDS:
        value = profile.get(field)
        if not _is_integer(value):
            raise TimingRefusal('TIMING_INVALID', field + ' must be an integer number of seconds')
        if value < low or value > high:
            code = 'TIMING_LINK_REQUEST_OVER_CAP' if field == 'linkRequestSeconds' and value > high else 'TIMING_OUT_OF_RANGE'
            raise TimingRefusal(code, f'{field} {_text(value)} is outside {low}..{high}')
    if profile['linkRequestSeconds'] >= profile['childStartWaitSeconds']:
        raise TimingRefusal('TIMING_LINK_REQUEST_TOO_LONG', 'one link request must end well inside the child start window')
    # The reference reads `profile.evidence !== null`: a missing evidence key is refused like any non-object.
    evidence = profile.get('evidence', _MISSING)
    if evidence is not None:
        if not _is_object(evidence):
            raise TimingRefusal('TIMING_INVALID', 'evidence is null or an object')
        for measure, field in EVIDENCE:
            if measure not in evidence:
                continue
            seen = evidence[measure]
            if not _is_number(seen) or not math.isfinite(seen) or seen <= 0:
                raise TimingRefusal('TIMING_INVALID', 'evidence.' + measure + ' must be a positive number')
            if profile[field] < seen * MIN_MARGIN:
                raise TimingRefusal('TIMING_BELOW_EVIDENCE', f'{field} {_text(profile[field])} s does not cover the measured '
                                                             f'{measure} {_text(seen)} s x {MIN_MARGIN}')
    if budget_seconds(profile) >= REGISTRATION_SECONDS:
        raise TimingRefusal('TIMING_OVER_REGISTRATION', 'the deploy budget must end before the dashboard registration expires')
    return profile


_MISSING = object()


def _text(value):
    return str(int(value)) if _is_integer(value) else str(value)


def runner_timeout_ms(profile, slack_seconds=180):
    """The app-side bound on `studio deploy-load` (the reference's runnerTimeoutMs): the budget plus slack."""
    validate_profile(profile)
    if not isinstance(slack_seconds, int) or isinstance(slack_seconds, bool) or slack_seconds < 0:
        raise TimingRefusal('TIMING_INVALID', 'slack must be a non-negative integer')
    return int(budget_seconds(profile) + slack_seconds) * 1000


def resume_allowed(profile, registration_age_seconds):
    """Whether a deploy resumed at `registered` or `dashboard_ready` may keep its retained registration: what is left
    of the deploy (child start, policy, ack, audit) must end before the registration expires (trap T6)."""
    validate_profile(profile)
    return resume_rule(profile, registration_age_seconds)


def resume_rule(profile, registration_age_seconds):
    """resume_allowed's rule on a profile the caller already holds (deploy-load's validated profile, or with no
    --timing-profile today's constants). Same verdicts and codes."""
    age = registration_age_seconds
    if not _is_number(age) or not math.isfinite(age) or age < 0:
        return dict(ok=False, code='RESUME_AGE_UNKNOWN', reason='the registration age could not be read; refusing the resume')
    left = REGISTRATION_SECONDS - age
    needed = profile['childStartWaitSeconds'] + APPLY_POLICY_SECONDS + profile['ackWaitSeconds'] + profile['auditWaitSeconds']
    if left > needed:
        return dict(ok=True, leftSeconds=left, neededSeconds=needed)
    return dict(ok=False, code='RESUME_REGISTRATION_TOO_OLD', leftSeconds=left, neededSeconds=needed,
                reason='the retained registration would expire before the deploy can finish; unwind and load fresh')


# ----------------------------------------------------------------- effective values and their record

def effective(profile):
    """The seven waits the controller uses, as integers, in the reference's field order."""
    return {field: int(profile[field]) for field in FIELD_NAMES}


def effective_sha256(profile):
    """sha256 of the canonical JSON of {schema, seven waits}: sorted keys, no whitespace, integers. It identifies what
    the controller waited, not the profile's name or evidence (two profiles with the same waits share it)."""
    canonical = json.dumps(dict(schema=SCHEMA, **effective(profile)), sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def record(profile, *, source):
    """What the journal and the CLI receipt carry: which profile, from where, and the sha of its effective values."""
    return dict(id=profile['id'], sha256=effective_sha256(profile), source=source, values=effective(profile))


def default_record():
    """The record of a call made without --timing-profile: the desktop waits, which are the controller's own defaults."""
    return record(PROFILES[DEFAULT_ID], source='default')


def builtin(profile_id):
    return json.loads(json.dumps(PROFILES[profile_id]))


def load_profile(value):
    """--timing-profile <file|id>. A built-in id (desktop, vps-cold-36) wins over a file of the same name. A file is
    one JSON object of at most 16 KB, validated like the reference; a file may not reuse a built-in id with other
    values (the journal would then name the wrong waits). Returns (profile, record)."""
    if not isinstance(value, str) or not value:
        raise TimingRefusal('TIMING_INVALID', 'a timing profile id or file is required')
    if value in PROFILES:
        profile = validate_profile(builtin(value))
        return profile, record(profile, source='builtin')
    path = Path(value)
    try:
        if path.is_symlink() or not path.is_file():
            raise TimingRefusal('TIMING_PROFILE_NOT_FOUND', 'no built-in timing profile or file named ' + value[:200]
                                + ' (built-in: ' + ', '.join(PROFILES) + ')')
        with path.open('rb') as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise TimingRefusal('TIMING_PROFILE_NOT_FOUND', 'the timing profile file could not be read: ' + str(exc)[:200]) from exc
    if not 0 < len(raw) <= MAX_FILE_BYTES:
        raise TimingRefusal('TIMING_INVALID', 'a timing profile file is 1 to ' + str(MAX_FILE_BYTES) + ' bytes')
    try:
        profile = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique, parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        if isinstance(exc, TimingRefusal):
            raise
        raise TimingRefusal('TIMING_INVALID', 'the timing profile file is not one JSON object') from exc
    validate_profile(profile)
    if profile['id'] in PROFILES and effective(profile) != effective(PROFILES[profile['id']]):
        raise TimingRefusal('TIMING_BUILTIN_ID_MISMATCH', 'the file reuses the built-in id ' + profile['id']
                            + ' with different waits; give it its own id')
    return profile, record(profile, source='file:' + hashlib.sha256(raw).hexdigest())


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise TimingRefusal('TIMING_INVALID', 'duplicate field ' + str(key))
        result[key] = value
    return result


def _no_constant(name):
    raise TimingRefusal('TIMING_INVALID', name + ' is not a JSON number')
