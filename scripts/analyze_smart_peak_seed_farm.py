#!/usr/bin/env python3
import csv
import re
import statistics
from collections import defaultdict
from pathlib import Path


PROGRESS = Path(r"C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\Common\Files\GOAT\SeedFarmingReports\SmartPeakMLPS\smart_peak_mlps_seed_farm_progress.csv")
OUTDIR = Path(r"C:\Users\web\AppData\Roaming\MetaQuotes\Terminal\Common\Files\GOAT\SeedFarmingReports\SmartPeakMLPS")


METRIC_RE = re.compile(
    r"_N(?P<n>\d+)_AvgFit=(?P<avgfit>-?\d+(?:\.\d+)?)_Health=(?P<health>-?\d+(?:\.\d+)?)"
    r"_Zero=(?P<zero>\d+)_AvgTrades=(?P<avgtrades>-?\d+(?:\.\d+)?)_Best=(?P<best>-?\d+(?:\.\d+)?)"
)
STRATEGY_RE = re.compile(r"^(?P<family>SPN_[A-Za-z]+(?:[A-Za-z]+)?)_R(?P<risk>\d+)$")


def parse_metrics(path_text: str) -> dict:
    m = METRIC_RE.search(path_text or "")
    if not m:
        return {}
    out = {}
    for key, value in m.groupdict().items():
        out[key] = int(value) if key in {"n", "zero"} else float(value)
    return out


def median(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else 0.0


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else 0.0


def main() -> None:
    if not PROGRESS.exists():
        raise SystemExit(f"Missing progress CSV: {PROGRESS}")

    latest_by_key = {}
    with PROGRESS.open("r", newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row.get("Status") not in {"Completed", "SkippedExisting"}:
                continue
            strategy = row.get("Strategy", "")
            symbol = row.get("Symbol", "")
            m = STRATEGY_RE.match(strategy)
            if not m:
                continue
            key = (m.group("family"), int(m.group("risk")), symbol)
            metrics = parse_metrics(row.get("XmlPath", ""))
            if not metrics:
                continue
            latest_by_key[key] = {
                **row,
                **metrics,
                "Family": m.group("family"),
                "RiskInt": int(m.group("risk")),
            }

    grouped = defaultdict(list)
    for row in latest_by_key.values():
        grouped[(row["Family"], row["RiskInt"])].append(row)

    summary_rows = []
    for (family, risk), rows in sorted(grouped.items()):
        count = len(rows)
        avgfit = mean([r["avgfit"] for r in rows])
        medfit = median([r["avgfit"] for r in rows])
        health = mean([r["health"] for r in rows])
        zero = sum([r["zero"] for r in rows])
        avgtrades = mean([r["avgtrades"] for r in rows])
        best = mean([r["best"] for r in rows])
        # Robust MLPS score: favor average/median seed fitness and healthy frames,
        # lightly reward good best cases, and penalize zero-trade frames.
        score = ((avgfit * 0.55) + (medfit * 0.35) + (best * 0.10)) * (health / 100.0) - (zero / max(count, 1)) * 0.0005
        summary_rows.append({
            "Family": family,
            "Risk": risk,
            "Symbols": count,
            "AvgFit": avgfit,
            "MedianFit": medfit,
            "Health": health,
            "ZeroFrames": zero,
            "AvgTrades": avgtrades,
            "BestAvg": best,
            "RobustScore": score,
        })

    by_family = defaultdict(list)
    for row in summary_rows:
        by_family[row["Family"]].append(row)

    winners = []
    for family, rows in sorted(by_family.items()):
        rows = sorted(rows, key=lambda r: (r["RobustScore"], r["Symbols"], r["Health"], r["AvgFit"]), reverse=True)
        winners.append(rows[0])

    OUTDIR.mkdir(parents=True, exist_ok=True)
    summary_csv = OUTDIR / "smart_peak_mlps_seed_farm_summary.csv"
    winners_csv = OUTDIR / "smart_peak_mlps_seed_farm_winners.csv"
    report_md = OUTDIR / "smart_peak_mlps_seed_farm_report.md"

    fieldnames = ["Family", "Risk", "Symbols", "AvgFit", "MedianFit", "Health", "ZeroFrames", "AvgTrades", "BestAvg", "RobustScore"]
    with summary_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    with winners_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(winners)

    lines = [
        "# Smart Peak MLPS Seed Farming Report",
        "",
        f"Progress source: `{PROGRESS}`",
        f"Completed symbol/risk rows parsed: {len(latest_by_key)}",
        "",
        "## Winners",
        "",
        "| Family | Risk | Symbols | AvgFit | MedianFit | Health | ZeroFrames | AvgTrades | BestAvg | RobustScore |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in winners:
        lines.append(
            f"| {row['Family']} | {row['Risk']} | {row['Symbols']} | {row['AvgFit']:.4f} | {row['MedianFit']:.4f} | "
            f"{row['Health']:.2f} | {row['ZeroFrames']} | {row['AvgTrades']:.1f} | {row['BestAvg']:.4f} | {row['RobustScore']:.5f} |"
        )

    lines += [
        "",
        "## Full Risk Summary",
        "",
        "| Family | Risk | Symbols | AvgFit | MedianFit | Health | ZeroFrames | AvgTrades | BestAvg | RobustScore |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in sorted(summary_rows, key=lambda r: (r["Family"], r["Risk"])):
        lines.append(
            f"| {row['Family']} | {row['Risk']} | {row['Symbols']} | {row['AvgFit']:.4f} | {row['MedianFit']:.4f} | "
            f"{row['Health']:.2f} | {row['ZeroFrames']} | {row['AvgTrades']:.1f} | {row['BestAvg']:.4f} | {row['RobustScore']:.5f} |"
        )

    report_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"summary_csv={summary_csv}")
    print(f"winners_csv={winners_csv}")
    print(f"report_md={report_md}")


if __name__ == "__main__":
    main()
