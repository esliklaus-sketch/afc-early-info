import os
import json
import time
import requests
from datetime import datetime, timezone

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"

LEAGUES = {
    274: "Indonesia Liga 1",
    368: "Singapore Premier League",
    296: "Thailand Thai League 1",
    340: "Vietnam V.League 1",
    233: "Egypt Premier League",
}

LINES = (2.5, 3.5, 4.5, 5.5, 6.5, 7.5)


def api_get(endpoint, params):
    response = requests.get(
        BASE_URL + endpoint,
        headers={"x-apisports-key": API_KEY},
        params=params,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("errors"):
        raise RuntimeError(str(data["errors"]))

    return data.get("response", [])


def get_current_season(league_id):
    leagues = api_get("/leagues", {"id": league_id})

    if not leagues:
        raise RuntimeError(f"League not found: {league_id}")

    seasons = leagues[0].get("seasons", [])
    current = [
        season for season in seasons
        if season.get("current") is True
    ]

    if len(current) != 1:
        raise RuntimeError(
            f"Cannot identify current season: league {league_id}"
        )

    season = current[0]
    print(
        f"Season: {season['year']} | "
        f"Start: {season.get('start')} | "
        f"End: {season.get('end')}",
        flush=True,
    )
    return season["year"]


def get_fixtures(league_id, season):
    return api_get(
        "/fixtures",
        {
            "league": league_id,
            "season": season,
            "status": "FT",
        },
    )


def line_key(line):
    return str(line).replace(".", "_")


def empty_stats():
    stats = {
        "matches": 0,
        "goals_for": 0,
        "goals_against": 0,
        "total_goals": 0,
    }

    for line in LINES:
        stats[f"over_{line_key(line)}"] = 0

    return stats


def add_match(stats, goals_for, goals_against):
    total = goals_for + goals_against
    stats["matches"] += 1
    stats["goals_for"] += goals_for
    stats["goals_against"] += goals_against
    stats["total_goals"] += total

    for line in LINES:
        if total > line:
            stats[f"over_{line_key(line)}"] += 1


def summarize(stats):
    result = dict(stats)
    n = stats["matches"]

    result["avg_goals"] = (
        round(stats["total_goals"] / n, 4) if n else None
    )
    result["avg_goals_for"] = (
        round(stats["goals_for"] / n, 4) if n else None
    )
    result["avg_goals_against"] = (
        round(stats["goals_against"] / n, 4) if n else None
    )

    for line in LINES:
        key = line_key(line)
        over = stats[f"over_{key}"]

        result[f"under_{key}"] = n - over
        result[f"over_{key}_pct"] = (
            round(over / n * 100, 2) if n else None
        )
        result[f"under_{key}_pct"] = (
            round((n - over) / n * 100, 2) if n else None
        )

    return result


def analyze(fixtures):
    league_stats = empty_stats()
    home_goals_total = 0
    away_goals_total = 0
    teams = {}
    seen = set()
    skipped = 0
    latest_match_at = None

    for match in fixtures:
        fixture = match.get("fixture") or {}
        fixture_id = fixture.get("id")
        status = (fixture.get("status") or {}).get("short")

        if status != "FT":
            skipped += 1
            continue

        if fixture_id is not None and fixture_id in seen:
            continue

        goals = match.get("goals") or {}
        home_goals = goals.get("home")
        away_goals = goals.get("away")

        match_teams = match.get("teams") or {}
        home_team = match_teams.get("home") or {}
        away_team = match_teams.get("away") or {}

        if (
            home_goals is None
            or away_goals is None
            or home_team.get("id") is None
            or away_team.get("id") is None
        ):
            skipped += 1
            continue

        if fixture_id is not None:
            seen.add(fixture_id)

        add_match(league_stats, home_goals, away_goals)
        home_goals_total += home_goals
        away_goals_total += away_goals

        match_date = fixture.get("date")
        if match_date:
            if latest_match_at is None or match_date > latest_match_at:
                latest_match_at = match_date

        for team, venue, scored, conceded in (
            (home_team, "home", home_goals, away_goals),
            (away_team, "away", away_goals, home_goals),
        ):
            team_id = str(team["id"])

            if team_id not in teams:
                teams[team_id] = {
                    "id": team["id"],
                    "name": team.get("name"),
                    "overall": empty_stats(),
                    "home": empty_stats(),
                    "away": empty_stats(),
                }

            add_match(teams[team_id]["overall"], scored, conceded)
            add_match(teams[team_id][venue], scored, conceded)

    n = league_stats["matches"]
    result = summarize(league_stats)

    result["home_goals_total"] = home_goals_total
    result["away_goals_total"] = away_goals_total
    result["avg_home_goals"] = (
        round(home_goals_total / n, 4) if n else None
    )
    result["avg_away_goals"] = (
        round(away_goals_total / n, 4) if n else None
    )
    result["skipped_matches"] = skipped
    result["latest_match_at"] = latest_match_at
    result["teams"] = {}

    for team_id, team in teams.items():
        result["teams"][team_id] = {
            "id": team["id"],
            "name": team["name"],
            "overall": summarize(team["overall"]),
            "home": summarize(team["home"]),
            "away": summarize(team["away"]),
        }

    return result


def main():
    if not API_KEY:
        raise RuntimeError("Missing API_FOOTBALL_KEY")

    output = {
        "schema_version": 3,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "season_mode": "api_current_per_league",
        "lines": list(LINES),
        "leagues": {},
    }

    for league_id, name in LEAGUES.items():
        print(f"Analyzing {name}...", flush=True)

        season = get_current_season(league_id)
        time.sleep(1)

        fixtures = get_fixtures(league_id, season)
        stats = analyze(fixtures)

        output["leagues"][name] = {
            "id": league_id,
            "season": season,
            **stats,
        }

        print(f"Matches: {stats['matches']}")
        print(f"Teams: {len(stats['teams'])}")
        print(f"Average goals: {stats['avg_goals']}")
        print(f"Latest match: {stats['latest_match_at']}")

        if not stats["matches"]:
            print("WARNING: No completed matches for this season.")

        time.sleep(1)

    os.makedirs("data", exist_ok=True)
    output_path = "data/league_analysis.json"
    temporary_path = output_path + ".tmp"

    with open(temporary_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    os.replace(temporary_path, output_path)
    print(f"SUCCESS: League and team analysis saved: {output_path}")


if __name__ == "__main__":
    main()
