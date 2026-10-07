import os
import re
import time
import hashlib
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone

# ============================================================
# AFC EARLY INFO
# News-first football intelligence bot
#
# FLOW:
# SOURCE -> NEWS -> MATCH/TEAM -> IMPORTANCE -> TELEGRAM
#
# IMPORTANT:
# Odds movement is NOT required to trigger an alert.
# ============================================================


# =========================
# TELEGRAM CONFIG
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

if not TELEGRAM_CHAT_ID:
    raise RuntimeError("Missing TELEGRAM_CHAT_ID")


# =========================
# GENERAL CONFIG
# =========================

CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))

# Minimum score required to send an alert.
MIN_ALERT_SCORE = int(os.getenv("MIN_ALERT_SCORE", "5"))

# Avoid sending the same story repeatedly.
SEEN_FILE = "seen_news.txt"


# =========================
# LEAGUES
# Easy to expand later.
# =========================

LEAGUES = {
    "AFC Champions League Elite": {
        "enabled": True,
        "keywords": [
            "afc champions league elite",
            "acl elite",
        ],
    },

    "AFC Champions League Two": {
        "enabled": True,
        "keywords": [
            "afc champions league two",
            "acl two",
            "afc cup",
        ],
    },

    "Indonesia Liga 1": {
        "enabled": True,
        "keywords": [
            "liga 1 indonesia",
            "bri liga 1",
            "indonesia liga 1",
        ],
    },

    "Thailand League": {
        "enabled": True,
        "keywords": [
            "thai league",
            "thailand league",
            "thai league 1",
        ],
    },

    "Singapore Premier League": {
        "enabled": True,
        "keywords": [
            "singapore premier league",
            "spl singapore",
        ],
    },
}


# =========================
# NEWS SOURCES
#
# We will add verified local journalists,
# official clubs, federations and local media here.
# =========================

SOURCES = [
    # Example:
    #
    # {
    #     "name": "Source Name",
    #     "url": "https://example.com/rss",
    #     "type": "rss",
    #     "trust": 3,
    # }
]


# =========================
# HIGH IMPACT KEYWORDS
# =========================

CRITICAL_KEYWORDS = {
    # Major player availability
    "injured": 3,
    "injury": 3,
    "ruled out": 5,
    "out of squad": 5,
    "not in squad": 5,
    "will miss": 4,
    "unavailable": 3,

    # Suspensions / bans
    "suspended": 4,
    "suspension": 4,
    "banned": 4,

    # Starting XI / lineup
    "starting xi": 5,
    "starting lineup": 5,
    "line-up": 3,
    "lineup": 3,
    "benched": 4,
    "on the bench": 3,

    # Rotation
    "rotation": 3,
    "rotate": 3,
    "rested": 4,
    "rest players": 4,

    # Goalkeeper
    "goalkeeper injured": 5,
    "keeper injured": 5,
    "goalkeeper out": 5,

    # Travel / logistical problems
    "flight delayed": 4,
    "flight cancelled": 5,
    "travel problems": 4,
    "travel issue": 4,
    "visa problem": 5,
    "visa issue": 5,
    "stranded": 5,

    # Internal problems
    "unpaid salaries": 5,
    "salary dispute": 5,
    "players refused": 5,
    "boycott": 5,
    "strike": 5,

    # Coach information
    "coach confirmed": 3,
    "manager confirmed": 3,
    "coach said": 2,

    # Squad
    "squad announced": 3,
    "squad list": 3,
    "travelling squad": 4,
    "traveling squad": 4,
}


# =========================
# LOW VALUE / NOISE
# =========================

NOISE_KEYWORDS = [
    "happy birthday",
    "birthday",
    "merchandise",
    "ticket sale",
    "tickets available",
    "fan zone",
    "giveaway",
    "competition winner",
    "training photos",
    "photo gallery",
]
[07.10.2026 13:32] K.U.R.R DON: # =========================
# LANGUAGE SUPPORT
#
# Initial local-language terms.
# This can be expanded league by league.
# =========================

LOCAL_KEYWORDS = {
    # Indonesian
    "cedera": 3,
    "absen": 4,
    "skorsing": 4,
    "tidak bermain": 4,
    "tidak dibawa": 5,
    "rotasi": 3,

    # Malay
    "kecederaan": 3,
    "digantung": 4,
    "tidak bermain": 4,

    # General football terms often found in translated feeds
    "squad": 2,
    "injury": 3,
    "suspension": 4,
}


# =========================
# UTILITIES
# =========================

def normalize(text):
    if not text:
        return ""

    text = text.lower()
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def story_id(title, link):
    raw = f"{title}|{link}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_seen():

    if not os.path.exists(SEEN_FILE):
        return set()

    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())

    except Exception:
        return set()


def save_seen(news_id):

    try:
        with open(SEEN_FILE, "a", encoding="utf-8") as f:
            f.write(news_id + "\n")

    except Exception as exc:
        print("Could not save seen item:", exc)


# =========================
# LEAGUE DETECTION
# =========================

def detect_league(text):

    text = normalize(text)

    matches = []

    for league, config in LEAGUES.items():

        if not config["enabled"]:
            continue

        for keyword in config["keywords"]:

            if keyword in text:
                matches.append(league)
                break

    return matches


# =========================
# NEWS IMPORTANCE ENGINE
# =========================

def calculate_importance(title, description, source_trust=1):

    combined = normalize(f"{title} {description}")

    # Reject obvious noise.
    for word in NOISE_KEYWORDS:

        if word in combined:
            return 0, []

    score = 0
    reasons = []

    for keyword, points in CRITICAL_KEYWORDS.items():

        if keyword in combined:
            score += points
            reasons.append(keyword)

    for keyword, points in LOCAL_KEYWORDS.items():

        if keyword in combined:
            score += points

            if keyword not in reasons:
                reasons.append(keyword)

    # Trusted local journalist / official source bonus.
    if source_trust >= 3:
        score += 2

    elif source_trust == 2:
        score += 1

    return score, reasons


# =========================
# TELEGRAM
# =========================

def send_telegram(message):

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        response.raise_for_status()

        return True

    except Exception as exc:

        print("Telegram error:", exc)

        return False


# =========================
# ALERT FORMAT
# =========================

def build_alert(
    source_name,
    title,
    description,
    link,
    score,
    reasons,
    leagues,
):

    league_text = (
        ", ".join(leagues)
        if leagues
        else "League/team detection pending"
    )

    reason_text = (
        ", ".join(reasons[:6])
        if reasons
        else "High-trust source"
    )

    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    return (
        "🚨 AFC EARLY INFO\n\n"
        f"🏆 {league_text}\n\n"
        f"📰 {title}\n\n"
[07.10.2026 13:32] K.U.R.R DON: f"📍 Source: {source_name}\n"
        f"⚡ Importance: {score}/10+\n"
        f"🔎 Trigger: {reason_text}\n"
        f"🕐 Detected: {now}\n\n"
        f"{description[:600]}\n\n"
        f"🔗 {link}\n\n"
        "⚠️ EARLY INFORMATION\n"
        "Odds movement is NOT required for this alert."
    )


# =========================
# PROCESS STORY
# =========================

def process_story(
    source_name,
    source_trust,
    title,
    description,
    link,
    seen,
):

    news_id = story_id(title, link)

    if news_id in seen:
        return

    combined = f"{title} {description}"

    leagues = detect_league(combined)

    score, reasons = calculate_importance(
        title,
        description,
        source_trust,
    )

    print(
        f"[NEWS] {source_name} | "
        f"score={score} | {title}"
    )

    if score < MIN_ALERT_SCORE:
        return

    alert = build_alert(
        source_name,
        title,
        description,
        link,
        score,
        reasons,
        leagues,
    )

    if send_telegram(alert):

        seen.add(news_id)

        save_seen(news_id)

        print("ALERT SENT")


# =========================
# RSS MONITOR
# =========================

def check_rss_source(source, seen):

    feed = feedparser.parse(source["url"])

    for entry in feed.entries[:20]:

        title = entry.get("title", "")

        description = entry.get(
            "summary",
            entry.get("description", ""),
        )

        link = entry.get("link", "")

        process_story(
            source["name"],
            source.get("trust", 1),
            title,
            description,
            link,
            seen,
        )

# =========================
# WEB PAGE MONITOR
# =========================

def check_web_source(source, seen):

    headers = {
        "User-Agent": "Mozilla/5.0 AFC-Early-Info/1.0"
    }

    response = requests.get(
        source["url"],
        headers=headers,
        timeout=20,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    links = soup.find_all("a", href=True)

    for item in links[:100]:

        title = item.get_text(
            " ",
            strip=True,
        )

        if not title or len(title) < 15:
            continue

        link = item["href"]

        if link.startswith("/"):
            from urllib.parse import urljoin
            link = urljoin(source["url"], link)

        process_story(
            source["name"],
            source.get("trust", 1),
            title,
            "",
            link,
            seen,
        )


# =========================
# CHECK ALL SOURCES
# =========================

def check_sources(seen):

    for source in SOURCES:

        try:

            if source["type"] == "rss":

                check_rss_source(
                    source,
                    seen,
                )

elif source["type"] == "web":

    check_web_source(
        source,
        seen,
    )        

        except Exception as exc:

            print(
                f"Source error "
                f"{source.get('name')}: {exc}"
            )


# =========================
# STARTUP TEST
# =========================

def startup_message():

    message = (
        "🟢 AFC EARLY INFO BOT ONLINE\n\n"
        "News-first monitoring active.\n"
        "Odds movement is NOT required "
        "to trigger an alert."
    )

    send_telegram(message)


# =========================
# MAIN
# =========================

def main():

    print("AFC EARLY INFO starting...")

    seen = load_seen()

    startup_message()

    while True:

        try:

            check_sources(seen)

        except Exception as exc:

            print("Main loop error:", exc)

        time.sleep(CHECK_INTERVAL)


if name == "main":
    main()
