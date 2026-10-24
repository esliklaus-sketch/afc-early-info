"""Optional AI review of AFC Value candidates. Never changes EV or places bets."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path("data/value_analysis.json")
TARGET = Path("data/value_ai_review.json")
MIN_EV = float(os.getenv("AFC_VALUE_MIN_EV", "15"))
MIN_ODD = float(os.getenv("AFC_VALUE_MIN_ODD", "1.8"))
MAX_MATCHES = max(1, min(int(os.getenv("AFC_VALUE_AI_MAX_MATCHES", "8")), 20))


def main():
    if not SOURCE.exists():
        raise SystemExit("Run value_model.py first")
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = [
        r for r in data.get("results", [])
        if float(r.get("model_ev_pct", -999)) >= MIN_EV
        and float(r.get("odd", 0)) >= MIN_ODD
    ]
    # One candidate per match to avoid paying for correlated lines.
    matches = {}
    for row in rows:
        key = str(row.get("fixture_id"))
        if key not in matches:
            matches[key] = row
    selected = list(matches.values())[:MAX_MATCHES]
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_status": data.get("status"),
        "odds_captured_at": data.get("odds_captured_at"),
        "model_version": data.get("model_version"),
        "min_model_ev_pct": MIN_EV,
        "min_odd": MIN_ODD,
        "candidates": [],
        "note": "AI review is not evidence of profitable value. No news is verified unless supplied.",
    }
    key = os.getenv("OPENAI_API_KEY")
    if selected and not key:
        result["status"] = "missing_key"
        print("AI skipped: configure OPENAI_API_KEY repository secret")
        selected = []
    if selected:
        from openai import OpenAI
        client = OpenAI(api_key=key, timeout=35.0, max_retries=1)
        for row in selected:
            evidence = {
                k: row.get(k) for k in (
                    "league", "home", "away", "match_date", "selection",
                    "line", "odd", "model_probability", "model_ev_pct",
                    "expected_total_goals", "bookmaker"
                )
            }
            response = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                temperature=0,
                max_tokens=450,
                messages=[
                    {"role": "system", "content": (
                        "You audit experimental football value-model candidates. "
                        "Reply in Albanian, concise. Use only supplied facts. "
                        "Do not invent injuries, lineups, travel, news or bookmaker moves. "
                        "Separate verified data, model assumptions, and missing evidence. "
                        "Explain risks and checks needed. Never recommend placing a bet "
                        "or claim EV is validated."
                    )},
                    {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
                ],
            )
            result["candidates"].append({
                "fixture_id": row.get("fixture_id"),
                "selection": row.get("selection"),
                "line": row.get("line"),
                "model_ev_pct": row.get("model_ev_pct"),
                "ai_review": response.choices[0].message.content or "",
            })
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("AFC Value AI review saved:", TARGET, "candidates:", len(result["candidates"]))


if __name__ == "__main__":
    main()
