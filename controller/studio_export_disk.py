"""Disk a batch's exports need, from measured export units (goatai#1885, Claude-Mac 6023896492).

Read only. ``prepare-batch`` returns this as ``disk_estimate`` so the agent tells people what a batch
will write to their MT5 Common Files disk, testers' disks included, beside the timing pilot.

Measured on Claude-PC, 2026-10-06, over every kept unit in Common Files: a unit with its sequence
capture is ``<stem>.goatseq`` (406 units: median 95.9 MiB, p90 163.4 MiB, max 226 MiB) plus the equity
CSV (706 units: median 0.6 MiB) and the SET (about 7 KiB). Without sequence data a unit is the CSV and
SET only. Below-score research exports (EA build B42) apply to members where nothing reached the export
score: 4.1% of member attempts on that PC (101 of 2,481) up to 11% of g6 members (101 of 916).
"""
import shutil
from pathlib import Path

MIB = 1024 * 1024
GIB = 1024 * MIB
UNIT_MEDIAN_BYTES = 97 * MIB      # .goatseq + equity CSV + SET, median
UNIT_P90_BYTES = 163 * MIB        # p90
UNIT_NO_SEQUENCE_BYTES = MIB      # equity CSV + SET, rounded up
BELOW_SCORE_RATE = (0.041, 0.11)  # share of members that export a below_score unit (slot 1)
MIN_FREE_BYTES = 5 * GIB          # the guides' free-space floor on every output disk
BASIS = ('Measured 2026-10-06 on Claude-PC: 406 kept units (sequence capture median 95.9 MiB, p90 163.4 MiB), '
         '706 equity CSVs (median 0.6 MiB); below_score in 4.1%-11% of members (B42+)')


def _gb(value):
    return round(value / GIB, 1)


def export_disk_estimate(member_count, export_settings, free_bytes=None):
    """Bytes the batch's kept exports may write: normal exports, plus research-only below_score exports.

    ``export_settings`` is a member's ``export`` block (SetsToExport, IncludeSequenceData). An estimate from
    measured units, never a promise: the EA keeps at most SetsToExport units per member (often fewer).
    """
    members = max(0, int(member_count))
    settings = export_settings or {}
    try:
        sets = max(2, int(settings.get('SetsToExport') or 2))   # the EA floors SetsToExport at 2
    except (TypeError, ValueError):
        sets = 2
    sequence = settings.get('IncludeSequenceData', True) not in (False, 0, '0', 'false', 'False')
    median, p90 = (UNIT_MEDIAN_BYTES, UNIT_P90_BYTES) if sequence else (UNIT_NO_SEQUENCE_BYTES, UNIT_NO_SEQUENCE_BYTES)
    normal = dict(units_max=members * sets, typical_bytes=members * sets * median, high_bytes=members * sets * p90)
    low_units, high_units = members * BELOW_SCORE_RATE[0], members * BELOW_SCORE_RATE[1]
    below = dict(units_low=round(low_units, 1), units_high=round(high_units, 1), low_bytes=int(low_units * median),
                 high_bytes=int(high_units * median), high_p90_bytes=int(high_units * p90))
    total_high = normal['high_bytes'] + below['high_p90_bytes']
    result = dict(schema='goat-export-disk-estimate-v1', members=members, sets_to_export=sets, sequence_data=sequence,
                  unit_median_bytes=median, unit_p90_bytes=p90, normal_exports=normal, below_score=below,
                  total_high_bytes=total_high, min_free_bytes=MIN_FREE_BYTES, basis=BASIS)
    words = ('Disk: up to %d kept export%s (%d members x %d) at about %s each, so about %.1f GB typical and up to %.1f GB'
             % (normal['units_max'], '' if normal['units_max'] == 1 else 's', members, sets,
                ('%d MB' % round(median / MIB)) if sequence else 'under 1 MB', _gb(normal['typical_bytes']), _gb(normal['high_bytes'])))
    words += ('; plus about %.1f-%.1f GB for research-only below_score exports (about %.1f-%.1f GB per 100 members, EA build B42 and later)'
              % (_gb(below['low_bytes']), _gb(below['high_bytes']), _gb(100 * BELOW_SCORE_RATE[0] * median), _gb(100 * BELOW_SCORE_RATE[1] * median)))
    if free_bytes is not None:
        result['free_bytes'] = int(free_bytes)
        result['fits'] = int(free_bytes) - total_high >= MIN_FREE_BYTES
        words += ('. %.1f GB free on the Common Files disk%s' % (_gb(free_bytes), '' if result['fits']
                  else ': not enough to keep 5 GB free at the high estimate. Free space or run fewer members'))
    result['plain'] = words + '.'
    return result


def estimate_for_root(member_count, export_settings, common_files_root=None):
    """The estimate with the Common Files disk's free space, when it can be read."""
    free = None
    if common_files_root:
        try:
            free = shutil.disk_usage(Path(common_files_root)).free
        except OSError:
            free = None
    return export_disk_estimate(member_count, export_settings, free)
