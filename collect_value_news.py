"""Collect dated publisher headlines for value candidates, not verified absences."""
import json
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests

SOURCES = {
    "liga3-online.de": "Liga3-online",
    "kicker.de": "Kicker",
    "sportschau.de": "Sportschau",
    "fupa.net": "FuPa",
    "nrz.de": "NRZ",
    "ndr.de": "NDR Sport",
    "mdr.de": "MDR Sport",
}
TARGET = Path("data/value_news.json")


def normalize(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def team_matches(title, team):
    words = [w for w in normalize(team).split() if len(w) >= 4 and w not in {"dynamo", "borussia", "viktoria", "fortuna", "united"}]
    return bool(words) and any(w in normalize(title).split() for w in words)


def publisher_allowed(url):
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in SOURCES)


def parse_feed(payload, teams, now):
    found = []
    for item in ET.fromstring(payload).findall("./channel/item"):
        title = item.findtext("title", "").strip()
        source = item.find("source")
        if source is None or not publisher_allowed(source.get("url", "")):
            continue
        try:
            published = parsedate_to_datetime(item.findtext("pubDate", "")).astimezone(timezone.utc)
        except (ValueError, TypeError, OverflowError):
            continue
        if not now - timedelta(days=7) <= published <= now:
            continue
        if not any(team_matches(title, team) for team in teams):
            continue
        found.append({"title": title, "source": source.text or "", "publisher_url": source.get("url"),
                      "url": item.findtext("link", ""), "published_at": published.isoformat(),
                      "evidence_type": "headline_only_unverified"})
    unique = {normalize(row["title"]): row for row in found}
    return sorted(unique.values(), key=lambda r: r["published_at"], reverse=True)[:10]


def main():
    data = json.loads(Path("data/value_analysis.json").read_text())
    minimum = float(os.getenv("AFC_VALUE_MIN_EV", "15"))
    min_odd = float(os.getenv("AFC_VALUE_MIN_ODD", "1.8"))
    maximum = max(1, min(int(os.getenv("AFC_VALUE_AI_MAX_MATCHES", "8")), 20))
    matches = {}
    for row in data.get("results", []):
        if float(row.get("model_ev_pct", -999)) >= minimum and float(row.get("odd", 0)) >= min_odd:
            matches.setdefault(str(row.get("fixture_id")), row)
    now = datetime.now(timezone.utc)
    result = {"generated_at": now.isoformat(), "odds_captured_at": data.get("odds_captured_at"),
              "sources": SOURCES, "matches": {}, "note": "Headlines only; no independently confirmed injuries or rotation."}
    domains = " OR ".join("site:" + d for d in SOURCES)
    for fixture, row in list(matches.items())[:maximum]:
        if str(row.get("league_id")) != "80":
            continue
        teams = [row["home"], row["away"]]
        query = f'("{teams[0]}" OR "{teams[1]}") ({domains}) when:7d'
        entry = {"status": "ok", "articles": []}
        try:
            response = requests.get("https://news.google.com/rss/search", params={"q": query, "hl": "de", "gl": "DE", "ceid": "DE:de"}, timeout=20)
            response.raise_for_status()
            entry["articles"] = parse_feed(response.content, teams, now)
            if not entry["articles"]:
                entry["status"] = "no_matching_headlines"
        except (requests.RequestException, ET.ParseError):
            entry["status"] = "fetch_failed"
        result["matches"][fixture] = entry
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print("News collection saved; matches:", len(result["matches"]))


if __name__ == "__main__":
    main()
