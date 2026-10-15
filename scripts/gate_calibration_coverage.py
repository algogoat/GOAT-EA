"""Coverage simulation for gate calibration v2: per draw AND per validated gate.

"Validated" is a per-draw guarantee: across evidence draws, few validate a gate
that really misses the target. It is not a per-gate guarantee: among the gates
that DO validate, a larger share is still slightly short. This script measures
both on the test suite's generative model (9 runs x 21 members x 2 near-copy sets,
one real signal, three correlated proxies at 0.8/0.6/0.4, pure-noise features and
a shared survival shock per run), judging every chosen gate on FRESH periods (new
run shocks, new members). Its output is the source of
``studio_gate_calibration.VALIDATED_GATE_MISS``. Read only; prints JSON, and with
``--out`` also writes it to a NEW file.

    python scripts/gate_calibration_coverage.py --draws 4000 [--out <new file>]
"""
import argparse
import json
from pathlib import Path
import sys

CONTROLLER = Path(__file__).resolve().parent.parent / 'controller'
sys.path[:] = [p for p in sys.path if not p.rstrip('\\/').lower().endswith('controller')]
sys.path.insert(0, str(CONTROLLER))

from test_studio_gate_calibration import validated_gate_misses  # noqa: E402

SCENARIOS = [(0.0, 0.9), (0.5, 0.9), (0.8, 0.9), (0.0, 0.8), (0.5, 0.8), (0.8, 0.8)]


def row(sigma, target, draws):
    s = validated_gate_misses(sigma, target, draws)
    shortfalls = sorted(s['shortfalls'])
    return dict(run_shock_sigma=sigma, target=target, draws=draws, validated=s['validated'],
                validated_below_target=s['validated_below'], bound_missed=int(s['bound_missed']),
                evaluated=s['evaluated'], per_draw=round(s['per_draw'], 4),
                per_validated_gate=None if s['per_validated_gate'] is None else round(s['per_validated_gate'], 4),
                shortfall_points=None if not shortfalls else [shortfalls[0], shortfalls[-1]])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--draws', type=int, default=4000)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args(argv)
    if args.out and args.out.exists():
        raise SystemExit('Output already exists: ' + str(args.out))
    result = dict(schema='goat-gate-calibration-v2-coverage', model='simulate_proxies + FreshPeriods',
                  rows=[row(sigma, target, args.draws) for sigma, target in SCENARIOS])
    text = json.dumps(result, sort_keys=True, indent=1)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text + '\n')
    print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
