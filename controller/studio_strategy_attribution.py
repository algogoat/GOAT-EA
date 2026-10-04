"""Which publisher strategy a run belongs to (library scoring v1, phase 1; goatai#2221).

Locks and trial counts are kept per ``strategyKey``: the root publisher template id.
Forks follow ``parentTemplateId``; seed promotions and robustness sets inherit their
template's key. New plans declare it per member as ``strategy_ref``::

    {strategy_key, template_id, template_revision, template_sha256, catalog_revision}

Members without one (every legacy member) are attributed read-only, in this order
(spec §5, Claude-Mac answer 5):

1. ``selection-receipt`` / ``fork-receipt`` / ``catalog-template``: the member's SET
   bytes equal a frozen selection, fork or catalog template SET (exact sha256);
2. ``ledger-record``: a v0 result whose artifact sha256 equals the attempt's
   ``result.json`` (the §3.5 join), or whose effective-settings hash equals the
   member's configuration hash;
3. ``fingerprint``: exactly one template revision whose non-axis input values and
   axis names both equal the member's (EA_Desc excluded). Any ambiguity, including
   two revisions of one template, stays unattributed;
4. otherwise ``unattributed``: such a member counts against every key.

The strategy library is the desktop's: ``<desktop data>/strategy-library*``, beside
the evidence root. Nothing here writes, launches or reads MT5.
"""
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

from studio_heldout import HeldOutRefused, INVALID_REF, ID, SHA, canonical, evidence_root

REF_KEYS = ('strategy_key', 'template_id', 'template_revision', 'template_sha256', 'catalog_revision')
EXACT = ('selection-receipt', 'fork-receipt', 'catalog-template')
MAX_JSON = 8 * 1024 * 1024
MAX_SET = 4 * 1024 * 1024
MAX_FILES = 5000


def validate_ref(ref, where='member'):
    """A declared strategy_ref, normalised; None when absent."""
    if ref is None:
        return None
    if not isinstance(ref, dict) or set(ref) != set(REF_KEYS):
        raise HeldOutRefused(INVALID_REF, '%s strategy_ref needs exactly %s.' % (where, ', '.join(REF_KEYS)))
    for key in ('strategy_key', 'template_id', 'template_revision', 'catalog_revision'):
        if not isinstance(ref[key], str) or not ID.fullmatch(ref[key]):
            raise HeldOutRefused(INVALID_REF, '%s strategy_ref.%s must be an id (letters, digits, . _ -).' % (where, key))
    if not isinstance(ref['template_sha256'], str) or not SHA.fullmatch(ref['template_sha256']):
        raise HeldOutRefused(INVALID_REF, '%s strategy_ref.template_sha256 must be a sha256.' % where)
    return {key: ref[key] for key in REF_KEYS}


# ---------------------------------------------------------------------------
# Canonical SET material: variant id and template fingerprint
# ---------------------------------------------------------------------------

def _norm(part):
    try:
        number = Decimal(part)
        if number.is_finite():
            return '0' if number == 0 else format(number.normalize(), 'f')
    except InvalidOperation:
        pass
    return part


def _split(values):
    """(axes {name: [value, start, step, stop]}, fixed {name: value}); EA_Desc excluded."""
    axes, fixed = {}, {}
    for name, raw in (values or {}).items():
        if name == 'EA_Desc' or not isinstance(raw, str):
            continue
        parts = raw.split('||')
        if len(parts) == 5 and parts[4] == 'Y':
            axes[name] = [_norm(p) for p in parts[:4]]
        else:
            fixed[name] = _norm(parts[0])
    return axes, fixed


def variant_id(values):
    """sha256 of the canonical trading values (spec §1): every input but EA_Desc (tester
    fields are not SET inputs), with each optimization axis's [value, start, step, stop]."""
    axes, fixed = _split(values)
    material = {name: [value] for name, value in fixed.items()} | axes
    return hashlib.sha256(canonical(material).encode('utf-8')).hexdigest()


def fingerprint(values):
    """Exact non-axis input values plus axis names (Claude-Mac answer 5)."""
    axes, fixed = _split(values)
    return hashlib.sha256(canonical(dict(axes=sorted(axes), values=fixed)).encode('utf-8')).hexdigest()


def set_values(raw):
    from studio_strategy_settings import read_values
    return read_values(raw)


# ---------------------------------------------------------------------------
# The desktop strategy library (read-only)
# ---------------------------------------------------------------------------

def _json(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_JSON:
        return None
    try:
        return json.loads(path.read_bytes().decode('utf-8-sig'))
    except (OSError, ValueError):
        return None


def _bytes(path, limit=MAX_SET):
    try:
        path = Path(path)
        if path.is_file() and path.stat().st_size <= limit:
            return path.read_bytes()
    except OSError:
        pass
    return None


class Library:
    """Selection, fork and catalog receipts and v0 results under every strategy-library root."""

    def __init__(self, roots=()):
        self.roots = [Path(r) for r in roots]
        self.forks, self.by_sha, self.by_fingerprint = {}, {}, {}
        self.by_artifact, self.by_settings, self.by_attempt, self.catalogs = {}, {}, {}, {}
        self.loaded = False

    @classmethod
    def for_install(cls, install):
        try:
            root = evidence_root(install)
        except ValueError:
            root = None
        if root is None or not root.parent.is_dir():
            return cls(())
        return cls(sorted(p for p in root.parent.glob('strategy-library*') if p.is_dir()))

    def key(self, template_id):
        fork = self.forks.get(template_id)
        return fork['parentTemplateId'] if fork else template_id

    def _add(self, index, digest, entry):
        bucket = index.setdefault(digest, [])
        if entry not in bucket:
            bucket.append(entry)

    def load(self):
        if self.loaded:
            return self
        self.loaded = True
        for root in self.roots:
            forks = sorted((root / 'forks').glob('*.json'))[:MAX_FILES] if (root / 'forks').is_dir() else []
            for path in forks:
                fork = _json(path)
                if isinstance(fork, dict) and isinstance(fork.get('id'), str) and isinstance(fork.get('parentTemplateId'), str):
                    self.forks[fork['id']] = fork
            catalogs = sorted((root / 'revisions').glob('*/catalog.json'))[:MAX_FILES] if (root / 'revisions').is_dir() else []
            for path in catalogs:
                catalog = _json(path)
                if not isinstance(catalog, dict) or not isinstance(catalog.get('templates'), list):
                    continue
                revision = catalog.get('revision')
                self.catalogs[revision] = dict(revision=revision, published_at=catalog.get('publishedAt'))
                for template in catalog['templates']:
                    if not isinstance(template, dict) or not isinstance(template.get('id'), str):
                        continue
                    entry = dict(template_id=template['id'], template_revision=template.get('revision'),
                                 template_sha256=template.get('sha256'), catalog_revision=revision)
                    if isinstance(template.get('sha256'), str):
                        self._add(self.by_sha, template['sha256'], dict(entry, source='catalog-template'))
                    raw = _bytes(path.parent / template['file']) if isinstance(template.get('file'), str) else None
                    if raw is not None:
                        try:
                            self._add(self.by_fingerprint, fingerprint(set_values(raw)), entry)
                        except (ValueError, UnicodeError):
                            pass
            for path in (sorted((root / 'selections').glob('*/receipt.json'))[:MAX_FILES] if (root / 'selections').is_dir() else []):
                receipt = _json(path)
                if not isinstance(receipt, dict):
                    continue
                for template in receipt.get('templates') or []:
                    if isinstance(template, dict) and isinstance(template.get('sha256'), str) and isinstance(template.get('id'), str):
                        self._add(self.by_sha, template['sha256'], dict(
                            template_id=template['id'], template_revision=template.get('revision'),
                            template_sha256=template['sha256'], catalog_revision=receipt.get('catalogRevision'),
                            source='selection-receipt'))
            for fork in self.forks.values():
                entry = dict(template_id=fork['id'], template_revision=fork.get('parentRevision'),
                             template_sha256=fork.get('sha256'), catalog_revision=None)
                if isinstance(fork.get('sha256'), str):
                    self._add(self.by_sha, fork['sha256'], dict(entry, source='fork-receipt'))
                raw = _bytes(root / 'forks' / (fork['id'] + '.set'))
                if raw is not None:
                    try:
                        self._add(self.by_fingerprint, fingerprint(set_values(raw)), entry)
                    except (ValueError, UnicodeError):
                        pass
            for path in (sorted((root / 'results').glob('*.json'))[:MAX_FILES * 4] if (root / 'results').is_dir() else []):
                result = _json(path)
                if not isinstance(result, dict) or not isinstance(result.get('templateId'), str):
                    continue
                entry = dict(template_id=result['templateId'], template_revision=result.get('templateRevision'),
                             template_sha256=result.get('templateSha256'), catalog_revision=result.get('catalogRevision'))
                if isinstance(result.get('attemptId'), str):
                    self._add(self.by_attempt, result['attemptId'], entry)
                for artifact in result.get('artifacts') or []:
                    if isinstance(artifact, dict) and isinstance(artifact.get('sha256'), str):
                        self._add(self.by_artifact, artifact['sha256'], entry)
                settings = (result.get('conditions') or {}).get('effectiveSettingsSha256')
                if isinstance(settings, str):
                    self._add(self.by_settings, settings, entry)
        return self

    def _one_key(self, entries):
        keys = {self.key(e['template_id']) for e in entries}
        return keys.pop() if len(keys) == 1 else None

    def attribute(self, *, declared=None, set_sha256=None, values=None, configuration_sha256=None, result_sha256s=(),
                  attempt_key=None):
        """Attribution of one member. ``keys`` is every key the member may belong to:
        a declared key plus any exact match that disagrees with it."""
        self.load()
        exact = self.by_sha.get(set_sha256, []) if set_sha256 else []
        exact_key = self._one_key(exact) if exact else None
        if declared is not None:
            keys = {declared['strategy_key'], self.key(declared['template_id'])}
            keys.update(self.key(e['template_id']) for e in exact)
            return dict(declared, attribution='declared', keys=sorted(keys))
        if exact_key:
            entry = self._pick(exact)
            return self._ref(entry, exact_key, entry['source'])
        # A v0 record of exactly this member (attempt key, or its configuration hash) first;
        # the attempt result.json join only when every record on it names one key.
        for records in ((self.by_attempt.get(attempt_key, []) if attempt_key else []),
                        (self.by_settings.get(configuration_sha256, []) if configuration_sha256 else []),
                        [e for sha in result_sha256s if sha for e in self.by_artifact.get(sha, [])]):
            record_key = self._one_key(records) if records else None
            if record_key:
                return self._ref(records[0], record_key, 'ledger-record')
        if values is not None:
            try:
                matches = self.by_fingerprint.get(fingerprint(values), [])
            except (TypeError, ValueError):
                matches = []
            # One template revision may ship in several catalog revisions; that is one match.
            # Two templates, or two revisions of one template, are ambiguous.
            if len({(m['template_id'], m['template_revision']) for m in matches}) == 1:
                return self._ref(self._pick(matches), self.key(matches[0]['template_id']), 'fingerprint')
        return dict(strategy_key=None, template_id=None, template_revision=None, template_sha256=None,
                    catalog_revision=None, attribution='unattributed', keys=[])

    @staticmethod
    def _pick(entries):
        """The most specific of equivalent entries: a selection receipt names the catalog it
        was chosen from; otherwise a catalog revision is kept only when every entry agrees."""
        order = {'selection-receipt': 0, 'fork-receipt': 1}
        best = dict(sorted(entries, key=lambda e: order.get(e.get('source'), 2))[0])
        if best.get('source') != 'selection-receipt' and len({e.get('catalog_revision') for e in entries}) > 1:
            best['catalog_revision'] = None
        return best

    def _ref(self, entry, key, how):
        return dict(strategy_key=key, template_id=entry['template_id'], template_revision=entry.get('template_revision'),
                    template_sha256=entry.get('template_sha256'), catalog_revision=entry.get('catalog_revision'),
                    attribution=how, keys=[key])


def suggestion(attribution):
    """A strategy_ref an agent could declare, from a non-declared exact attribution."""
    if not attribution or attribution.get('attribution') in (None, 'declared', 'unattributed'):
        return None
    ref = {key: attribution.get(key) for key in REF_KEYS}
    return ref if all(isinstance(v, str) for v in ref.values()) else None


STRATEGY_REF_HELP = ('Add strategy_ref {strategy_key, template_id, template_revision, template_sha256, catalog_revision} '
                     'to each member (the publisher template it came from; a fork names its own id with its parent as '
                     'strategy_key).')


def stable(ref):
    """The strategy_ref fields bound into a frozen plan (drops derived helpers)."""
    return None if ref is None else {key: ref[key] for key in REF_KEYS}


def parse_ref_list(value, count, where):
    """Optional per-member strategy refs: None, or a list of ``count`` refs/nulls."""
    if value is None:
        return [None] * count
    if not isinstance(value, list) or len(value) != count:
        raise HeldOutRefused(INVALID_REF, '%s strategy_refs must list one strategy_ref (or null) per entry.' % where)
    return [validate_ref(item, '%s %d' % (where, index + 1)) for index, item in enumerate(value)]
