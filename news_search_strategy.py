"""Bounded multilingual discovery and paragraph-scoped AFC evidence extraction."""
import re
from urllib.parse import quote

SEARCH_TERMS = {
    "en": '"team news" OR "ruled out" OR "press conference" OR rotation OR "travel delay"',
    "ar": 'غياب OR إصابة OR التشكيلة OR "مؤتمر صحفي" OR سفر',
    "fa": 'مصدوم OR محروم OR "نشست خبری" OR "مجوز پرواز" OR سفر',
    "ko": '부상 OR 결장 OR 로테이션 OR 기자회견 OR 원정',
    "ja": '負傷 OR 欠場 OR 出場停止 OR 記者会見',
    "id": 'cedera OR absen OR rotasi OR "konferensi pers"',
    "ms": 'kecederaan OR digantung OR "sidang media"',
    "ru": 'травма OR пропустит OR дисквалификация OR "пресс конференция"',
    "vi": '"chấn thương" OR "vắng mặt" OR "họp báo"',
    "th": 'บาดเจ็บ OR ติดโทษแบน OR แถลงข่าว',
    "zh-CN": '伤病 OR 缺阵 OR 停赛 OR 发布会',
    "zh-TW": '受傷 OR 缺陣 OR 停賽 OR 記者會',
}


def discovery_urls(team_query, domains, locale=None):
    """General + native + intent + bounded publisher groups; no title-only scoring."""
    language, country = locale or ("en", "US")
    plans = [(team_query + " when:2d", "en", "US")]
    if language != "en" or country != "US":
        plans.append((team_query + " when:2d", language, country))
    intent = SEARCH_TERMS.get(language, SEARCH_TERMS["en"])
    plans.append((f'{team_query} ({intent}) when:2d', language, country))
    # Splitting avoids a long OR query hiding later publishers.
    for start in range(0, min(len(domains), 12), 4):
        sites = " OR ".join("site:" + d for d in domains[start:start + 4])
        plans.append((f'{team_query} ({sites}) when:2d', language, country))
    return list(dict.fromkeys(
        "https://news.google.com/rss/search?q=" + quote(query)
        + "&hl=" + lang + "&gl=" + nation + "&ceid=" + nation + ":" + lang
        for query, lang, nation in plans))


def priority(item, signals, normalize):
    text = normalize(item.get("title", "") + " " + item.get("summary", ""))
    return sum(1 for terms in signals.values() for term in terms if normalize(term) in text)


def scoped_evidence(item, team, target_teams, names_for, normalize, contains,
                    football_terms, native_claims, native_negations, strict):
    """Allow a short claim after an explicit team paragraph, never across another team."""
    evidence = list(strict(item, team))
    headline = item.get("title", "") + " " + item.get("summary", "")
    head = normalize(headline)
    names = names_for(team)
    scoped_title = any(contains(head, n) for n in names)
    # Do not inherit team context from a roundup/multi-team heading.
    other_teams = [t for t in target_teams if t != team and not any(
        normalize(a) == normalize(b) for a in names_for(t) for b in names)]
    multi_title = any(any(contains(head, n) for n in names_for(t)) for t in other_teams)
    football_context = any(contains(normalize(headline + " " + item.get("article_text", "")), w)
                           for w in football_terms)
    if not football_context:
        return evidence
    context = headline[:240] if scoped_title and not multi_title else None
    remaining = 2 if context else 0
    future = re.compile(r"\b(?:ahead of|pre-match|will miss|will be|next match|upcoming|against|on (?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday))\b", re.I)
    recap = re.compile(r"\b(?:last season|last year|yesterday|last match|last game|was substituted|had missed)\b", re.I)
    negated = re.compile(r"\b(?:no|not)\b.{0,45}\b(?:injur\w*|suspend\w*|miss\w*|rotat\w*)\b|injury.free|fully fit|full strength", re.I)
    speculative = re.compile(r"\b(?:predicted lineup|predicted starting|unconfirmed rumour|not confirmed|could miss|might miss|may miss)\b", re.I)
    patterns = {
        "SQUAD": r"\b(?:ruled out|will miss|set to miss|sidelined|suspended|unavailable|injured|doubtful)\b",
        "LINEUP": r"\b(?:confirmed (?:lineup|starting)|official (?:lineup|starting)|will (?:rotate|rest)|rotation (?:for|against))\b",
        "TRAVEL": r"\b(?:flight delayed|flight cancelled|travel disruption|visa issue|visa problem|landing permit|flight permission|travel delay|arrived late)\b",
        "PREMATCH": r"\b(?:must.win|must win|need(?:s)? (?:a win|to win)|already qualified|qualification secured|prioritis[ez] (?:the )?league)\b",
    }
    for paragraph in item.get("article_text", "").splitlines():
        paragraph = paragraph.strip()
        if not paragraph or len(paragraph) > 1200:
            context = None; remaining = 0
            continue
        text = normalize(paragraph)
        mentioned = any(contains(text, n) for n in names)
        other = any(any(contains(text, n) for n in names_for(t)) for t in other_teams)
        if other:
            context = None; remaining = 0
            # Multi-team paragraphs remain subject to the original strict detector.
            continue
        if mentioned:
            context = paragraph[:240]; remaining = 2
        elif not context or remaining <= 0:
            continue
        else:
            remaining -= 1
        if (negated.search(paragraph) or speculative.search(paragraph)
                or any(contains(text, n) for n in native_negations)
                or (recap.search(paragraph) and not future.search(paragraph))):
            continue
        tagged = [kind for kind, pattern in patterns.items() if re.search(pattern, paragraph, re.I)]
        tagged += [kind for kind, terms in native_claims.items() if any(contains(text, n) for n in terms)]
        for kind in dict.fromkeys(tagged):
            proof = paragraph if mentioned else context + " — " + paragraph
            if not any(k == kind and paragraph in sentence for k, sentence in evidence):
                evidence.append((kind, proof[:550]))
    # Filter obvious historical claims from the original detector too.
    return list(dict.fromkeys((kind, proof) for kind, proof in evidence
                             if not (recap.search(proof) and not future.search(proof))))
