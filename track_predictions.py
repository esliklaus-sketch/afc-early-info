import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from test_odds import api_get, API_KEY
from value_model import parse_date, read_json

STATE_PATH = Path("data/prediction_tracking.json")
VALUE_PATH = Path("data/value_analysis.json")


def prediction_key(model, row):
    return json.dumps(
        [
            model,
            row["league_id"],
            row["fixture_id"],
            row["bookmaker"],
            row["market"],
            row["selection"],
            float(row["line"]),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def main():
    if not API_KEY:
        raise RuntimeError("Missing API_FOOTBALL_KEY")

    now = datetime.now(timezone.utc)

    if STATE_PATH.exists():
        state = read_json(STATE_PATH)
        if state.get("schema_version") != 1:
            raise RuntimeError("Unsupported tracking schema")
    else:
        state = {
            "schema_version": 1,
            "started_at": now.isoformat(),
            "predictions": {},
        }

    ledger = state["predictions"]
    value = read_json(VALUE_PATH)
    model = value["model_version"]
    capture = parse_date(value["odds_captured_at"])

    if capture > now:
        raise RuntimeError("Snapshot timestamp is in the future")

    added = 0
    skipped = Counter()

    for row in value.get("results", []):
        kickoff = parse_date(row["match_date"])

        # Regjistrim vetëm për ndeshje që ende nuk kanë nisur.
        if kickoff <= now:
            skipped["already_started"] += 1
            continue

        # Nuk regjistrojmë snapshot më të vjetër se 12 orë.
        if (now - capture).total_seconds() > 12 * 3600:
            skipped["old_snapshot"] += 1
            continue

        key = prediction_key(model, row)
        if key in ledger:
            continue

        ledger[key] = {
            **row,
            "model_version": model,
            "registered_at": now.isoformat(),
            "snapshot_captured_at": capture.isoformat(),
            "stake_units": 1.0,
            "positive_ev_at_registration": row["model_ev_pct"] > 0,
            "tracking_status": "pending",
            "profit_units": None,
        }
        added += 1

    pending_ids = sorted({
        row["fixture_id"]
        for row in ledger.values()
        if row["tracking_status"] == "pending"
        and parse_date(row["match_date"]) <= now
    })

    settled = 0
    fetch_errors = {}

    for fixture_id in pending_ids:
        try:
            matches = api_get("/fixtures", {"id": fixture_id})
        except Exception as error:
            # Ruajmë gjendjen dhe riprovojmë në ekzekutimin tjetër.
            fetch_errors[str(fixture_id)] = str(error)
            continue

        if len(matches) != 1:
            fetch_errors[str(fixture_id)] = "Fixture unavailable"
            continue

        match = matches[0]
        status = match["fixture"]["status"]["short"]

        # Ndeshjet e shtyra/anuluara kërkojnë rregulla të veçanta.
        # Nuk i shpallim automatikisht fituese, humbëse ose void.
        if status != "FT":
            for row in ledger.values():
                if (
                    row["fixture_id"] == fixture_id
                    and row["tracking_status"] == "pending"
                ):
                    row["latest_fixture_status"] = status
            continue

        goals = match.get("goals") or {}
        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            continue

        total = home_goals + away_goals

        for row in ledger.values():
            if (
                row["fixture_id"] != fixture_id
                or row["tracking_status"] != "pending"
            ):
                continue

            line = float(row["line"])
            won = (
                total > line
                if row["selection"] == "Over"
                else total < line
            )

            row.update({
                "tracking_status": "settled",
                "settled_at": now.isoformat(),
                "latest_fixture_status": "FT",
                "home_goals": home_goals,
                "away_goals": away_goals,
                "won": won,
                "profit_units": (
                    float(row["odd"]) - 1 if won else -1.0
                ),
            })
            settled += 1

    summaries = {}

    for version in sorted({
        row["model_version"] for row in ledger.values()
    }):
        summaries[version] = {}

        for cohort in ("all", "positive_model_ev"):
            rows = [
                row for row in ledger.values()
                if row["model_version"] == version
                and (
                    cohort == "all"
                    or row["positive_ev_at_registration"]
                )
            ]
            finished = [
                row for row in rows
                if row["tracking_status"] == "settled"
            ]
            profit = sum(row["profit_units"] for row in finished)

            summaries[version][cohort] = {
                "registered_records": len(rows),
                "settled_records": len(finished),
                "settled_fixtures": len({
                    row["fixture_id"] for row in finished
                }),
                "profit_units": profit,
                "roi_pct": (
                    profit / len(finished) * 100
                    if finished else None
                ),
            }

    state.update({
        "updated_at": now.isoformat(),
        "summary": summaries,
        "fetch_errors": fetch_errors,
        "notes": [
            "Paper simulation only; no real bets are placed.",
            "First registered quote retained for each model and market.",
            "Bookmaker availability and execution are not verified.",
            "Multiple lines and bookmakers from one match are correlated.",
            "Aggregate ROI is not a one-pick-per-match strategy.",
            "Non-FT fixtures remain pending.",
        ],
    })

    STATE_PATH.parent.mkdir(exist_ok=True)

    with open(str(STATE_PATH) + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    Path(str(STATE_PATH) + ".tmp").replace(STATE_PATH)

    print("PREDICTION TRACKING - PAPER SIMULATION")
    print(f"New records: {added}")
    print(f"Newly settled records: {settled}")
    print(f"Total records: {len(ledger)}")
    print(f"Skipped: {dict(skipped)}")
    print(f"Result-fetch errors: {len(fetch_errors)}")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    print(f"SUCCESS: Saved {STATE_PATH}")


if __name__ == "__main__":
    main()
