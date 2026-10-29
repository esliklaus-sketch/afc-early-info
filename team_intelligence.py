"""Evidence-led team dossier for AFC Early Info.

Stores dated observations, never invents lineups, playing minutes or confirmed
absences. Data is local to the VPS and persists across scheduled runs.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

DOSSIER_PATH = Path(os.getenv("AFC_TEAM_DOSSIERS", "afc_team_dossiers.json"))
MAX_ITEMS = 35
RETENTION_DAYS = 21

def _read():
    try:
        data = json.loads(DOSSIER_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def _write(data):
    DOSSIER_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DOSSIER_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DOSSIER_PATH)

def _short(text, limit=165):
    return re.sub(r"\s+", " ", str(text or "")).strip()[:limit]

def update_dossier(team, item, tags, evidence, now=None):
    """Return context for a new alert, recording only source-backed observations.

    Called only after a candidate passes relevance and quality checks.
    No assumptions about who starts, availability, or tactical impact.
    """
    now = now or datetime.now(timezone.utc)
    data = _read()
    previous = data.get(team, [])
    if not isinstance(previous, list):
        previous = []
    cutoff = now - timedelta(days=RETENTION_DAYS)
    valid = []
    for obs in previous:
        try:
            if datetime.fromisoformat(obs["seen_at"]) >= cutoff:
                valid.append(obs)
        except (KeyError, TypeError, ValueError):
            continue
    url = item.get("article_url") or item.get("link") or ""
    title = _short(item.get("title"))
    key = (url, title.casefold())
    prior = [obs for obs in valid if (obs.get("url"), obs.get("title", "").casefold()) != key]
    # Existing observations are leads, not independently verified facts.
    earlier = prior[-4:]
    current = {
        "seen_at": now.isoformat(),
        "title": title,
        "url": url,
        "tags": list(tags),
        "evidence": [_short(sentence, 210) for _, sentence in evidence[:3]],
        "article_read": bool(item.get("article_text")),
        "status": "unverified",
    }
    data[team] = (prior + [current])[-MAX_ITEMS:]
    _write(data)
    if earlier:
        history = "\n".join(
            "• " + _short(obs.get("title"), 120) + " [" + ", ".join(obs.get("tags", [])) + "]"
            for obs in earlier
        )
    else:
        history = "Nuk ka sinjale të mëparshme të ruajtura për këtë ekip."
    return {
        "history": history,
        "current": title,
        "prior_count": len(prior),
        "warning": ("Sinjalet e mëparshme nuk provojnë se mungesat vazhdojnë. "
                    "Titullarët, minutat, zëvendësuesit dhe gjendja aktuale "
                    "duhen konfirmuar me burime të datuara."),
    }
