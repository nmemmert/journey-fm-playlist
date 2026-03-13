import logging
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager
import requests

from journeyfm.paths import data_path

logger = logging.getLogger(__name__)
DEBUG_SCRAPE_DIR = data_path("debug_scrapes")


def detect_chrome_binary():
    env_binary = os.getenv("CHROME_BINARY", "").strip()
    if env_binary and os.path.exists(env_binary):
        return env_binary

    candidates = []
    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA", "")
        program_files = os.getenv("PROGRAMFILES", "")
        program_files_x86 = os.getenv("PROGRAMFILES(X86)", "")
        candidates.extend([
            os.path.join(local_app_data, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(program_files, "Chromium", "Application", "chrome.exe"),
            os.path.join(program_files_x86, "Chromium", "Application", "chrome.exe"),
        ])
    else:
        candidates.extend([
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
            "/opt/google/chrome/chrome",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ])

    for binary in candidates:
        if binary and os.path.exists(binary):
            return binary

    for name in ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"]:
        found = shutil.which(name)
        if found:
            return found
    return None


def detect_chromedriver_path():
    env_driver = os.getenv("CHROMEDRIVER_PATH", "").strip()
    if env_driver and os.path.exists(env_driver):
        return env_driver
    for candidate in ["/usr/bin/chromedriver", "/usr/local/bin/chromedriver"]:
        if os.path.exists(candidate):
            return candidate
    return shutil.which("chromedriver")


def _write_debug_payload(station_key, payload, extension):
    DEBUG_SCRAPE_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = DEBUG_SCRAPE_DIR / f"{station_key}_{timestamp}.{extension}"
    with open(file_path, "w", encoding="utf-8") as file_handle:
        file_handle.write(payload)
    latest_path = DEBUG_SCRAPE_DIR / f"{station_key}_latest.{extension}"
    with open(latest_path, "w", encoding="utf-8") as file_handle:
        file_handle.write(payload)
    return str(file_path)


class JourneyFMScraper:
    station_key = "journey_fm"
    display_name = "Journey FM"
    url = "https://www.myjourneyfm.com/recently-played/"

    SELECTOR_PATTERNS = [
        {
            "name": "rp-item",
            "container": ("div", "rp-item"),
            "title": ("h5", "song-title"),
            "artist": ("p", "song-artist"),
        },
        {
            "name": "top-rp-list",
            "container": ("div", "song-item"),
            "title": ("div", "title-artist"),
            "artist": ("span", None),
        },
    ]

    @classmethod
    def _extract_with_pattern(cls, soup, pattern):
        songs = []
        container_tag, container_class = pattern["container"]
        title_tag, title_class = pattern["title"]
        artist_tag, artist_class = pattern["artist"]

        for item in soup.find_all(container_tag, class_=container_class):
            if title_class:
                title_elem = item.find(title_tag, class_=title_class)
            else:
                title_elem = item.find(title_tag)
            if not title_elem:
                continue

            if pattern["name"] == "top-rp-list":
                paragraph = title_elem.find("p")
                if not paragraph:
                    continue
                combined = paragraph.get_text(" ", strip=True)
                parts = re.split(r"\s+by\s+", combined, maxsplit=1, flags=re.IGNORECASE)
                if len(parts) != 2:
                    continue
                title = parts[0].strip()
                artist = parts[1].strip()
            else:
                if artist_class:
                    artist_elem = item.find(artist_tag, class_=artist_class)
                else:
                    artist_elem = item.find(artist_tag)
                if not artist_elem:
                    continue
                title = title_elem.get_text(" ", strip=True).strip()
                artist = artist_elem.get_text(" ", strip=True).strip()

            if title and artist:
                songs.append({"title": title, "artist": artist, "source": cls.display_name})

        return songs

    @classmethod
    def parse_html_with_telemetry(cls, html):
        soup = BeautifulSoup(html, "html.parser")
        for pattern in cls.SELECTOR_PATTERNS:
            songs = cls._extract_with_pattern(soup, pattern)
            if songs:
                return songs, pattern["name"]
        return [], "none"

    @staticmethod
    def parse_html(html):
        songs, _pattern = JourneyFMScraper.parse_html_with_telemetry(html)
        return songs

    @classmethod
    def scrape(cls, driver):
        driver.get(cls.url)
        WebDriverWait(driver, 15).until(
            lambda _driver: (
                bool(_driver.find_elements(By.CSS_SELECTOR, "div.rp-item"))
                or bool(_driver.find_elements(By.CSS_SELECTOR, "div.song-item"))
            )
        )
        try:
            more_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "moreSongs")))
            more_button.click()
            time.sleep(2)
        except Exception:
            pass
        html = driver.page_source
        raw_path = _write_debug_payload(cls.station_key, html, "html")
        songs, parse_pattern = cls.parse_html_with_telemetry(html)
        return songs, raw_path, parse_pattern

    @classmethod
    def scrape_without_driver(cls):
        response = requests.get(cls.url, timeout=20)
        response.raise_for_status()
        html = response.text
        raw_path = _write_debug_payload(cls.station_key, html, "html")
        songs, parse_pattern = cls.parse_html_with_telemetry(html)
        return songs, raw_path, f"{parse_pattern}-requests-fallback"


class SpiritFMScraper:
    station_key = "spirit_fm"
    display_name = "Spirit FM"
    url = "https://spiritfm.com/ajax/now_playing_history.txt"

    @staticmethod
    def parse_text(text):
        songs = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.match(r"^\w+\s+\d+:\d+[AP]M\s+(.+?)\s+-\s+(.+)$", line)
            if not match:
                continue
            artist = match.group(1).strip().replace("&amp;", "&")
            title = match.group(2).strip().replace("&amp;", "&")
            if title and artist:
                songs.append({"title": title, "artist": artist, "source": SpiritFMScraper.display_name})
        return songs

    @classmethod
    def scrape(cls, driver):
        driver.get(cls.url)
        time.sleep(2)
        text = BeautifulSoup(driver.page_source, "html.parser").get_text()
        raw_path = _write_debug_payload(cls.station_key, text, "txt")
        return cls.parse_text(text), raw_path, "plain-text-regex"

    @classmethod
    def scrape_without_driver(cls):
        response = requests.get(cls.url, timeout=20)
        response.raise_for_status()
        text = response.text
        raw_path = _write_debug_payload(cls.station_key, text, "txt")
        return cls.parse_text(text), raw_path, "plain-text-regex-requests-fallback"


class KLOVEScraper:
    station_key = "klove"
    display_name = "K-LOVE"
    url = "https://www.klove.com/music/songs"
    # K-LOVE is a JS-rendered React app; Selenium is the primary path.
    # The requests fallback may still return partial SSR content worth parsing.
    _LOAD_SELECTOR = "a[href*='/music/artists/']"

    @staticmethod
    def parse_html(html):
        songs, _pattern = KLOVEScraper.parse_html_with_telemetry(html)
        return songs

    @staticmethod
    def parse_html_with_telemetry(html):
        soup = BeautifulSoup(html, "html.parser")
        songs = []
        seen = set()

        # Collect every anchor that points at /music/artists/{artist}/{song}
        # The page renders each card as two anchors (art + title) — use hrefs
        # as a dedup key so we only process each song once.
        processed_hrefs = set()
        for anchor in soup.find_all("a", href=re.compile(r"/music/artists/[^/]+/[^/]+")):
            href = anchor.get("href", "").strip().rstrip("/")
            parts = href.strip("/").split("/")
            # Expect:  music / artists / artist-slug / song-slug
            if len(parts) < 4:
                continue

            title_text = anchor.get_text(" ", strip=True)
            if not title_text or len(title_text) < 2:
                # Image-only anchor (cover art link) — skip it; the title anchor
                # for this same href will appear later in the DOM with real text.
                continue

            # Now that we have a text-bearing anchor, dedup by href
            if href in processed_hrefs:
                continue
            processed_hrefs.add(href)

            # Skip navigation / album-only links (e.g. artist page without song)
            song_slug = parts[-1]
            artist_slug = parts[-2] if len(parts) >= 4 else ""

            # Find "By {artist}" text in nearby DOM — check siblings and parent
            artist_text = ""
            parent = anchor.parent
            if parent:
                full_text = parent.get_text(" ", strip=True)
                by_match = re.search(r"\bBy\s+(.+)", full_text)
                if by_match:
                    artist_text = by_match.group(1).strip()

            if not artist_text and parent and parent.parent:
                grandparent_text = parent.parent.get_text(" ", strip=True)
                by_match = re.search(r"\bBy\s+(.+?)(?:\bBy\b|$)", grandparent_text)
                if by_match:
                    artist_text = by_match.group(1).strip()

            if not artist_text:
                # Derive artist from URL slug as last resort
                artist_text = " ".join(w.capitalize() for w in artist_slug.split("-"))

            # Strip leftover boilerplate that sometimes bleeds in
            artist_text = re.sub(r"\s*(feat\.|ft\.|featuring|Play Sample|Image).*$", "",
                                  artist_text, flags=re.IGNORECASE).strip()

            if title_text and artist_text:
                key = (title_text.lower(), artist_text.lower())
                if key not in seen:
                    seen.add(key)
                    songs.append({"title": title_text, "artist": artist_text,
                                  "source": KLOVEScraper.display_name})

        if songs:
            return songs, "klove-anchor-by"
        return [], "none"

    @classmethod
    def scrape(cls, driver):
        driver.get(cls.url)
        # Wait for song anchor links to appear (JS-rendered)
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, cls._LOAD_SELECTOR))
        )
        time.sleep(2)  # Allow lazy-load tiles to settle
        html = driver.page_source
        raw_path = _write_debug_payload(cls.station_key, html, "html")
        songs, parse_pattern = cls.parse_html_with_telemetry(html)
        return songs, raw_path, parse_pattern

    @classmethod
    def scrape_without_driver(cls):
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        response = requests.get(cls.url, headers=headers, timeout=20)
        response.raise_for_status()
        html = response.text
        raw_path = _write_debug_payload(cls.station_key, html, "html")
        songs, parse_pattern = cls.parse_html_with_telemetry(html)
        return songs, raw_path, f"{parse_pattern}-requests-fallback"


SCRAPERS = {
    JourneyFMScraper.station_key: JourneyFMScraper,
    SpiritFMScraper.station_key: SpiritFMScraper,
    KLOVEScraper.station_key: KLOVEScraper,
}


def build_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    chrome_binary = detect_chrome_binary()
    if chrome_binary:
        options.binary_location = chrome_binary
    chromedriver_path = detect_chromedriver_path()
    if chromedriver_path:
        service = Service(chromedriver_path)
    else:
        service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def scrape_recently_played(selected_stations=None):
    selected_stations = selected_stations or ["journey_fm", "spirit_fm"]
    driver = None
    driver_start_error = ""
    all_songs = []
    seen = set()
    station_results = []

    try:
        try:
            driver = build_driver()
        except Exception as exc:
            driver = None
            driver_start_error = str(exc)
            logger.warning("Browser scraper unavailable; using fallback mode: %s", exc)
        for station_key in selected_stations:
            scraper_cls = SCRAPERS.get(station_key)
            if scraper_cls is None:
                station_results.append({
                    "station": station_key,
                    "display_name": station_key,
                    "success": False,
                    "error": "unsupported-station",
                    "scraped_count": 0,
                    "raw_path": "",
                })
                continue
            try:
                if driver is not None:
                    try:
                        songs, raw_path, parse_pattern = scraper_cls.scrape(driver)
                    except Exception as scrape_error:
                        logger.warning(
                            "Selenium scrape failed for %s, retrying fallback mode: %s",
                            scraper_cls.display_name,
                            scrape_error,
                        )
                        songs, raw_path, parse_pattern = scraper_cls.scrape_without_driver()
                else:
                    songs, raw_path, parse_pattern = scraper_cls.scrape_without_driver()
                raw_payload_bytes = 0
                if raw_path and os.path.exists(raw_path):
                    try:
                        raw_payload_bytes = os.path.getsize(raw_path)
                    except Exception:
                        raw_payload_bytes = 0
                added_for_station = 0
                for song in songs:
                    dedupe_key = (song["title"].lower(), song["artist"].lower())
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    all_songs.append(song)
                    added_for_station += 1
                    logger.info("  Found: %s by %s", song["title"], song["artist"])
                station_results.append({
                    "station": station_key,
                    "display_name": scraper_cls.display_name,
                    "success": True,
                    "error": "",
                    "scraped_count": added_for_station,
                    "raw_path": raw_path,
                    "raw_payload_bytes": raw_payload_bytes,
                    "parse_pattern": parse_pattern,
                })
            except Exception as exc:
                combined_error = str(exc)
                if driver is None and driver_start_error:
                    combined_error = f"{combined_error}; browser init: {driver_start_error}"
                station_results.append({
                    "station": station_key,
                    "display_name": scraper_cls.display_name,
                    "success": False,
                    "error": combined_error,
                    "scraped_count": 0,
                    "raw_path": "",
                    "raw_payload_bytes": 0,
                    "parse_pattern": "error",
                })
                logger.error("Error scraping %s: %s", scraper_cls.display_name, exc)
    finally:
        if driver is not None:
            driver.quit()

    logger.info("Total unique songs found: %s", len(all_songs))
    return {"songs": all_songs, "station_results": station_results}
