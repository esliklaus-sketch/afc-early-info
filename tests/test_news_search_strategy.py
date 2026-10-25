import unittest
from urllib.parse import unquote
import afc_social_press as press
from news_search_strategy import discovery_urls, priority

class SearchTests(unittest.TestCase):
    def evidence(self, title, body, team='Tractor'):
        return press._signal_evidence({'title': title, 'summary': '', 'article_text': body}, team)

    def test_following_paragraph(self):
        evidence = self.evidence('Tractor FC team news ahead of Al Ain',
                                 'The striker will miss Monday\'s match with an injury.')
        # A multi-club heading must NOT assign an unnamed player to either club.
        self.assertEqual(evidence, [])
        evidence = self.evidence('Tractor FC team news',
                                 'The striker will miss Monday\'s match with an injury.')
        self.assertTrue(any(k == 'SQUAD' for k, _ in evidence))

    def test_explicit_paragraph_resets_context(self):
        evidence = self.evidence('Asian football news',
            'Tractor FC prepare for the next match.\nThe striker will miss Monday\'s match.')
        self.assertTrue(evidence)

    def test_other_club_stops_context(self):
        evidence = self.evidence('Tractor FC football news',
            'Al Ain FC prepare for Monday.\nThe striker will miss the match.')
        self.assertEqual(evidence, [])

    def test_negation(self):
        self.assertEqual(self.evidence('Tractor FC football team news',
            'No players are injured and the squad is fully fit.'), [])

    def test_historical(self):
        self.assertEqual(self.evidence('Tractor FC football news',
            'Tractor FC striker was injured last season.'), [])

    def test_context_expires(self):
        self.assertEqual(self.evidence('Tractor FC football news',
            'First paragraph.\nSecond paragraph.\nAn unnamed striker will miss the next match.'), [])

    def test_travel_and_rotation(self):
        self.assertTrue(any(k == 'TRAVEL' for k, _ in self.evidence(
            'Tractor FC football news', 'The club is waiting for flight permission.')))
        self.assertTrue(any(k == 'LINEUP' for k, _ in self.evidence(
            'Tractor FC football news', 'The coach will rotate for Monday\'s game.')))

    def test_qualification_context(self):
        self.assertTrue(any(k == 'PREMATCH' for k, _ in self.evidence(
            'Tractor FC football news', 'The club is already qualified for the next round.')))

    def test_multilingual_discovery(self):
        urls = discovery_urls('("FC서울" OR "FC Seoul")', ['yna.co.kr', 'kleague.com'], ('ko', 'KR'))
        decoded = unquote(' '.join(urls))
        self.assertIn('부상', decoded)
        self.assertIn('ceid=KR:ko', decoded)
        self.assertIn('site:yna.co.kr', decoded)
        self.assertEqual(len(urls), len(set(urls)))

    def test_source_chunks(self):
        urls = discovery_urls('"Tractor FC"', [f'source{i}.test' for i in range(12)], ('fa', 'IR'))
        self.assertIn('source11.test', unquote(' '.join(urls)))
        self.assertLessEqual(len(urls), 6)

    def test_ranking(self):
        self.assertGreater(priority({'title': 'Tractor FC striker ruled out'}, press.SIGNALS, press._normalized),
                           priority({'title': 'Tractor FC birthday photos'}, press.SIGNALS, press._normalized))


if __name__ == '__main__':
    unittest.main()
