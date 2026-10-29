"""Conservative outbound-only checks; discovery and stored evidence remain intact."""
import html
import re

GENERIC_LINEUP = re.compile(
    r"(is .{0,45} playing today|will .{0,45} play today|"
    r"predicted (lineup|xi)|probable (lineup|xi)|"
    r"expected to (play|start)|latest team news|"
    r"where to watch|live stream|tv channel)", re.I)
CONFIRMED_CHANGE = re.compile(
    r"(ruled out|will miss|confirmed (absen|absence|injury|lineup)|"
    r"not in (the )?squad|left out|sidelined|suspended|"
    r"tore (his|her)|fracture|surgery|"
    r"pelatih memastikan|dipastikan absen|欠場|離脱|出場停止|"
    r"결장|부상으로 제외|غياب مؤكد|سيغيب)", re.I)
HISTORICAL = re.compile(
    r"(long-term absence|has experienced injuries|"
    r"injury risk|career injury|過去.*けが|長期離脱を経験|"
    r"思いや|サポーターへの|振り返)", re.I)

def reject_alert(team, item, evidence, tags):
    title = html.unescape(item.get("title", "") or "")
    summary = html.unescape(item.get("summary", "") or "")
    article = html.unescape(item.get("article_text", "") or "")
    proof = " ".join(str(sentence) for _, sentence in (evidence or []))
    text = " ".join((title, summary, article, proof))
    tagset = set(tags or [])
    # Never promote a generic lineup/TV preview to actionable squad news.
    # A genuinely confirmed new absence in the article overrides this rule.
    if GENERIC_LINEUP.search(title) and not CONFIRMED_CHANGE.search(article + " " + proof):
        return "generic_lineup_preview"
    # Historical injury profiles are not current availability reports.
    if HISTORICAL.search(title) and not CONFIRMED_CHANGE.search(article + " " + proof):
        return "historical_injury_profile"
    if tagset <= {"PREMATCH"}:
        concrete = ("rotate", "rotation", "rotasi", "rested", "resting",
                    "press conference", "coach confirmed", "pelatih memastikan",
                    "injur", "cedera", "absen", "suspend", "digantung",
                    "travel", "flight", "visa", "lineup", "starting xi",
                    "ruled out", "doubtful", "return", "kembali", "out of squad")
        if not any(word in proof.lower() for word in concrete):
            return "generic_prematch"
    if re.search(r"\b(manchester united|man united|premier league england)\b", text, re.I):
        if not re.search(r"\b(vs|versus|against|melawan)\b", title, re.I):
            return "unrelated_europe"
    return None
