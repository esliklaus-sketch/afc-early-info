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

    # =========================================================
    # AFC - OFFICIAL COMPETITIONS
    # =========================================================

    {
        "name": "AFC Champions League Elite",
        "url": "https://www.the-afc.com/en/club/afc_champions_league_elite.html",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "AFC Champions League Two",
        "url": "https://www.the-afc.com/en/club/afc_champions_league_two.html",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "AFC Challenge League",
        "url": "https://www.the-afc.com/en/club/afc_challenge_league.html",
        "type": "web",
        "trust": 3,
    },

    # =========================================================
    # ASEAN / SHOPEE CUP
    # =========================================================

    {
        "name": "ASEAN United FC - Shopee Cup",
        "url": "https://aseanutdfc.com/asean-club-championship",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "ASEAN Football Federation",
        "url": "https://www.aseanfootball.org/v3/",
        "type": "web",
        "trust": 3,
    },

    # =========================================================
    # MALAYSIA - JDT + LOCAL EARLY INFO
    # =========================================================

    {
        "name": "Johor Darul Tazim Official",
        "url": "https://johorsoutherntigers.my/",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "MakanBola Malaysia",
        "url": "https://makanbola.com/",
        "type": "web",
        "trust": 2,
    },

    {
        "name": "RTM Sukan Malaysia",
        "url": "https://berita.rtm.gov.my/arena",
        "type": "web",
        "trust": 2,
    },

    {
        "name": "Utusan Sukan Malaysia",
        "url": "https://www.utusan.com.my/category/sukan/",
        "type": "web",
        "trust": 2,
    },

    # =========================================================
    # INDONESIA - PERSIB / LIGA 1
    # =========================================================

    {
        "name": "Persib Bandung Official",
        "url": "https://persib.co.id/",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "Detik Jabar Persib",
        "url": "https://www.detik.com/jabar/sepakbola",
        "type": "web",
        "trust": 2,
    },

    {
        "name": "BolaSport Indonesia",
        "url": "https://www.bolasport.com/",
        "type": "web",
        "trust": 2,
    },

    # =========================================================
    # SINGAPORE - LION CITY SAILORS
    # =========================================================

    {
        "name": "Lion City Sailors Official",
        "url": "https://www.lioncitysailorsfc.sg/",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "Football Association Singapore",
        "url": "https://www.fas.org.sg/",
        "type": "web",
        "trust": 3,
    },

    # =========================================================
    # VIETNAM
    # =========================================================

    {
        "name": "Vietnam Football Federation",
        "url": "https://vff.org.vn/",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "Vietnam Football",
        "url": "https://vietnamnet.vn/en/sports",
        "type": "web",
        "trust": 2,
    },

    # =========================================================
    # THAILAND
    # =========================================================

    {
        "name": "Thai League Official",
        "url": "https://thaileague.co.th/",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "Football Association Thailand",
        "url": "https://fathailand.org/",
        "type": "web",
        "trust": 3,
    },

    # =========================================================
    # AUSTRALIA
    # =========================================================

    {
        "name": "A-Leagues Australia",
        "url": "https://aleagues.com.au/",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "Football Australia",
        "url": "https://www.footballaustralia.com.au/",
        "type": "web",
        "trust": 3,
    },

    # =========================================================
    # JAPAN
    # =========================================================

    {
        "name": "J League Official",
        "url": "https://www.jleague.jp/en/",
        "type": "web",
        "trust": 3,
    },

    # =========================================================
    # SOUTH KOREA
    # =========================================================

    {
        "name": "K League Official",
        "url": "https://www.kleague.com/",
        "type": "web",
        "trust": 3,
    },

    # =========================================================
    # SAUDI ARABIA
    # =========================================================

    {
        "name": "Saudi Pro League",
        "url": "https://www.spl.com.sa/",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "Arriyadiyah Saudi",
        "url": "https://arriyadiyah.com/",
        "type": "web",
        "trust": 2,
    },

    # =========================================================
    # QATAR
    # =========================================================

    {
        "name": "Qatar Stars League",
        "url": "https://www.qsl.qa/en",
        "type": "web",
        "trust": 3,
    },

    # =========================================================
    # UAE
    # =========================================================

    {
        "name": "UAE Pro League",
        "url": "https://www.uaeproleague.ae/",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "UAE Football Association",
        "url": "https://www.uaefa.ae/",
        "type": "web",
        "trust": 3,
    },

    # =========================================================
    # IRAQ
    # =========================================================

    {
        "name": "Iraq Football Association",
        "url": "https://ifa.iq/",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "Shafaq Iraq Sports",
        "url": "https://shafaq.com/en/Sports",
        "type": "web",
        "trust": 2,
    },

    # =========================================================
    # KUWAIT
    # =========================================================

    {
        "name": "Kuwait Football Association",
        "url": "https://kfa.org.kw/",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "Al Rai Kuwait Sports",
        "url": "https://www.alraimedia.com/",
        "type": "web",
        "trust": 2,
    },

    # =========================================================
    # EGYPT
    # =========================================================

    {
        "name": "Egyptian Football Association",
        "url": "https://www.efa.com.eg/",
        "type": "web",
        "trust": 3,
    },

    {
        "name": "Ahram Sports Egypt",
        "url": "https://english.ahram.org.eg/Category/6/Sports.aspx",
        "type": "web",
        "trust": 2,
    },

    # =========================================================
    # INDIA
    # =========================================================

    {
        "name": "AIFF India",
        "url": "https://www.the-aiff.com/",
        "type": "web",
        "trust": 3,
    },

    # =========================================================
    # IRAN
    # =========================================================

    {
        "name": "Iran Football Federation",
        "url": "https://ffiri.ir/",
        "type": "web",
        "trust": 3,
    },

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
    "photo gallery",]
# =========================
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
        f"📍 Source: {source_name}\n"
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


    try:

        check_sources(seen)

    except Exception as exc:

        print("Main loop error:", exc)




if __name__ == "__main__":
    main()
