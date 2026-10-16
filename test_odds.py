
import os
import requests
from datetime import datetime, timezone

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"

LEAGUES = {
    368: "Singapore",
    274: "Indonesia",
    296: "Thailand",
    340: "Vietnam",
    233: "Egypt",
}

LINES = {"2.5", "3.5", "4.5", "5.5", "6.5", "7.5"}

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

def main():
    if not API_KEY:
        raise RuntimeError("Missing API_FOOTBALL_KEY")

    today = datetime.now(timezone.utc).date().isoformat()
    total_fixtures = 0
    total_with_odds = 0

    for league_id, league_name in LEAGUES.items():
        print(f"\n=== {league_name} ===")

        fixtures = api_get(
            "/fixtures",
            {"league": league_id, "next": 3}
        )

        for match in fixtures:
            total_fixtures += 1
            fixture_id = match["fixture"]["id"]
            home = match["teams"]["home"]["name"]
            away = match["teams"]["away"]["name"]
            match_date = match["fixture"]["date"]

            print(f"\n{home} vs {away}")
            print(f"Date: {match_date}")
            print(f"Fixture ID: {fixture_id}")

            odds = api_get("/odds", {"fixture": fixture_id})

            if not odds:
                print("No pre-match odds available")
                continue

            total_with_odds += 1

            for item in odds:
                for bookmaker in item.get("bookmakers", []):
                    for bet in bookmaker.get("bets", []):
                        if "Over/Under" not in bet.get("name", ""):
                            continue

                        values = [
                            v for v in bet.get("values", [])
                            if any(
                                v.get("value", "").endswith(line)
                                for line in LINES
                            )
                        ]

                        if values:
                            print("Bookmaker:", bookmaker["name"])
                            print("Market:", bet["name"])
                            for v in values:
                                print(v["value"], "=", v["odd"])

    print("\n=== SUMMARY ===")
    print("Checked at:", today)
    print("Fixtures checked:", total_fixtures)
    print("Fixtures with odds:", total_with_odds)

if __name__ == "__main__":
    main()
