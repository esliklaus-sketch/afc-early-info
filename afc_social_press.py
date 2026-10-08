"""AFC social/press news discovery add-on. No Telegram secrets stored here.
Install: pip install requests feedparser
Call: from afc_social_press import check_afc_social_press
      check_afc_social_press(send_message=your_existing_telegram_sender)
Sender signature: send_message(text: str). Schedule every 10-20 minutes.
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

import feedparser
import requests

STATE_PATH = Path(os.getenv('AFC_PRESS_STATE', 'afc_press_seen.json'))
TIMEOUT = 12
# Team names as shown in the two screenshots. Verified social URLs can be added below.
MATCHES = {
    '2026-10-12': [
        ('Pakhtakor', 'Al Qadsiah'), ('Al Wasl', 'Al Ahli Saudi'),
        ('Tractor SC', 'Al Shamal'), ('Al Gharafa', 'Esteghlal'),
        ('Al Nassr', 'Neftchi Fergana'), ('Al Quwa Al Jawiya', 'Al Ain'),
    ],
    '2026-10-13': [
        ('Newcastle Jets', 'Gamba Osaka'), ('Kyoto Sanga', 'Ratchaburi'),
        ('Pohang Steelers', 'Johor Darul Tazim'), ('Shanghai Port', 'Daejeon Hana Citizen'),
        ('Buriram United', 'Beijing Guoan'), ('Cong An Ha Noi', 'Kashima Antlers'),
        ('Al Sadd', 'Al Hilal'), ('Al Ittihad', 'Shabab Al Ahli Dubai'),
        ('East Bengal', 'Al Shorta'), ('Al Seeb', 'Al Hussein SC'),
    ],
}
# Add ONLY confirmed club or federation RSS/Atom feeds. Social media URLs
# without RSS/API access must NOT be treated as machine-readable feeds.
VERIFIED_FEEDS = {
    # 'East Bengal': ['https://verified-site.example/rss'],
}
# Keyword candidates, not confirmation of squad news.
SIGNALS = {
    'SQUAD': ['injury', 'injured', 'ruled out', 'sidelined', 'suspended', 'absence',
              'unavailable', 'doubtful', 'out of squad', 'missing', 'إصابة', 'غياب',
              'موقوف', '欠場', '負傷', '부상', '결장'],
    'LINEUP': ['starting xi', 'starting lineup', 'line-up', 'team news', 'rotation',
               'rested', 'first eleven', 'التشكيلة', '先発', '선발'],
    'COACH': ['press conference', 'pre-match', 'head coach', 'manager said',
              'المؤتمر الصحفي', '記者会見', '기자회견'],
    'TRAVEL': ['flight delayed', 'travel disruption', 'visa issue', 'stranded',
               'arrived late', 'travel delay'],
}
HIGH_PRIORITY = {'SQUAD', 'LINEUP', 'TRAVEL'}


def _load_state():
    try:
        data = json.loads(STATE_PATH.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    tmp.replace(STATE_PATH)


def _feed_items(url):
    response = requests.get(url, timeout=TIMEOUT, headers={'User-Agent': 'AFC-Early-Info/1.0'})
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    for item in feed.entries[:15]:
        yield {
            'title': re.sub(r'<[^>]*>', ' ', item.get('title', '')).strip(),
            'summary': re.sub(r'<[^>]*>', ' ', item.get('summary', '')).strip(),
            'link': item.get('link', ''),
            'published': item.get('published_parsed') or item.get('updated_parsed'),
        }


def _recent(item, now):
    stamp = item['published']
    if not stamp:
        return False  # Undated content cannot be called breaking news.
    try:
        published = datetime(*stamp[:6], tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return False
    return now - timedelta(hours=36) <= published <= now + timedelta(minutes=15)


def _classify(item):
    text = (item['title'] + ' ' + item['summary']).lower()
    return [kind for kind, words in SIGNALS.items() if any(w.lower() in text for w in words)]


def _google_news_feed(team, opponent):
    # Google News RSS is a discovery source; linked publisher must be checked
    # before claiming the information is confirmed or officially sourced.
    query = f'"{team}" (injury OR squad OR lineup OR "press conference" OR suspended OR coach)'
    return 'https://news.google.com/rss/search?q=' + quote(query) + '&hl=en&gl=US&ceid=US:en'


def check_afc_social_press(send_message, now=None, dry_run=False):
    """Returns number of alerts sent. Sender must accept one string argument.

    Existing bot handles Telegram; this add-on never starts a second bot loop.
    """
    now = now or datetime.now(timezone.utc)
    state = _load_state()
    alerts = 0
    # Limit activity to 3 days before and 1 day after a match.
    for day, games in MATCHES.items():
        match_day = datetime.strptime(day, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        if not (match_day - timedelta(days=3) <= now <= match_day + timedelta(days=2)):
            continue
        for home, away in games:
            for team, opponent in ((home, away), (away, home)):
                feeds = [_google_news_feed(team, opponent)] + VERIFIED_FEEDS.get(team, [])
                for feed_url in feeds:
                    try:
                        entries = list(_feed_items(feed_url))
                    except (requests.RequestException, ValueError, OSError) as exc:
                        print(f'[AFC PRESS] Feed unavailable for {team}: {exc}')
                        continue
                    for item in entries:
                        if not item['title'] or not item['link'] or not _recent(item, now):
                            continue
                        tags = _classify(item)
                        if not tags:
                            continue
                        # Only potentially impactful news; press conference alone
                        # is not sufficient unless a squad/lineup/travel signal exists.
                        if not HIGH_PRIORITY.intersection(tags):
                            continue
                        digest = hashlib.sha256((team + '|' + item['link'].split('?')[0]).encode()).hexdigest()
                        if digest in state:
                            continue
                        msg = (f'⚠️ AFC EARLY INFO | UNVERIFIED\n'
                               f'📅 {day} | {home} vs {away}\n'
                               f'🏟️ Team: {team}\n'
                               f'🔎 Signals: {", ".join(tags)}\n'
                               f'📰 {item["title"][:180]}\n'
                               f'🔗 {item["link"]}\n'
                               f'⚠️ Candidate only: verify primary source, player identity, and match relevance.')
                        if not dry_run:
                            send_message(msg)  # Mark as seen only after successful delivery.
                            state[digest] = now.isoformat()
                            _save_state(state)
                        alerts += 1
    # Retain recent dedup keys only.
    if not dry_run:
        cutoff = now - timedelta(days=14)
        state = {k: v for k, v in state.items() if datetime.fromisoformat(v) >= cutoff}
        _save_state(state)
    return alerts
