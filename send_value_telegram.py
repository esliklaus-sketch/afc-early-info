import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from value_model import parse_date, read_json

STATE_PATH = Path("data/prediction_tracking.json")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_VALUE_CHAT_ID")
MIN_EV = float(os.getenv("AFC_VALUE_MIN_EV", "15"))
MIN_ODD = float(os.getenv("AFC_VALUE_MIN_ODD", "1.8"))


def save_state(state):
    temporary = Path(str(STATE_PATH) + ".tmp")
    with open(temporary, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    temporary.replace(STATE_PATH)


def send_message(text):
    # Nuk afishojmë URL-në: ajo përmban token-in.
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
    except requests.RequestException:
        raise RuntimeError(
            "Telegram connection error; delivery may be uncertain"
        ) from None

    try:
        data = response.json()
    except ValueError:
        raise RuntimeError(
            "Telegram returned an unreadable response"
        ) from None

    if response.status_code != 200 or not data.get("ok"):
        raise RuntimeError(
            f"Telegram rejected request: "
            f"{data.get('error_code', response.status_code)} "
            f"{data.get('description', 'Unknown error')}"
        )

    return data["result"]["message_id"]


def deliver(state, entry, status_field, text):
    # Ruajmë tentativën para dërgimit për të shmangur
    # ridërgimin automatik pas një përgjigjeje të paqartë.
    entry[status_field] = "sending"
    save_state(state)

    try:
        message_id = send_message(text)
    except RuntimeError:
        entry[status_field] = "needs_review"
        save_state(state)
        raise

    entry[status_field] = "sent"
    entry[status_field + "_message_id"] = message_id
    save_state(state)


def main():
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("Missing Telegram token or value chat ID")

    if not STATE_PATH.exists():
        raise RuntimeError("Run prediction tracking first")

    state = read_json(STATE_PATH)
    value = read_json("data/value_analysis.json")
    reviews = {}
    review_path = Path("data/value_ai_review.json")
    if review_path.exists():
        review_data = read_json(review_path)
        if (review_data.get("odds_captured_at") == value.get("odds_captured_at")
                and review_data.get("model_version") == value.get("model_version")):
            reviews = {str(r["fixture_id"]): r for r in review_data.get("candidates", [])}
    now = datetime.now(timezone.utc)
    captured = parse_date(value["odds_captured_at"])

    telegram = state.setdefault("telegram_value", {})
    # Gjendje e veçantë për secilin kanal.
    channel = telegram.setdefault(CHAT_ID, {"fixtures": {}})
    sent_fixtures = channel["fixtures"]

    grouped = {}

    if 0 <= (now - captured).total_seconds() <= 3600:
        for row in value.get("results", []):
            if parse_date(row["match_date"]) <= now:
                continue
            if float(row["model_ev_pct"]) < MIN_EV or float(row["odd"]) < MIN_ODD:
                continue

            fixture_key = (
                f"{value['model_version']}:"
                f"{row['league_id']}:{row['fixture_id']}"
            )

            if fixture_key in sent_fixtures:
                continue

            selections = grouped.setdefault(fixture_key, {})
            selection_key = (row["selection"], float(row["line"]))
            old = selections.get(selection_key)

            if old is None or float(row["odd"]) > float(old["odd"]):
                selections[selection_key] = row
    else:
        print("Snapshot older than one hour; new alerts skipped")

    new_messages = 0

    for fixture_key, selections in grouped.items():
        picks = sorted(
            selections.values(),
            key=lambda row: (float(row["line"]), row["selection"]),
        )
        first = picks[0]
        kickoff = parse_date(first["match_date"]).astimezone(
            ZoneInfo("Europe/Berlin")
        )
        capture_local = captured.astimezone(ZoneInfo("Europe/Berlin"))

        lines = [
            "🧪 AFC VALUE TEST",
            f"{first['home']} – {first['away']}",
            f"Liga: {first['league']}",
            f"Nisja: {kickoff:%d/%m %H:%M} (Berlin)",
            "",
        ]

        for pick in picks:
            lines.append(
                f"{pick['selection']} {pick['line']} "
                f"@ {pick['odd']} — {pick['bookmaker']}\n"
                f"P: {pick['model_probability']:.1%} | "
                f"Fair: {pick['fair_odd']:.2f} | "
                f"EV modeli: {pick['model_ev_pct']:+.1f}%"
            )

        review = reviews.get(str(first["fixture_id"]))
        if review and review.get("ai_review"):
            lines.extend([
                "",
                f"🤖 AI — {review['selection']} {review['line']}:",
                str(review["ai_review"])[:1200],
                "AI shqyrton statistikat; lajmet dhe mungesat nuk janë verifikuar.",
            ])
        else:
            lines.extend(["", "AI: pa analizë për këtë ndeshje."])

        lines.extend([
            "",
            f"Kuotat u morën: {capture_local:%d/%m %H:%M} (Berlin)",
            "Kuotat e kompanisë mund të kenë ndryshuar.",
            "Model eksperimental — value ende e paverifikuar.",
            "Simulim: 1 njësi për linjë; linjat janë të lidhura.",
        ])

        entry = {
            "fixture_id": first["fixture_id"],
            "league_id": first["league_id"],
            "home": first["home"],
            "away": first["away"],
            "registered_at": now.isoformat(),
            "picks": picks,
        }
        sent_fixtures[fixture_key] = entry
        deliver(state, entry, "alert_status", "\n".join(lines))
        new_messages += 1

    # Marrim rezultatet që kontrolloi track_predictions.py.
    completed = {
        (row["league_id"], row["fixture_id"]): row
        for row in state["predictions"].values()
        if row.get("tracking_status") == "settled"
    }

    result_messages = 0

    for entry in sent_fixtures.values():
        if entry.get("alert_status") != "sent":
            continue
        if entry.get("result_status"):
            continue

        result = completed.get(
            (entry["league_id"], entry["fixture_id"])
        )
        if result is None:
            continue

        total = result["home_goals"] + result["away_goals"]
        profit = 0.0
        lines = [
            "🧪 AFC VALUE TEST — REZULTATI",
            f"{entry['home']} – {entry['away']}",
            f"Rezultati: {result['home_goals']}–{result['away_goals']}",
            "",
        ]

        for pick in entry["picks"]:
            won = (
                total > float(pick["line"])
                if pick["selection"] == "Over"
                else total < float(pick["line"])
            )
            pnl = float(pick["odd"]) - 1 if won else -1.0
            profit += pnl
            lines.append(
                f"{'✅' if won else '❌'} "
                f"{pick['selection']} {pick['line']} "
                f"@ {pick['odd']}: {pnl:+.2f} njësi"
            )

        entry["simulation_profit_units"] = profit
        lines.extend([
            "",
            f"Totali në simulim: {profit:+.2f} njësi",
            "Përllogaritur me kuotat e mesazhit fillestar.",
        ])

        deliver(state, entry, "result_status", "\n".join(lines))
        result_messages += 1

    save_state(state)
    print(f"New Telegram match messages: {new_messages}")
    print(f"New Telegram result messages: {result_messages}")
    print(
        "No automatic resend for sending/needs_review entries; "
        "check channel before resolving uncertain delivery."
    )
    print("SUCCESS: Telegram state saved in prediction history")


if __name__ == "__main__":
    main()
