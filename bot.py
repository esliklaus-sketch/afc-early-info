import os
import re
import time
import hashlib
import requests
import feedparser
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from urllib.parse import quote_plus
from afc_social_press import check_afc_social_press
from intelligence_engine import analyze_match

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
    "AFC Challenge League": {"enabled": True, "keywords": ["afc challenge league", "liga tantangan afc", "دوري التحدي", "лига вызова"]},
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

AI_CALLS_THIS_RUN = 0

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

    # AI remains disabled unless explicitly enabled in the workflow.
    # Per-run cap is NOT a monthly spending limit.
    ai_enabled = os.getenv("AI_ENABLED", "false").lower() == "true"
    ai_min_score = int(os.getenv("AI_MIN_SCORE", "9"))
    if ai_enabled and score >= ai_min_score and os.getenv("OPENAI_API_KEY"):
        global AI_CALLS_THIS_RUN
        ai_limit = max(0, int(os.getenv("AI_MAX_CALLS_PER_RUN", "1")))
        if AI_CALLS_THIS_RUN < ai_limit:
            AI_CALLS_THIS_RUN += 1
            evidence = (
                f"Burimi: {source_name}\nTitulli: {title}\n"
                f"Pershkrimi: {description}\nLinku: {link}\n"
                "Vetem keto te dhena jane verifikuar si te disponueshme. "
                "Mos supozo se linku eshte lexuar."
            )
            ai_result = analyze_match(
                "Vlereso rendesine e ketij lajmi per ndeshjet e ardhshme. "
                "Dallo faktet, pasigurite dhe verifikimet e nevojshme.",
                evidence=evidence,
            )
            if ai_result and not ai_result.startswith(("Gabim:", "Analiza AI deshtoi")):
                description = (description[:350] + "\n\nAI (bazuar vetem ne kete lajm):\n" + ai_result[:1200])

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



# ============================================================
# TELEGRAM: KERKIM ME KERKESE (pa prag score)
# P.sh.: /analizo Paro vs Asai, ose "Shiko Paro - Asai"
# Mesazhet lexohen kur ekzekutohet GitHub Actions; jo ne kohe reale.
# ============================================================

def telegram_api(method, payload=None):
    response = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}",
        json=payload or {}, timeout=20,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram {method} returned an error")
    return result.get("result")


def reply_to_chat(chat_id, text):
    # Telegram accepts at most 4096 characters per message.
    for start in range(0, len(text), 3500):
        telegram_api("sendMessage", {
            "chat_id": chat_id, "text": text[start:start + 3500],
            "disable_web_page_preview": True,
        })


def requested_match(message):
    text = (message or "").strip()
    if not text:
        return None
    if text.lower().startswith("/start") or text.lower().startswith("/help"):
        return "__HELP__"
    match = re.match(r"^/(?:analizo|analyzo|analizoje|shiko)(?:@\w+)?\s+(.+)$", text, re.I | re.S)
    if match:
        return match.group(1).strip()[:120]
    match = re.match(r"^(?:me\s+analizo|më\s+analizo|me\s+analizoje|analizo|analyzo|analizoje|shiko|kerko|kërko|me\s+shif|më\s+shif|kontrollo)\s+(.+)$", text, re.I | re.S)
    if match:
        return match.group(1).strip()[:120]
    if not text.startswith("/") and 2 <= len(text) <= 80 and len(text.split()) <= 7:
        return text
    return None


def research_news(match_name):
    """Search regional football news in local languages; RSS is not verified reporting."""
    from datetime import datetime, timezone
    from email.utils import parsedate_to_datetime
    from concurrent.futures import ThreadPoolExecutor, as_completed

    teams = [x.strip() for x in re.split(r"\\s+(?:vs?\\.?|versus)\\s+|\\s*[-–—]\\s*", match_name, maxsplit=1, flags=re.I) if x.strip()]
    subjects = teams if len(teams) == 2 else [match_name]

    # Local-script aliases and region/language pairs. Expand as leagues are added.
    aliases = {
        "ittihad aleppo": ["Al Ittihad Aleppo", "Al-Ittihad SC Aleppo", "الاتحاد الحلبي", "نادي الاتحاد الحلبي", "أهلي حلب"],
        "al ittihad aleppo": ["الاتحاد الحلبي", "أهلي حلب"],
        "goa fc": ["FC Goa", "एफसी गोवा", "एफ सी गोवा", "एफसी गोवा फुटबॉल"],
        "fc goa": ["एफसी गोवा", "एफ सी गोवा"],
        "paro": ["Paro FC", "بارو"],
        "paro fc": ["Paro FC", "بارو"],
        "al qadsia": ["Al Qadsiah", "Al Qadisiya", "القادسية"],
        "al qadisa": ["Al Qadsiah", "Al Qadisiya", "القادسية"],
        "al qadsiah": ["Al Qadisiya", "القادسية"],
    }
    regional = {
        "ittihad aleppo": [("ar", "SA"), ("ar", "EG"), ("en", "US")],
        "al ittihad aleppo": [("ar", "SA"), ("en", "US")],
        "goa fc": [("en", "IN"), ("hi", "IN"), ("en", "US")],
        "fc goa": [("en", "IN"), ("hi", "IN")],
        "paro": [("en", "IN"), ("en", "US")],
        "paro fc": [("en", "IN"), ("en", "US")],
    }
    # Cover all major regional search languages without forcing every language
    # onto every team; unrelated translations cause false positives.
    default_regions = [
        ("en", "US"), ("ar", "SA"), ("hi", "IN"), ("bn", "BD"),
        ("id", "ID"), ("ms", "MY"), ("th", "TH"), ("vi", "VN"),
        ("zh-CN", "CN"), ("ja", "JP"), ("ko", "KR"), ("fa", "IR"),
        ("fr", "FR"), ("pt", "BR"), ("ru", "RU"), ("tr", "TR"),
    ]
    plans = []
    if len(subjects) == 2:
        plans.append((f'"{subjects[0]}" "{subjects[1]}" football', "en", "US"))
    for team in subjects:
        key = team.casefold().strip()
        variants = list(dict.fromkeys([team] + aliases.get(key, [])))
        regions = regional.get(key, default_regions)
        for i, variant in enumerate(variants[:5]):
            lang, country = regions[min(i, len(regions) - 1)]
            plans.append((f'"{variant}"', lang, country))
            if i == 0:
                for lang2, country2 in regions[:5]:
                    plans.append((f'"{variant}" football', lang2, country2))
        for lang, country in regions[:2]:
            plans.append((f'"{team}" coach OR injury OR squad OR travel', lang, country))
    plans = list(dict.fromkeys(plans))[:24]

    def clean(value):
        return BeautifulSoup(value or "", "html.parser").get_text(" ", strip=True)

    variants = [normalize(v) for t in subjects for v in ([t] + aliases.get(t.casefold().strip(), []))]
    variants = [v for v in variants if len(v) >= 4]
    def relevant(title, summary):
        haystack = normalize(title + " " + summary)
        return any(v in haystack for v in variants)

    def fetch(plan):
        term, lang, country = plan
        url = (f"https://news.google.com/rss/search?q={quote_plus(term + ' when:7d')}"
               f"&hl={lang}-{country}&gl={country}&ceid={country}:{lang}")
        response = requests.get(url, timeout=9, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return feedparser.parse(response.content).entries[:15]

    articles, seen_titles, failures = [], set(), 0
    # Parallel RSS requests keep multilingual coverage from blocking Telegram.
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch, plan) for plan in plans]
        for future in as_completed(futures):
            try:
                entries = future.result()
                for item in entries:
                    title, summary = clean(item.get("title")), clean(item.get("summary"))
                    link = item.get("link", "")
                    if not title or not link or not relevant(title, summary):
                        continue
                    pub = item.get("published", "")
                    try:
                        published_at = parsedate_to_datetime(pub).astimezone(timezone.utc)
                        if (datetime.now(timezone.utc) - published_at).days > 7:
                            continue
                    except (ValueError, TypeError, OverflowError):
                        pass
                    headline = re.sub(r"\\s+-\\s+[^-]{2,55}$", "", title).strip()
                    key = re.sub(r"[^\\w]+", " ", normalize(headline))[:110]
                    if key in seen_titles:
                        continue
                    seen_titles.add(key)
                    source = clean(item.get("source", {}).get("title", "")) if isinstance(item.get("source"), dict) else ""
                    articles.append({"title": title[:250], "summary": summary[:450],
                                     "date": pub[:65] or "date e papërcaktuar",
                                     "source": source or "Google News RSS", "url": link})
            except Exception as exc:
                failures += 1
                print("[REQUEST] regional search failed:", type(exc).__name__)
    # Prefer recent, relevant reporting over arbitrary search completion order.
    def article_date(a):
        try:
            return parsedate_to_datetime(a["date"]).timestamp()
        except (ValueError, TypeError, OverflowError):
            return 0
    articles.sort(key=article_date, reverse=True)
    print(f"[REQUEST] MULTILINGUAL queries={len(plans)} relevant={len(articles)} failures={failures}")
    return articles[:10], failures


def investigate_match(match_name, chat_id):
    global AI_CALLS_THIS_RUN
    if os.getenv("AI_ENABLED", "false").lower() != "true" or not os.getenv("OPENAI_API_KEY"):
        reply_to_chat(chat_id, "AI nuk eshte aktiv ose mungon OPENAI_API_KEY ne workflow.")
        return True
    cap = max(0, int(os.getenv("AI_MAX_CALLS_PER_RUN", "1")))
    if AI_CALLS_THIS_RUN >= cap:
        reply_to_chat(chat_id, "Limiti i analizave per kete ekzekutim u arrit. Provo ne ekzekutimin tjeter.")
        return False
    articles, failures = research_news(match_name)
    if not articles:
        print("[REQUEST] NO_RELEVANT_EVIDENCE; AI not called")
        reply_to_chat(chat_id, (
            f"🔎 {match_name}\nNuk gjeta lajme te perdorshme ne kerkimin 7-ditor. "
            "Nuk mund te konfirmoj mungesa, udhetime ose levizje kuotash. "
            + ("Disa kerkime deshtuan teknikisht." if failures else "")
        ))
        return True
    evidence = "\n\n".join(
        f"{i}. {a['title']} | {a['source']} | {a['date']}\n{a['summary']}\n{a['url']}"
        for i, a in enumerate(articles, 1)
    )
    AI_CALLS_THIS_RUN += 1
    print(f"[REQUEST] AI_CALL match={match_name[:70]} articles={len(articles)}")
    analysis = analyze_match(
        "Analizo ndeshjen '" + match_name + "' perpara ndeshjes. "
        "Jep lajmet me rendesi, mungesat e reja kundrejt te vjetrave, udhetimin, "
        "deklaratat, motivimin dhe arsyet e mundshme te levizjes se kuotave. "
        "Per cdo pohim trego burimin dhe daten. Mos shpik formacione, mungesa, "
        "statistika ose kuota. Kemi vetem tituj dhe permbledhje nga RSS, "
        "jo verifikim te artikujve. Thuaj shprehimisht cfare nuk dihet. "
        "Pergjigju ne shqip, shkurt dhe me renditje prioriteti.",
        evidence=evidence[:11500],
    )
    if not analysis or analysis.startswith(("Gabim:", "Analiza AI deshtoi")):
        reply_to_chat(chat_id, "Analiza AI deshtoi. Kontrollo log-un [REQUEST].")
        return True
    links = "\n".join(f"{i}. {a['title'][:85]} ({a['date']})\n{a['url']}" for i, a in enumerate(articles[:5], 1))
    reply_to_chat(chat_id, (
        f"🔎 AFC INTELLIGENCE | {match_name}\n\n{analysis}\n\n"
        f"BURIMET E KERKIMIT (tituj RSS; artikujt nuk jane verifikuar plotesisht):\n{links}\n\n"
        "⚠️ Kuotat dhe formacionet nuk kontrollohen automatikisht ne kete version."
    ))
    print("[REQUEST] AI_REPLY_SENT")
    return True


def check_telegram_requests():
    # getUpdates offset i konfirmuar nga Telegram ruan gjendjen mes GitHub runs.
    # Nuk kerkon skedar offset ne GitHub. Duhet te mos kete webhook aktiv.
    try:
        updates = telegram_api("getUpdates", {"timeout": 0, "limit": 30, "allowed_updates": ["message"]})
    except Exception as exc:
        print("[REQUEST] Telegram polling error:", type(exc).__name__, str(exc)[:250])
        return
    print(f"[REQUEST] TELEGRAM_UPDATES count={len(updates)}")
    for update in updates:
        update_id = update.get("update_id")
        if update_id is None:
            continue
        message = update.get("message") or {}
        chat_id = str((message.get("chat") or {}).get("id", ""))
        command = requested_match(message.get("text", ""))
        print(f"[REQUEST] incoming update={update_id} authorized={chat_id == str(TELEGRAM_CHAT_ID)} recognized={bool(command)}")
        if chat_id == str(TELEGRAM_CHAT_ID) and command:
            try:
                if command == "__HELP__":
                    reply_to_chat(chat_id, "Shkruaj: /analizo Paro vs Asai\nOse: Shiko Paro - Asai")
                    processed = True
                else:
                    processed = investigate_match(command, chat_id)
            except Exception as exc:
                print("[REQUEST] processing error:", type(exc).__name__, str(exc)[:250])
                break  # keep this update pending for the next run
            if not processed:
                break  # cap reached; leave the message pending
        # Confirm only the current processed/ignored update, not future messages.
        try:
            telegram_api("getUpdates", {"offset": update_id + 1, "limit": 1, "timeout": 0})
        except Exception as exc:
            print("[REQUEST] Telegram ack error:", type(exc).__name__)
            break

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

  # send_telegram("✅ TEST: Dërgimi në Telegram funksionon.")

    try:

        check_sources(seen)
        check_afc_social_press(send_telegram)
    except Exception as exc:

        print("Main loop error:", exc)
        raise




if __name__ == "__main__":
    main()
