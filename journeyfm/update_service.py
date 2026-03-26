import logging
import os
import urllib.parse

from journeyfm.config_store import load_runtime_config
from journeyfm.history_service import init_history_db, save_history_entry
from journeyfm.paths import data_path
from journeyfm.plex_service import PlexConnectionError, connect_to_plex_server, create_or_update_playlist
from journeyfm.scraper_service import scrape_recently_played

logger = logging.getLogger(__name__)


def update_buy_list(missing_songs, buy_list_path=None):
    buy_list_path = buy_list_path or data_path("amazon_buy_list.txt")
    if not missing_songs:
        logger.info("No new songs to add to buy list.")
        return []

    existing_songs = set()
    if os.path.exists(buy_list_path):
        try:
            with open(buy_list_path, "r", encoding="utf-8") as file_handle:
                lines = file_handle.read().splitlines()
            for line in lines:
                if line.strip() and not line.startswith("http") and " - " in line:
                    artist, title = line.split(" - ", 1)
                    existing_songs.add((artist.strip(), title.strip()))
        except Exception:
            pass

    new_missing = []
    for song in missing_songs:
        key = (song["artist"], song["title"])
        if key in existing_songs:
            continue
        existing_songs.add(key)
        new_missing.append(song)

    if not new_missing:
        logger.info("No new songs to add to buy list.")
        return []

    file_exists = os.path.exists(buy_list_path)
    file_empty = not file_exists or os.path.getsize(buy_list_path) == 0
    with open(buy_list_path, "a", encoding="utf-8") as file_handle:
        if file_empty:
            file_handle.write("Songs not in your library - Amazon search links:\n\n")
        for song in new_missing:
            query = urllib.parse.quote(f"{song['artist']} {song['title']}")
            file_handle.write(f"{song['artist']} - {song['title']}\n")
            file_handle.write(f"https://www.amazon.com/s?k={query}&i=digital-music\n\n")

    logger.info("Buy list updated.")
    return new_missing


def format_result_summary(result):
    station_bits = []
    for station in result.get("station_breakdown", []):
        if station.get("success"):
            pattern = station.get("parse_pattern", "unknown")
            payload_bytes = int(station.get("raw_payload_bytes", 0) or 0)
            payload_kib = payload_bytes / 1024.0
            station_bits.append(
                f"{station['display_name']}: {station['scraped_count']} [{pattern}, {payload_kib:.1f} KiB]"
            )
        else:
            station_bits.append(f"{station['display_name']}: failed")
    station_summary = ", ".join(station_bits) or "No station data"

    lines = [
        f"Scraped {result.get('scraped_count', 0)} songs ({station_summary})",
        f"Matched {result.get('matched_count', 0)} in Plex",
        f"Added {result.get('added_count', 0)} to playlist",
        f"Skipped {result.get('skipped_count', 0)} invalid entries",
        f"Suppressed {result.get('duplicate_count', 0)} duplicates already in playlist",
        f"Missing {result.get('missing_count', 0)} from Plex library",
    ]
    if result.get("status") == "error":
        lines.append(f"Error: {result.get('error_message', 'Unknown error')}")
    return "\n".join(lines)


def run_update_job(config=None, dry_run=False, persist_history=True, write_buy_list=True):
    config = config or load_runtime_config()
    result = {
        "status": "success",
        "error_message": "",
        "station_breakdown": [],
        "scraped_count": 0,
        "matched_count": 0,
        "added_count": 0,
        "added_songs": [],
        "missing_count": 0,
        "missing_songs": [],
        "duplicate_count": 0,
        "duplicate_songs": [],
        "skipped_count": 0,
        "skipped_songs": [],
    }

    token = config.get("PLEX_TOKEN", "").strip()
    server_ip = config.get("SERVER_IP", "").strip()
    playlist_name = config.get("PLAYLIST_NAME", "Journey FM Recently Played").strip()
    selected_stations = config.get("SELECTED_STATIONS", ["journey_fm", "spirit_fm"])

    if not token or not server_ip:
        result["status"] = "error"
        result["error_message"] = "Missing configuration: set Plex token and server IP before running updates"
        return result

    if persist_history:
        init_history_db()

    scrape_result = scrape_recently_played(selected_stations)
    songs = scrape_result["songs"]
    result["station_breakdown"] = scrape_result["station_results"]
    result["scraped_count"] = len(songs)
    # Keep scraped songs for history analytics (song play counts per station)
    result["scraped_songs"] = songs

    try:
        plex = connect_to_plex_server(token, server_ip)
        playlist_result = create_or_update_playlist(plex, songs, playlist_name, dry_run=dry_run)
        result.update(playlist_result)
        result["missing_count"] = len(result.get("missing_songs", []))
        result["skipped_count"] = len(result.get("skipped_songs", []))
        if write_buy_list and not dry_run:
            update_buy_list(result.get("missing_songs", []))
    except PlexConnectionError as exc:
        result["status"] = "error"
        result["error_message"] = str(exc)
    except Exception as exc:
        result["status"] = "error"
        result["error_message"] = f"Unexpected update failure: {exc}"

    if persist_history:
        save_history_entry(result)
    return result
