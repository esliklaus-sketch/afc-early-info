import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from value_model import (
    LINES,
    MIN_VENUE_MATCHES,
    estimate_goals,
    historical_rows,
    parse_date,
    read_json,
    under_probability,
)


def summarize(rows):
    if not rows:
        return {"predictions": 0, "matches": 0}

    n = len(rows)
    model_brier = sum(
        (r["probability"] - r["actual"]) ** 2 for r in rows
    ) / n
    baseline_brier = sum(
        (r["baseline_probability"] - r["actual"]) ** 2
        for r in rows
    ) / n

    loss = 0.0
    for row in rows:
        p = min(1 - 1e-12, max(1e-12, row["probability"]))
        y = row["actual"]
        loss -= y * math.log(p) + (1 - y) * math.log(1 - p)

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
        "matches": len({
            (r["league_id"], r["fixture_id"]) for r in rows
        }),
        "model_brier": model_brier,
        "baseline_brier": baseline_brier,
        "brier_skill": (
            1 - model_brier / baseline_brier
            if baseline_brier > 0 else None
        ),
        "model_log_loss": loss / n,
        "expected_overs": sum(r["probability"] for r in rows),
        "actual_overs": sum(r["actual"] for r in rows),
        "mean_probability": sum(
            r["probability"] for r in rows
        ) / n,
        "observed_frequency": sum(r["actual"] for r in rows) / n,
        "calibration_bins": bins,
    }


def report(rows):
    by_line = defaultdict(list)
    for row in rows:
        by_line[str(row["line"])].append(row)

    return {
        "summary": summarize(rows),
        "by_line": {
            line: summarize(items)
            for line, items in by_line.items()
        },
    }


def test_season(name, league_id, season, label):
    names = {
        team["id"]: team["name"]
        for team in season["teams"].values()
    }
    predictions = []
    skipped = Counter()
    seen = set()

    fixtures = sorted(
        season.get("fixtures", []),
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
                season,
                names[match["home_id"]],
                names[match["away_id"]],
                cutoff,
            )
        except (KeyError, ValueError) as error:
            skipped[str(error)] += 1
            continue

        history = historical_rows(season, cutoff)
        total_weight = sum(weight for _, weight in history)
        actual_total = match["home_goals"] + match["away_goals"]

        for line in LINES:
            probability = 1 - under_probability(
                estimate["expected_total_goals"], line
            )

            baseline = (
                sum(
                    weight
                    for past, weight in history
                    if past["home_goals"] + past["away_goals"] > line
                ) + 1
            ) / (total_weight + 2)

            predictions.append({
                "league": name,
                "league_id": league_id,
                "season": season["season"],
                "evaluation_period": label,
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
            })

    result = report(predictions)
    result["season"] = season["season"]
    result["skipped_matches"] = dict(skipped)

    print(f"\n{name} | {label} season {season['season']}")
    print(f"Tested matches: {result['summary']['matches']}")
    print(f"Skipped matches: {sum(skipped.values())}")

    for line, stats in result["by_line"].items():
        print(
            f"Over {line} | N={stats['matches']} | "
            f"Model Brier={stats['model_brier']:.4f} | "
            f"Baseline Brier={stats['baseline_brier']:.4f} | "
            f"Expected={stats['expected_overs']:.1f} | "
            f"Actual={stats['actual_overs']}"
        )

    return predictions, result, sum(skipped.values())


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
    league_reports = {}
    skipped_total = 0

    for name, league in data["leagues"].items():
        league_reports[name] = {}
        previous = league.get("previous_season")

        if previous:
            # Ky sezon trajtohet si sezoni aktiv në datën e testit.
            # Asnjë rezultat nga sezoni i sotëm nuk përdoret këtu.
            previous_view = {
                **previous,
                "previous_season": None,
            }
            rows, result, skipped = test_season(
                name, league["id"], previous_view, "previous"
            )
            predictions.extend(rows)
            league_reports[name]["previous"] = result
            skipped_total += skipped

        rows, result, skipped = test_season(
            name, league["id"], league, "current"
        )
        predictions.extend(rows)
        league_reports[name]["current"] = result
        skipped_total += skipped

    periods = {}
    for label in ("previous", "current"):
        periods[label] = report([
            row for row in predictions
            if row["evaluation_period"] == label
        ])

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "EXPERIMENTAL_RETROSPECTIVE_TEST",
        "evaluation": "previous_and_current_seasons_separate",
        "minimum_venue_matches": MIN_VENUE_MATCHES,
        "notes": [
            "Lower Brier and log loss are better.",
            "Only earlier matches are used for each prediction.",
            "Three-hour gap approximates match completion.",
            "Historical data availability and corrections are unknown.",
            "Previous season has no preceding season in this dataset.",
            "Current-season training includes available previous season.",
            "The two periods therefore have different history depth.",
            "Six lines from one match are correlated observations.",
            "No historical odds: ROI is not measured.",
            "Previously inspected results are not an untouched holdout.",
        ],
        **report(predictions),
        "by_period": periods,
        "leagues": league_reports,
        "skipped_matches_total": skipped_total,
        "predictions": predictions,
    }

    Path("data").mkdir(exist_ok=True)
    path = Path("data/backtest_results.json")

    with open(str(path) + ".tmp", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    Path(str(path) + ".tmp").replace(path)

    print("\nBACKTEST COMPLETE")
    print(f"Tested matches: {output['summary']['matches']}")
    print(f"Skipped matches: {skipped_total}")
    print("ROI not calculated: historical odds unavailable.")
    print(f"SUCCESS: Saved {path}")


if __name__ == "__main__":
    main()
