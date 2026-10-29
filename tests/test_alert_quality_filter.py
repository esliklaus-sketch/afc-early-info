import unittest
from alert_quality_filter import reject_alert


class AlertQualityTests(unittest.TestCase):
    def test_ronaldo_generic_preview(self):
        item = {"title": "Al Nassr vs Al Kholood: Is Cristiano Ronaldo Playing Today?",
                "summary": "Ronaldo is expected to play", "article_text": ""}
        self.assertEqual(reject_alert("Al Nassr", item, [], ["LINEUP"]),
                         "generic_lineup_preview")

    def test_confirmed_absence_preserved(self):
        item = {"title": "Al Nassr vs Al Kholood: Latest Team News",
                "summary": "", "article_text": "Coach confirmed Ronaldo will miss the match"}
        self.assertIsNone(reject_alert("Al Nassr", item, [], ["LINEUP"]))

    def test_historical_injury_profile(self):
        item = {"title": "Kyoto Sanga star looks back at career injury risk",
                "summary": "", "article_text": "Reflecting on past injuries and supporters"}
        self.assertEqual(reject_alert("Kyoto Sanga", item, [], ["SQUAD"]),
                         "historical_injury_profile")

    def test_actual_match_injury_not_blocked(self):
        item = {"title": "Al Faisaly injury update", "summary": "",
                "article_text": "Al Awadat was injured and substituted in minute 36"}
        self.assertIsNone(reject_alert("Al Faisaly", item, [], ["SQUAD"]))


if __name__ == "__main__":
    unittest.main()
