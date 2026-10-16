import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

LINES = (2.5, 3.5, 4.5, 5.5, 6.5, 7.5)

# Parametra fillestarë; do të vlerësohen me teste historike.
PREVIOUS_WEIGHT = 0.5
PRIOR_MATCHES = 5.0


def parse_date(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Date must include timezone")
    return result.astimezone(timezone.utc)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def historical_rows(league, cutoff):
    rows = []
    seen = set()

    for season, weight in (
        (league, 1.0),
        (league.get("previous_season") or {}, PREVIOUS_WEIGHT),
    ):
        for match in season.get("fixtures", []):
            fixture_id = match["fixture_id"]

            # Të dhënat përmbajnë orën e nisjes, jo të përfundimit.
            if parse_date(match["date"]) > cutoff - timedelta(hours=3):
                continue

            if fixture_id in seen:
                continue

            seen.add(fixture_id)
            rows.append((match, weight))

    return rows


def find_team_id(league, name):
    # Vetëm përputhje të sakta; nuk hamendësojmë emra të ngjashëm.
    matches = [
        team["id"]
        for team in league.get("teams", {}).values()
        if team.get("name") == name
    ]

    if len(matches) != 1:
        raise ValueError(f"Team name missing or ambiguous: {name}")

    return matches[0]


def estimate_goals(league, home_name, away_name, cutoff):
    home_id = find_team_id(league, home_name)
    away_id = find_team_id(league, away_name)
    rows = historical_rows(league, cutoff)

    total_weight = sum(weight for _, weight in rows)
    if total_weight <= 0:
        raise ValueError("No historical matches available")

    home_base = sum(
        m["home_goals"] * w for m, w in rows
    ) / total_weight

    away_base = sum(
        m["away_goals"] * w for m, w in rows
    ) / total_weight

    if home_base <= 0 or away_base <= 0:
        raise ValueError("Insufficient league goal data")

    def venue_rates(team_id, venue):
        selected = [
            (m, w) for m, w in rows
            if m[f"{venue}_id"] == team_id
        ]

        if not selected:
            raise ValueError(f"No {venue} history for team {team_id}")

        opposite = "away" if venue == "home" else "home"
        scored_base = home_base if venue == "home" else away_base
        conceded_base = away_base if venue == "home" else home_base
        weight = sum(w for _, w in selected)

        scored = (
            sum(m[f"{venue}_goals"] * w for m, w in selected)
            + PRIOR_MATCHES * scored_base
        ) / (weight + PRIOR_MATCHES)

        conceded = (
            sum(m[f"{opposite}_goals"] * w for m, w in selected)
            + PRIOR_MATCHES * conceded_base
        ) / (weight + PRIOR_MATCHES)

        return scored, conceded, len(selected), weight

    home_for, home_against, home_n, home_w = venue_rates(
        home_id, "home"
    )
    away_for, away_against, away_n, away_w = venue_rates(
        away_id, "away"
    )

    expected_home = home_for * away_against / home_base
    expected_away = away_for * home_against / away_base

    return {
        "expected_home_goals": expected_home,
        "expected_away_goals": expected_away,
        "expected_total_goals": expected_home + expected_away,
        "home_history_matches": home_n,
        "away_history_matches": away_n,
        "home_weighted_matches": home_w,
        "away_weighted_matches": away_w,
    }


def under_probability(expected_total, line):
    term = math.exp(-expected_total)
    probability = term

    for goals in range(1, math.floor(line) + 1):
        term *= expected_total / goals
        probability += term

    return min(1.0, max(0.0, probability))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--analysis", default="data/league_analysis.json"
    )
    parser.add_argument("--odds")
    args = parser.parse_args()

    analysis = read_json(args.analysis)

    if analysis.get("schema_version", 0) < 4:
        raise RuntimeError("Run the updated league analysis first")

    if args.odds:
        odds_path = Path(args.odds)
    else:
        paths = list(Path("data").glob("odds_*.json"))
        if not paths:
            raise RuntimeError("No odds snapshots found in data/")
        odds_path = max(
            paths,
            key=lambda p: parse_date(read_json(p)["captured_at"]),
        )

    snapshot = read_json(odds_path)
    captured = parse_date(snapshot["captured_at"])
    leagues = {
        int(league["id"]): league
        for league in analysis["leagues"].values()
    }

    predictions = {}
    results = []
    skipped = Counter()
    seen = set()

    for record in snapshot.get("records", []):
        try:
            line = float(record["line"])
            odd = float(record["odd"])
            selection = record["selection"]
            league_id = int(record["league_id"])
            kickoff = parse_date(record["match_date"])

            if record.get("market") != "Full Time Goals":
                skipped["unsupported_market"] += 1
                continue

            if line not in LINES or selection not in ("Over", "Under"):
                skipped["unsupported_selection"] += 1
                continue

            if not math.isfinite(odd) or odd <= 1:
                skipped["invalid_odd"] += 1
                continue

            if kickoff <= captured:
                skipped["already_started_at_capture"] += 1
                continue

            key = (
                league_id,
                record["fixture_id"],
                record["bookmaker"],
                line,
                selection,
            )

            if key in seen:
                skipped["duplicate"] += 1
                continue
            seen.add(key)

            prediction_key = (
                league_id,
                record["fixture_id"],
                record["home"],
                record["away"],
            )

            if prediction_key not in predictions:
                predictions[prediction_key] = estimate_goals(
                    leagues[league_id],
                    record["home"],
                    record["away"],
                    captured,
                )

            estimate = predictions[prediction_key]
            under = under_probability(
                estimate["expected_total_goals"], line
            )
            probability = under if selection == "Under" else 1 - under

            if probability <= 0:
                skipped["zero_probability"] += 1
                continue

            results.append({
                **record,
                **estimate,
                "model_probability": probability,
                "fair_odd": 1 / probability,
                "break_even_probability": 1 / odd,
                "edge_percentage_points": (
                    probability - 1 / odd
                ) * 100,
                "model_ev_pct": (probability * odd - 1) * 100,
                "status": "EXPERIMENTAL_UNVALIDATED",
            })

        except (KeyError, ValueError, TypeError) as error:
            skipped[str(error)] += 1

    results.sort(key=lambda r: r["model_ev_pct"], reverse=True)

    output = {
        "model_version": "poisson_baseline_v1",
        "status": "EXPERIMENTAL_UNVALIDATED",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "odds_file": str(odds_path),
        "odds_captured_at": snapshot["captured_at"],
        "analysis_updated_at": analysis.get("updated_at"),
        "note": (
            "Capture time is not bookmaker update time. "
            "Positive model EV is unvalidated, not confirmed value."
        ),
        "parameters": {
            "previous_season_weight": PREVIOUS_WEIGHT,
            "prior_matches": PRIOR_MATCHES,
        },
        "evaluated_records": len(results),
        "evaluated_fixtures": len({
            r["fixture_id"] for r in results
        }),
        "skipped": dict(skipped),
        "results": results,
    }

    Path("data").mkdir(exist_ok=True)
    path = Path("data/value_analysis.json")

    with open(str(path) + ".tmp", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    Path(str(path) + ".tmp").replace(path)

    print("EXPERIMENTAL VALUE MODEL")
    print(f"Odds snapshot: {snapshot['captured_at']}")
    print(f"Evaluated records: {len(results)}")
    print(f"Evaluated fixtures: {output['evaluated_fixtures']}")
    print(f"Skipped: {dict(skipped)}")

    for record in results[:10]:
        print(
            f"{record['home']} vs {record['away']} | "
            f"{record['selection']} {record['line']} | "
            f"{record['bookmaker']} @ {record['odd']} | "
            f"P={record['model_probability']:.1%} | "
            f"Fair={record['fair_odd']:.2f} | "
            f"Model EV={record['model_ev_pct']:+.1f}%"
        )

    print(f"SUCCESS: Saved {path}")


if __name__ == "__main__":
    main()
