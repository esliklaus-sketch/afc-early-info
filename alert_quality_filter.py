"""Conservative outbound-only quality checks; discovery remains unchanged."""
import re

def reject_alert(team, item, evidence, tags):
    title = item.get("title", "")
    text = (title + " " + item.get("summary", "")).lower()
    proof = " ".join(sentence for _, sentence in evidence).lower()
    # Betting/TV previews often repeat generic motivation without actionable news.
    if set(tags) <= {"PREMATCH"}:
        concrete = ("rotate", "rotation", "rotasi", "rested", "resting",
                    "press conference", "coach confirmed", "pelatih memastikan",
                    "injur", "cedera", "absen", "suspend", "digantung",
                    "travel", "flight", "visa", "lineup", "starting xi",
                    "ruled out", "doubtful", "return", "kembali", "out of squad")
        if not any(word in proof for word in concrete):
            return "generic_prematch"
    # Reject articles where the only 'team match' is a publisher/section name.
    # Do not suppress named opponent absences: those can be valuable.
    if re.search(r"\b(manchester united|man united|premier league england)\b", text):
        if not re.search(r"\b(vs|versus|against|melawan)\b", title.lower()):
            return "unrelated_europe"
    return None
