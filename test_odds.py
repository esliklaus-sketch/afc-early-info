
import os
import requests

API_KEY = os.getenv("API_FOOTBALL_KEY")
BASE_URL = "https://v3.football.api-sports.io"

def main():
    if not API_KEY:
        raise RuntimeError("Missing API_FOOTBALL_KEY")

    headers = {"x-apisports-key": API_KEY}

    # Gjejme nje ndeshje te perfunduar ne Singapor
    response = requests.get(
        f"{BASE_URL}/fixtures",
        headers=headers,
        params={
            "league": 368,
            "season": 2025,
            "status": "FT",
            "last": 1
        },
        timeout=30
    )
    response.raise_for_status()
    data = response.json()

    if data.get("errors"):
        raise RuntimeError(str(data["errors"]))

    fixtures = data.get("response", [])

    if not fixtures:
        print("No fixtures found")
        return

    match = fixtures[0]
    fixture_id = match["fixture"]["id"]

    print("MATCH:", match["teams"]["home"]["name"],
          "vs", match["teams"]["away"]["name"])
    print("FIXTURE ID:", fixture_id)

    # Kontrollojme kuotat historike
    response = requests.get(
        f"{BASE_URL}/odds",
        headers=headers,
        params={"fixture": fixture_id},
        timeout=30
    )
    response.raise_for_status()
    odds = response.json()

    if odds.get("errors"):
        raise RuntimeError(str(odds["errors"]))

    print("ODDS RESULTS:", odds.get("results", 0))

    for item in odds.get("response", []):
        for bookmaker in item.get("bookmakers", []):
            print("BOOKMAKER:", bookmaker["name"])

            for bet in bookmaker.get("bets", []):
                if "Over/Under" in bet["name"]:
                    print("MARKET:", bet["name"])
                    for value in bet.get("values", []):
                        print(value["value"], value["odd"])

if __name__ == "__main__":
    main()
