import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from value_model import (
    LINES,
    estimate_goals,
    historical_rows,
    parse_date,
    read_json,
    under_probability,
)

MIN_VENUE_MATCHES = 5


def summarize(rows):
    if not rows:
        return {"predictions": 0}

    n = len(rows)
    model_brier = sum(
        (r["probability"] - r["actual"]) ** 2 for r in rows
    ) / n
    baseline_brier = sum(
        (r["baseline_probability"] - r["actual"]) ** 2
        for r in rows
    ) / n

    log_loss = 0.0
    for row in rows:
        p = min(1 - 1e-12, max(1e-12, row["probability"]))
        y = row["actual"]
        log_loss -= y * math.log(p) + (1 - y) * math.log(1 - p)

    bins = []
    for index in range(10):
        selected = [
            r for r in rows
            if min(9, int(r["probability"] * 10)) == index
        ]
        if selected:
            bins.append({
                "range": f"{index * 10}-{(index + 1) * 10}%",
                "count": len(selected),
                "mean_probability": sum(
                    r["probability"] for r in selected
                ) / len(selected),
                "observed_frequency": sum(
                    r["actual"] for r in selected
                ) / len(selected),
            })

    return {
        "predictions": n,
        "matches": len({r["fixture_id"] for r in rows}),
        "model_brier": model_brier,
        "baseline_brier": baseline_brier,
        "brier_skill": (
            1 - model_brier / baseline_brier
            if baseline_brier > 0 else None
        ),
        "model_log_loss": log_loss / n,
        "mean_probability": sum(
            r["probability"] for r in rows
        ) / n,
        "observed_frequency": sum(
            r["actual"] for r in rows
        ) / n,
        "calibration_bins": bins,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--analysis", default="data/league_analysis.json"
    )
    args = parser.parse_args()

    data = read_json(args.analysis)
    if data.get("schema_version", 0) < 4:
        raise RuntimeError("League analysis schema 4 required")

    predictions = []
    skipped = Counter()
    league_reports = {}

    for name, league in data["leagues"].items():
        names = {
            team["id"]: team["name"]
            for team in league["teams"].values()
        }
        league_rows = []
        seen = set()

        fixtures = sorted(
            league.get("fixtures", []),
            key=lambda match: parse_date(match["date"]),
        )

        for match in fixtures:
            fixture_id = match["fixture_id"]
            if fixture_id in seen:
                continue
            seen.add(fixture_id)

            cutoff = parse_date(match["date"])

            try:
                estimate = estimate_goals(
                    league,
                    names[match["home_id"]],
                    names[match["away_id"]],
                    cutoff,
                )
            except (KeyError, ValueError) as error:
                skipped[f"{name}: {error}"] += 1
                continue

            if min(
                estimate["home_history_matches"],
                estimate["away_history_matches"],
            ) < MIN_VENUE_MATCHES:
                skipped[f"{name}: insufficient venue history"] += 1
                continue

            history = historical_rows(league, cutoff)
            total_weight = sum(weight for _, weight in history)
            actual_total = match["home_goals"] + match["away_goals"]

            for line in LINES:
                probability = 1 - under_probability(
                    estimate["expected_total_goals"], line
                )

                # Bazë krahasimi: shpeshtësia historike over e ligës,
                # e zbutur me 1 sukses dhe 1 mossukses virtual.
                baseline = (
                    sum(
                        weight
                        for past, weight in history
                        if past["home_goals"] + past["away_goals"] > line
                    ) + 1
                ) / (total_weight + 2)

                row = {
                    "league": name,
                    "fixture_id": fixture_id,
                    "date": match["date"],
                    "home": names[match["home_id"]],
                    "away": names[match["away_id"]],
                    "line": line,
                    "selection": "Over",
                    "probability": probability,
                    "baseline_probability": baseline,
                    "actual": int(actual_total > line),
                    "actual_total_goals": actual_total,
                    **estimate,
                }
                league_rows.append(row)
                predictions.append(row)

        by_line = defaultdict(list)
        for row in league_rows:
            by_line[str(row["line"])].append(row)

        league_reports[name] = {
            "summary": summarize(league_rows),
            "by_line": {
                line: summarize(rows)
                for line, rows in by_line.items()
            },
        }

        print(f"\n{name}")
        print(f"Tested matches: {len(league_rows) // len(LINES)}")

        for line, rows in by_line.items():
            report = summarize(rows)
            print(
                f"Over {line} | N={len(rows)} | "
                f"Model Brier={report['model_brier']:.4f} | "
                f"Baseline Brier={report['baseline_brier']:.4f}"
            )

    by_line = defaultdict(list)
    for row in predictions:
        by_line[str(row["line"])].append(row)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "EXPERIMENTAL_RETROSPECTIVE_TEST",
        "evaluation": "current_season_only",
        "minimum_venue_matches": MIN_VENUE_MATCHES,
        "notes": [
            "Lower Brier and log loss are better.",
            "Historical rows are restricted by match kickoff time.",
            "Three-hour gap approximates match completion.",
            "Historical data availability and corrections are not known.",
            "Six lines from one match are correlated observations.",
            "No historical odds: no ROI or profitability measurement.",
            "This test alone does not validate betting value.",
        ],
        "summary": summarize(predictions),
        "by_line": {
            line: summarize(rows)
            for line, rows in by_line.items()
        },
        "leagues": league_reports,
        "skipped_matches": dict(skipped),
        "predictions": predictions,
    }

    Path("data").mkdir(exist_ok=True)
    path = Path("data/backtest_results.json")

    with open(str(path) + ".tmp", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    Path(str(path) + ".tmp").replace(path)

    print("\nBACKTEST COMPLETE")
    print(f"Tested matches: {output['summary'].get('matches', 0)}")
    print(f"Skipped matches: {sum(skipped.values())}")
    print("Lower Brier score is better.")
    print("ROI not calculated: historical odds unavailable.")
    print(f"SUCCESS: Saved {path}")


if __name__ == "__main__":
    main()
