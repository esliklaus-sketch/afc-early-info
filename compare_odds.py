"""Compare two AFC odds snapshots (JSON files or GitHub Actions ZIP artifacts).

Usage:
    python compare_odds.py older.json newer.json
    python compare_odds.py "odds-snapshot (1).zip" "odds-snapshot (2).zip"
    python compare_odds.py older.zip newer.zip --min-change 20

Only compares matching fixture, bookmaker, market, selection, and line.
"""
import argparse
import json
import zipfile
from pathlib import Path


def load_snapshot(path):
    path = Path(path)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            candidates = sorted(n for n in archive.namelist() if n.lower().endswith(".json") and not n.endswith("/"))
            if len(candidates) != 1:
                raise ValueError(f"Expected exactly one JSON file in {path}, found {len(candidates)}")
            with archive.open(candidates[0]) as stream:
                data = json.load(stream)
    else:
        with path.open(encoding="utf-8") as stream:
            data = json.load(stream)
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise ValueError(f"Invalid odds snapshot: {path}")
    return data


def key(record):
    return (
        str(record["fixture_id"]),
        str(record["bookmaker"]),
        str(record["market"]),
        str(record["selection"]),
        str(record["line"]),
    )


def indexed(snapshot):
    result = {}
    for record in snapshot["records"]:
        try:
            price = float(record["odd"])
            if price <= 0:
                continue
            identity = key(record)
        except (KeyError, TypeError, ValueError):
            continue
        result[identity] = (record, price)
    return result


def compare(old, new):
    old_items, new_items = indexed(old), indexed(new)
    changes = []
    for identity in old_items.keys() & new_items.keys():
        old_record, old_price = old_items[identity]
        new_record, new_price = new_items[identity]
        if old_price == new_price:
            continue
        changes.append({
            "fixture_id": new_record["fixture_id"],
            "league": new_record.get("league", ""),
            "home": new_record.get("home", ""),
            "away": new_record.get("away", ""),
            "bookmaker": new_record["bookmaker"],
            "market": new_record["market"],
            "selection": new_record["selection"],
            "line": new_record["line"],
            "old_odd": old_price,
            "new_odd": new_price,
            "change_pct": round((new_price / old_price - 1) * 100, 2),
        })
    changes.sort(key=lambda item: abs(item["change_pct"]), reverse=True)
    return changes, len(old_items.keys() & new_items.keys()), len(new_items.keys() - old_items.keys())


def main():
    parser = argparse.ArgumentParser(description="Compare AFC odds snapshots")
    parser.add_argument("older", help="Earlier JSON or ZIP snapshot")
    parser.add_argument("newer", help="Later JSON or ZIP snapshot")
    parser.add_argument("--min-change", type=float, default=0, help="Minimum absolute percentage change to display")
    args = parser.parse_args()
    old, new = load_snapshot(args.older), load_snapshot(args.newer)
    changes, matched, added = compare(old, new)
    print("AFC EARLY INFO - ODDS COMPARISON")
    print(f"Earlier snapshot: {old.get('captured_at', 'unknown')}")
    print(f"Later snapshot:   {new.get('captured_at', 'unknown')}")
    print(f"Matched odds: {matched} | New entries: {added} | Changed odds: {len(changes)}")
    shown = [c for c in changes if abs(c["change_pct"]) >= args.min_change]
    for c in shown:
        print(f"{c['league']} | {c['home']} vs {c['away']} | {c['bookmaker']} | "
              f"{c['selection']} {c['line']} | {c['old_odd']:.2f} -> {c['new_odd']:.2f} "
              f"({c['change_pct']:+.2f}%)")
    if not shown:
        print("No changes above the selected threshold.")


if __name__ == "__main__":
    main()
