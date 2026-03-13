import unittest
from pathlib import Path

from journeyfm.scraper_service import JourneyFMScraper, SpiritFMScraper, KLOVEScraper


class ScraperParserTests(unittest.TestCase):
    def fixture_text(self, name):
        fixture_path = Path("tests") / "fixtures" / name
        return fixture_path.read_text(encoding="utf-8")

    def test_parse_journey_fm_html(self):
        html = """
        <div class='rp-item'>
            <h5 class='song-title'>No Survivors</h5>
            <p class='song-artist'>Jeremy Camp</p>
        </div>
        <div class='rp-item'>
            <h5 class='song-title'>Take It All Back</h5>
            <p class='song-artist'>Tauren Wells</p>
        </div>
        """
        songs = JourneyFMScraper.parse_html(html)
        self.assertEqual(2, len(songs))
        self.assertEqual('No Survivors', songs[0]['title'])
        self.assertEqual('Jeremy Camp', songs[0]['artist'])

    def test_parse_journey_fm_current_markup_fixture(self):
        html = self.fixture_text("journeyfm_recent_markup.html")
        songs, parse_pattern = JourneyFMScraper.parse_html_with_telemetry(html)
        self.assertEqual("top-rp-list", parse_pattern)
        self.assertEqual(2, len(songs))
        self.assertEqual('Have Your Way', songs[0]['title'])
        self.assertEqual('Katy Nichole', songs[0]['artist'])

    def test_parse_spirit_fm_text(self):
        text = """
        Mon 01:45PM Brandon Lake - Hard Fought Hallelujah
        Mon 01:49PM Danny Gokey - Love God  Love People
        """
        songs = SpiritFMScraper.parse_text(text)
        self.assertEqual(2, len(songs))
        self.assertEqual('Brandon Lake', songs[0]['artist'])
        self.assertEqual('Hard Fought Hallelujah', songs[0]['title'])

    def test_parse_klove_fixture(self):
        html = self.fixture_text("klove_recent_markup.html")
        songs, parse_pattern = KLOVEScraper.parse_html_with_telemetry(html)
        self.assertEqual("klove-anchor-by", parse_pattern)
        self.assertGreaterEqual(len(songs), 3)
        # Verify first song title and artist
        titles = [s['title'] for s in songs]
        artists = [s['artist'] for s in songs]
        self.assertIn('Testimony', titles)
        self.assertIn('Katy Nichole', artists)
        self.assertIn('TobyMac', artists)


if __name__ == '__main__':
    unittest.main()
