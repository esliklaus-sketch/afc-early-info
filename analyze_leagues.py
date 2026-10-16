
import os
import json
import time
import requests
from datetime import datetime, timezone

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"

# Ligat e testimit
LEAGUES = {
    274: "Indonesia Liga 1",
    368: "Singapore Premier League",
    296: "Thailand Thai League 1",
    340: "Vietnam V.League 1",
    233: "Egypt Premier League",
}

SEASON = 2025

def get_fixtures(league_id):
    response = requests.get(
        f"{BASE_URL}/fixtures",
        headers={"x-apisports-key": API_KEY},
        params={"league": league_id, "season": SEASON, "status": "FT"},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("errors"):
        raise RuntimeError(str(data["errors"]))

    return data.get("response", [])

def analyze(fixtures):
    results = {
        "matches": 0,
        "over_2_5": 0,
        "over_3_5": 0,
        "over_4_5": 0,
        "total_goals": 0,
    }

    for match in fixtures:
        goals = match.get("goals", {})
        home = goals.get("home")
        away = goals.get("away")

        if home is None or away is None:
            continue

        total = home + away
        results["matches"] += 1
        results["total_goals"] += total

        if total > 2.5:
            results["over_2_5"] += 1
        if total > 3.5:
            results["over_3_5"] += 1
        if total > 4.5:
            results["over_4_5"] += 1

    n = results["matches"]

    if n:
        results["avg_goals"] = round(results["total_goals"] / n, 2)
        for line in ("2_5", "3_5", "4_5"):
            results[f"over_{line}_pct"] = round(
                results[f"over_{line}"] / n * 100, 2
            )

    return results

def main():
    if not API_KEY:
        raise RuntimeError("Missing API_FOOTBALL_KEY")

    output = {
        "season": SEASON,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "leagues": {},
    }

    for league_id, name in LEAGUES.items():
        print(f"Analyzing {name}...")

        fixtures = get_fixtures(league_id)
        stats = analyze(fixtures)

        output["leagues"][name] = {
            "id": league_id,
            **stats,
        }

        print(f"Matches: {stats['matches']}")
        print(f"Average goals: {stats.get('avg_goals', 'N/A')}")
        time.sleep(1)

    os.makedirs("data", exist_ok=True)

    with open("data/league_analysis.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("SUCCESS: League analysis saved")

if __name__ == "__main__":
    main()
