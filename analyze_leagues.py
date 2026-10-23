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
    80: "Germany 3. Liga",
    207: "Switzerland Super League",
    208: "Switzerland Challenge League",
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


def get_seasons(league_id):
    leagues = api_get("/leagues", {"id": league_id})

    if not leagues:
        raise RuntimeError(f"League not found: {league_id}")

    seasons = leagues[0].get("seasons", [])
    current = [s for s in seasons if s.get("current") is True]

    if len(current) != 1:
        raise RuntimeError(
            f"Cannot identify current season: league {league_id}"
        )

    current = current[0]
    start = current.get("start")

    if not start:
        raise RuntimeError(f"Missing season start: league {league_id}")

    earlier = [
        s for s in seasons
        if s.get("start")
        and s["start"] < start
        and s.get("year") != current["year"]
    ]

    previous = (
        max(earlier, key=lambda s: s["start"]) if earlier else None
    )

    return current, previous


def get_fixtures(league_id, season):
    return api_get(
        "/fixtures",
        {"league": league_id, "season": season, "status": "FT"},
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


def add_match(stats, scored, conceded):
    total = scored + conceded
    stats["matches"] += 1
    stats["goals_for"] += scored
    stats["goals_against"] += conceded
    stats["total_goals"] += total

    for line in LINES:
        if total > line:
            stats[f"over_{line_key(line)}"] += 1


def summarize(stats):
    result = dict(stats)
    n = stats["matches"]

    for source, target in (
        ("total_goals", "avg_goals"),
        ("goals_for", "avg_goals_for"),
        ("goals_against", "avg_goals_against"),
    ):
        result[target] = round(stats[source] / n, 4) if n else None

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
    league = empty_stats()
    teams = {}
    records = []
    seen = set()
    skipped = 0
    home_total = 0
    away_total = 0

    for match in fixtures:
        fixture = match.get("fixture") or {}
        fixture_id = fixture.get("id")
        status = (fixture.get("status") or {}).get("short")
        goals = match.get("goals") or {}
        sides = match.get("teams") or {}
        home = sides.get("home") or {}
        away = sides.get("away") or {}
        hg = goals.get("home")
        ag = goals.get("away")
        date = fixture.get("date")

        if (
            status != "FT"
            or fixture_id is None
            or not date
            or home.get("id") is None
            or away.get("id") is None
            or hg is None
            or ag is None
        ):
            skipped += 1
            continue

        if fixture_id in seen:
            continue
        seen.add(fixture_id)

        add_match(league, hg, ag)
        home_total += hg
        away_total += ag

        records.append({
            "fixture_id": fixture_id,
            "date": date,
            "home_id": home["id"],
            "away_id": away["id"],
            "home_goals": hg,
            "away_goals": ag,
        })

        for team, venue, scored, conceded in (
            (home, "home", hg, ag),
            (away, "away", ag, hg),
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

    records.sort(key=lambda r: r["date"])
    n = league["matches"]
    result = summarize(league)
    result.update({
        "home_goals_total": home_total,
        "away_goals_total": away_total,
        "avg_home_goals": round(home_total / n, 4) if n else None,
        "avg_away_goals": round(away_total / n, 4) if n else None,
        "skipped_matches": skipped,
        "latest_match_at": records[-1]["date"] if records else None,
        "fixtures": records,
        "teams": {},
    })

    for team_id, team in teams.items():
        result["teams"][team_id] = {
            "id": team["id"],
            "name": team["name"],
            "overall": summarize(team["overall"]),
            "home": summarize(team["home"]),
            "away": summarize(team["away"]),
        }

    return result


def collect_season(league_id, season, label):
    print(
        f"{label} season: {season['year']} | "
        f"Start: {season.get('start')} | End: {season.get('end')}",
        flush=True,
    )

    time.sleep(1)
    stats = analyze(get_fixtures(league_id, season["year"]))

    print(f"Matches: {stats['matches']}")
    print(f"Teams: {len(stats['teams'])}")
    print(f"Average goals: {stats['avg_goals']}")
    print(f"Latest match: {stats['latest_match_at']}", flush=True)

    if not stats["matches"]:
        print(f"WARNING: No completed matches in {label} season.")

    return {
        "season": season["year"],
        "season_start": season.get("start"),
        "season_end": season.get("end"),
        **stats,
    }


def main():
    if not API_KEY:
        raise RuntimeError("Missing API_FOOTBALL_KEY")

    output = {
        "schema_version": 4,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "season_mode": "current_and_previous_separate",
        "lines": list(LINES),
        "leagues": {},
    }

    for league_id, name in LEAGUES.items():
        print(f"\nAnalyzing {name}...", flush=True)
        current, previous = get_seasons(league_id)

        current_stats = collect_season(league_id, current, "Current")
        previous_stats = None

        if previous:
            previous_stats = collect_season(
                league_id, previous, "Previous"
            )
        else:
            print("WARNING: Previous season unavailable.")

        older_stats = None
        if league_id in (80, 207, 208):
            older_stats = collect_season(
                league_id,
                {"year": 2024, "start": None, "end": None},
                "Historical 2024",
            )

        output["leagues"][name] = {
            "id": league_id,
            **current_stats,
            "previous_season": previous_stats,
            "historical_2024": older_stats,
        }

        time.sleep(1)

    os.makedirs("data", exist_ok=True)
    path = "data/league_analysis.json"

    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    os.replace(path + ".tmp", path)
    print(f"\nSUCCESS: Current and previous seasons saved: {path}")


if __name__ == "__main__":
    main()
