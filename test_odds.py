
import os
import json
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

    captured_at = datetime.now(timezone.utc).isoformat()
    records = []
    checked = 0

    for league_id, league_name in LEAGUES.items():
        print(f"Checking {league_name}...")

        fixtures = api_get(
            "/fixtures",
            {"league": league_id, "next": 3}
        )

        for match in fixtures:
            checked += 1
            fixture_id = match["fixture"]["id"]

            odds_data = api_get(
                "/odds",
                {"fixture": fixture_id}
            )

            for item in odds_data:
                for bookmaker in item.get("bookmakers", []):
                    for bet in bookmaker.get("bets", []):

                        # Only full-time Over/Under
                        if bet.get("name") != "Goals Over/Under":
                            continue

                        for value in bet.get("values", []):
                            parts = value.get("value", "").split()

                            if len(parts) != 2:
                                continue

                            side, line = parts

                            if side not in ("Over", "Under"):
                                continue

                            if line not in LINES:
                                continue

                            records.append({
                                "captured_at": captured_at,
                                "league_id": league_id,
                                "league": league_name,
                                "fixture_id": fixture_id,
                                "match_date": match["fixture"]["date"],
                                "home": match["teams"]["home"]["name"],
                                "away": match["teams"]["away"]["name"],
                                "bookmaker": bookmaker["name"],
                                "market": "Full Time Goals",
                                "selection": side,
                                "line": float(line),
                                "odd": value.get("odd"),
                            })

    os.makedirs("data", exist_ok=True)

    output = {
        "captured_at": captured_at,
        "fixtures_checked": checked,
        "odds_records": len(records),
        "records": records,
    }

    
timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
filename = f"data/odds_{timestamp}.json"


    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("SUCCESS: Odds snapshot saved")
    print("Fixtures checked:", checked)
    print("Odds records:", len(records))
    print("File:", filename)

if __name__ == "__main__":
    main()
