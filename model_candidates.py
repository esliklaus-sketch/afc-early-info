import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from value_model import (
    MIN_VENUE_MATCHES,
    estimate_goals,
    historical_rows,
    parse_date,
    read_json,
    under_probability,
)

# Variante të paracaktuara për krahasim.
HALF_LIVES = (180, 365)
TEST_LINES = (2.5, 3.5, 4.5, 5.5, 6.5, 7.5)
PRIOR_WEIGHT = 5.0
ITERATIONS = 40


def fit_strengths(rows, cutoff, half_life):
    weighted = []

    for match, season_weight in rows:
        age = max(
            0.0,
            (cutoff - parse_date(match["date"])).total_seconds()
            / 86400,
        )
        weight = season_weight * 0.5 ** (age / half_life)
        weighted.append((match, weight))

    total_weight = sum(w for _, w in weighted)
    if total_weight <= 0:
        raise ValueError("No training history")

    home_base = sum(
        m["home_goals"] * w for m, w in weighted
    ) / total_weight
    away_base = sum(
        m["away_goals"] * w for m, w in weighted
    ) / total_weight

    if min(home_base, away_base) <= 0:
        raise ValueError("Insufficient goal data")

    # Çdo rresht përfaqëson golat e një ekipi kundër tjetrit.
    observations = []
    teams = set()

    for match, weight in weighted:
        home = match["home_id"]
        away = match["away_id"]
        teams.update((home, away))

        observations.append(
            (home, away, match["home_goals"], home_base, weight)
        )
        observations.append(
            (away, home, match["away_goals"], away_base, weight)
        )

    attack = {team: 1.0 for team in teams}
    defense = {team: 1.0 for team in teams}

    # Vlerësim iterativ i sulmit dhe dobësisë mbrojtëse.
    # Prior-i i afron ekipet me mesataren e ligës.
    for _ in range(ITERATIONS):
        scored = defaultdict(float)
        exposure = defaultdict(float)

        for team, opponent, goals, base, weight in observations:
            scored[team] += weight * goals
            exposure[team] += weight * base * defense[opponent]

        attack = {
            team: (scored[team] + PRIOR_WEIGHT)
            / (exposure[team] + PRIOR_WEIGHT)
            for team in teams
        }

        conceded = defaultdict(float)
        exposure = defaultdict(float)

        for team, opponent, goals, base, weight in observations:
            conceded[opponent] += weight * goals
            exposure[opponent] += weight * base * attack[team]

        defense = {
            team: (conceded[team] + PRIOR_WEIGHT)
            / (exposure[team] + PRIOR_WEIGHT)
            for team in teams
        }

    return home_base, away_base, attack, defense


def summarize(rows, model):
    n = len(rows)
    if not n:
        return {"matches": 0}

    result = {"matches": n, "by_line": {}}

    for line in TEST_LINES:
        key = str(line)
        probabilities = [r["probabilities"][model][key] for r in rows]
        actuals = [int(r["total_goals"] > line) for r in rows]

        result["by_line"][key] = {
            "brier": sum(
                (p - y) ** 2
                for p, y in zip(probabilities, actuals)
            ) / n,
            "expected_overs": sum(probabilities),
            "actual_overs": sum(actuals),
        }

    return result


def main():
    data = read_json("data/league_analysis.json")
    if data.get("schema_version", 0) < 4:
        raise RuntimeError("League analysis schema 4 required")

    models = [
        "current_model",
        "league_baseline",
        *[f"opponent_adjusted_{days}d" for days in HALF_LIVES],
    ]

    predictions = []
    skipped = Counter()
    reports = {}

    for name, league in data["leagues"].items():
        names = {
            team["id"]: team["name"]
            for team in league["teams"].values()
        }

        league_rows = []
        seen = set()

        for match in sorted(
            league.get("fixtures", []),
            key=lambda m: parse_date(m["date"]),
        ):
            fixture_id = match["fixture_id"]
            if fixture_id in seen:
                continue
            seen.add(fixture_id)

            cutoff = parse_date(match["date"])
            home = match["home_id"]
            away = match["away_id"]

            try:
                # Edhe kandidatët përdorin të njëjtin filtër historie.
                original = estimate_goals(
                    league, names[home], names[away], cutoff
                )
                history = historical_rows(league, cutoff)

                if min(
                    original["home_history_matches"],
                    original["away_history_matches"],
                ) < MIN_VENUE_MATCHES:
                    raise ValueError("Insufficient venue history")

                expected = {
                    "current_model": original["expected_total_goals"]
                }

                for days in HALF_LIVES:
                    hb, ab, attack, defense = fit_strengths(
                        history, cutoff, days
                    )
                    expected[f"opponent_adjusted_{days}d"] = (
                        hb * attack[home] * defense[away]
                        + ab * attack[away] * defense[home]
                    )

                probabilities = {
                    model: {
                        str(line): 1 - under_probability(total, line)
                        for line in TEST_LINES
                    }
                    for model, total in expected.items()
                }

                weight = sum(w for _, w in history)
                probabilities["league_baseline"] = {
                    str(line): (
                        sum(
                            w for past, w in history
                            if past["home_goals"] + past["away_goals"]
                            > line
                        ) + 1
                    ) / (weight + 2)
                    for line in TEST_LINES
                }

                row = {
                    "league": name,
                    "league_id": league["id"],
                    "fixture_id": fixture_id,
                    "date": match["date"],
                    "total_goals": (
                        match["home_goals"] + match["away_goals"]
                    ),
                    "expected_goals": expected,
                    "probabilities": probabilities,
                }

                league_rows.append(row)
                predictions.append(row)

            except (KeyError, ValueError) as error:
                skipped[f"{name}: {error}"] += 1

        reports[name] = {
            model: summarize(league_rows, model)
            for model in models
        }

    overall = {
        model: summarize(predictions, model)
        for model in models
    }

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "DEVELOPMENT_COMPARISON_NOT_FINAL_VALIDATION",
        "evaluation": "current_season_same_matches_for_all_models",
        "notes": [
            "Only history before each match is used.",
            "All models are compared on the same evaluated matches.",
            "This period has already been inspected.",
            "Future unseen matches are needed for final validation.",
            "No historical odds: no ROI measurement.",
            "Candidates do not replace the active value model.",
        ],
        "parameters": {
            "half_lives_days": list(HALF_LIVES),
            "prior_weight": PRIOR_WEIGHT,
            "iterations": ITERATIONS,
        },
        "overall": overall,
        "leagues": reports,
        "skipped": dict(skipped),
        "predictions": predictions,
    }

    Path("data").mkdir(exist_ok=True)
    path = Path("data/model_candidates.json")

    with open(str(path) + ".tmp", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    Path(str(path) + ".tmp").replace(path)

    print("MODEL CANDIDATES - DEVELOPMENT COMPARISON")
    print(f"Compared matches: {len(predictions)}")

    for model, result in overall.items():
        print(f"\n{model}")
        for line, stats in result.get("by_line", {}).items():
            print(
                f"Over {line} | Brier={stats['brier']:.5f} | "
                f"Expected={stats['expected_overs']:.1f} | "
                f"Actual={stats['actual_overs']}"
            )

    print(f"\nSUCCESS: Saved {path}")


if __name__ == "__main__":
    main()
