import os
import json
import time
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
    80: "Germany 3. Liga",
    207: "Switzerland Super League",
    208: "Switzerland Challenge League",
}

LINES = {"2.5", "3.5", "4.5", "5.5", "6.5", "7.5"}

MAX_ATTEMPTS = 4
RETRY_STATUSES = {429, 500, 502, 503, 504}


def api_get(endpoint, params):
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response = None

        try:
            response = requests.get(
                BASE_URL + endpoint,
                headers={"x-apisports-key": API_KEY},
                params=params,
                timeout=30,
            )

            if response.status_code in RETRY_STATUSES:
                response.raise_for_status()

            response.raise_for_status()
            data = response.json()

            if data.get("errors"):
                raise RuntimeError(str(data["errors"]))

            return data.get("response", [])

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError,
        ) as error:
            if isinstance(error, requests.exceptions.HTTPError):
                status = (
                    error.response.status_code
                    if error.response is not None
                    else None
                )
                if status not in RETRY_STATUSES:
                    raise
            else:
                status = None

            if attempt == MAX_ATTEMPTS:
                print(
                    f"FAILED: {endpoint} params={params} | "
                    f"All {MAX_ATTEMPTS} attempts exhausted",
                    flush=True,
                )
                raise

            delay = 2 ** attempt

            if response is not None:
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        pass

            delay = min(delay, 60)

            print(
                f"RETRY: {endpoint} params={params} | "
                f"Attempt {attempt}/{MAX_ATTEMPTS} | "
                f"Status={status or 'connection/timeout'} | "
                f"Waiting {delay:g}s",
                flush=True,
            )
            time.sleep(delay)

    raise RuntimeError("API request did not complete")


def main():
    if not API_KEY:
        raise RuntimeError("Missing API_FOOTBALL_KEY")

    captured_at = datetime.now(timezone.utc).isoformat()
    records = []
    checked = 0

    for league_id, league_name in LEAGUES.items():
        print(f"Checking {league_name}...", flush=True)

        fixtures = api_get(
            "/fixtures",
            {"league": league_id, "next": 3},
        )

        for match in fixtures:
            checked += 1
            fixture_id = match["fixture"]["id"]

            odds_data = api_get(
                "/odds",
                {"fixture": fixture_id},
            )
            fetched_at = datetime.now(timezone.utc).isoformat()

            for item in odds_data:
                for bookmaker in item.get("bookmakers", []):
                    for bet in bookmaker.get("bets", []):

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
                                "fetched_at": fetched_at,
                                "provider_updated_at": item.get("update"),
                                "league_id": league_id,
                                "league": league_name,
                                "fixture_id": fixture_id,
                                "match_date": match["fixture"]["date"],
                                "home_id": match["teams"]["home"]["id"],
                                "away_id": match["teams"]["away"]["id"],
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
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "fixtures_checked": checked,
        "odds_records": len(records),
        "records": records,
    }

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"data/odds_{timestamp}.json"

    with open(filename + ".tmp", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    os.replace(filename + ".tmp", filename)

    print("SUCCESS: Odds snapshot saved")
    print("Fixtures checked:", checked)
    print("Odds records:", len(records))
    print("File:", filename)


if __name__ == "__main__":
    main()
