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
SWISS_SOURCES = {
    "sfl.ch": "Swiss Football League", "srf.ch": "SRF Sport",
    "blick.ch": "Blick", "rsi.ch": "RSI Sport", "rtn.ch": "RTN",
}
GERMAN_SOURCES = dict(SOURCES)
SOURCES.update(SWISS_SOURCES)
TARGET = Path("data/value_news.json")

def source_config(league_id):
    if str(league_id) == "80":
        return GERMAN_SOURCES, [("de", "DE", "DE:de")]
    if str(league_id) in {"207", "208"}:
        return SWISS_SOURCES, [("de", "CH", "CH:de"), ("fr", "CH", "CH:fr"), ("it", "CH", "CH:it")]
    return {}, []


def normalize(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def team_matches(title, team):
    words = [w for w in normalize(team).split() if len(w) >= 4 and w not in {"dynamo", "borussia", "viktoria", "fortuna", "united"}]
    return bool(words) and any(w in normalize(title).split() for w in words)


def publisher_allowed(url, sources=None):
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in (SOURCES if sources is None else sources))


def parse_feed(payload, teams, now, sources=None):
    found = []
    for item in ET.fromstring(payload).findall("./channel/item"):
        title = item.findtext("title", "").strip()
        source = item.find("source")
        if source is None or not publisher_allowed(source.get("url", ""), sources):
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
    for fixture, row in list(matches.items())[:maximum]:
        sources, locales = source_config(row.get("league_id"))
        if not locales:
            continue
        teams = [row["home"], row["away"]]
        domains = " OR ".join("site:" + d for d in sources)
        query = f'("{teams[0]}" OR "{teams[1]}") ({domains}) when:7d'
        entry = {"status": "ok", "articles": [], "language_results": {}}
        for language, country, edition in locales:
            try:
                response = requests.get("https://news.google.com/rss/search",
                    params={"q": query, "hl": language, "gl": country, "ceid": edition}, timeout=20)
                response.raise_for_status()
                rows = parse_feed(response.content, teams, now, sources)
                entry["articles"].extend(rows)
                entry["language_results"][language] = "ok"
            except (requests.RequestException, ET.ParseError):
                entry["language_results"][language] = "fetch_failed"
        unique = {normalize(r["title"]): r for r in entry["articles"]}
        entry["articles"] = sorted(unique.values(), key=lambda r: r["published_at"], reverse=True)[:10]
        failed = list(entry["language_results"].values()).count("fetch_failed")
        if failed:
            entry["status"] = "fetch_failed" if failed == len(locales) else "partial_fetch"
        elif not entry["articles"]:
            entry["status"] = "no_matching_headlines"
        result["matches"][fixture] = entry
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print("News collection saved; matches:", len(result["matches"]))


if __name__ == "__main__":
    main()
