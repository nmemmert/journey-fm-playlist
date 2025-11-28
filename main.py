#!/usr/bin/env python3
"""
Journey FM Playlist Creator

This script scrapes recently played songs from myjourneyfm.com,
checks if they exist in the local music library,
creates a playlist of matching songs, and imports it into Plex.
"""

import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import os
from plexapi.myplex import MyPlexAccount
from mutagen.easyid3 import EasyID3
import re
from datetime import datetime
import json
import subprocess
import urllib.parse
import sqlite3
import urllib.parse

# Configuration (defaults, will be overridden by config.json)
PLEX_TOKEN = 'pU-m3HWYUZU6iXJFhJyA'  # Your Plex.tv token
SERVER_IP = '172.16.16.106'  # Your local server IP
PLAYLIST_NAME = 'Journey FM Recently Played'

def scrape_recently_played(selected_stations=None):
    """Scrape recently played songs from Journey FM and Spirit FM"""
    if selected_stations is None:
        selected_stations = ['journey_fm', 'spirit_fm']

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.binary_location = "/usr/bin/google-chrome-stable"
    
    service = Service(ChromeDriverManager().install())
    
    try:
        driver = webdriver.Chrome(service=service, options=options)
    except Exception as e:
        print(f"Failed to start Chrome: {e}")
        return []
    
    all_songs = []
    seen = set()
    
    # Journey FM - uses <strong> for title, normal text for artist
    if 'journey_fm' in selected_stations:
        try:
            print("Scraping Journey FM...")
            driver.get('https://www.myjourneyfm.com/recently-played/')
            time.sleep(5)
            
            # Click "View More" button if exists
            try:
                more_button = driver.find_element(By.ID, "moreSongs")
                more_button.click()
                time.sleep(5)
            except:
                pass
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # Find all song items using the proper class structure
            song_items = soup.find_all('div', class_='rp-item')
            
            for item in song_items:
                try:
                    title_elem = item.find('h5', class_='song-title')
                    artist_elem = item.find('p', class_='song-artist')
                    
                    if title_elem and artist_elem:
                        title = title_elem.get_text().strip()
                        artist = artist_elem.get_text().strip()
                        
                        if title and artist:
                            key = (title.lower(), artist.lower())
                            if key not in seen:
                                all_songs.append({'title': title, 'artist': artist, 'source': 'Journey FM'})
                                seen.add(key)
                                print(f"  Found: {title} by {artist}")
                except Exception as e:
                    continue
                    
        except Exception as e:
            print(f"Error scraping Journey FM: {e}")
    
    # Spirit FM - loads songs from iframe text file
    if 'spirit_fm' in selected_stations:
        try:
            print("Scraping Spirit FM...")
            driver.get('https://spiritfm.com/ajax/now_playing_history.txt')
            time.sleep(3)
            
            # Parse the plain text format: "Mon 01:45PM Artist - Title"
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            text_content = soup.get_text()
            
            # Split into lines and parse each
            for line in text_content.split('\n'):
                line = line.strip()
                if not line:
                    continue
                    
                # Match pattern: Day HH:MM(AM/PM) Artist - Title
                match = re.match(r'^\w+\s+\d+:\d+[AP]M\s+(.+?)\s+-\s+(.+)$', line)
                if match:
                    artist = match.group(1).strip()
                    title = match.group(2).strip()
                    
                    # Clean up HTML entities
                    artist = artist.replace('&amp;', '&')
                    title = title.replace('&amp;', '&')
                    
                    if title and artist:
                        key = (title.lower(), artist.lower())
                        if key not in seen:
                            all_songs.append({'title': title, 'artist': artist, 'source': 'Spirit FM'})
                            seen.add(key)
                            print(f"  Found: {title} by {artist}")
                    
        except Exception as e:
            print(f"Error scraping Spirit FM: {e}")
    
    driver.quit()
    
    print(f"\nTotal unique songs found: {len(all_songs)}")
    return all_songs

def normalize_string(s):
    """Normalize string for comparison"""
    return re.sub(r'[^\\w\\s]', '', s).lower().strip()

def find_song_in_library(artist, title, library_path):
    """Check if song exists in local library"""
    for root, dirs, files in os.walk(library_path):
        for file in files:
            if file.endswith(('.mp3', '.flac', '.m4a')):  # Add more formats if needed
                try:
                    audio = EasyID3(os.path.join(root, file))
                    file_artist = normalize_string(audio.get('artist', [''])[0])
                    file_title = normalize_string(audio.get('title', [''])[0])
                    if normalize_string(artist) == file_artist and normalize_string(title) == file_title:
                        return os.path.join(root, file)
                except:
                    continue
    return None

def create_playlist_in_plex(plex, songs, playlist_name):
    """Create playlist in Plex and return added count, added songs, and missing songs"""
    # Assuming Plex has a music library named 'Music'
    music_library = plex.library.section('Music')
    tracks = []
    seen_keys = set()  # Track which ratingKeys we've already added to prevent duplicates within this run
    missing = []
    added_songs = []
    
    for song in songs:
        # Clean title and artist by removing text in parentheses and normalizing spaces
        clean_title = re.sub(r'\([^)]*\)', '', song['title']).strip()
        clean_title = re.sub(r'\s+', ' ', clean_title)  # Replace multiple spaces with single space
        clean_artist = re.sub(r'\([^)]*\)', '', song['artist']).strip()
        clean_artist = re.sub(r'\s+', ' ', clean_artist)  # Replace multiple spaces with single space
        
        # Skip invalid entries
        if not clean_title or len(clean_title) < 3 or clean_title.lower() in ['by', 'recently played', 'now playing:', 'search']:
            continue
        
        # Skip entries that are ONLY punctuation (but allow titles with punctuation in them)
        if re.match(r'^[!?\\\\s]+$', clean_title):
            continue
        
        # Remove only ! and ? for searching, but keep apostrophes
        search_title = re.sub(r'[!?]', '', clean_title).strip()
        search_artist = re.sub(r'[!?]', '', clean_artist).strip()
        
        # Normalize & and + to "and" for both title and artist
        search_title = re.sub(r'\s*[&+]\s*', ' and ', search_title, flags=re.IGNORECASE)
        search_artist = re.sub(r'\s*[&+]\s*', ' and ', search_artist, flags=re.IGNORECASE)
        
        # Search for tracks by cleaned title
        results = music_library.searchTracks(title=search_title)
        if results:
            # Try to match by artist as well
            matched = False
            for track in results:
                track_artist = track.artist().title.lower()
                search_artist_lower = search_artist.lower()
                
                # Clean featured artists from search (e.g., "W/ Emerson Day", "feat. Someone")
                search_artist_main = re.sub(r'\s+(w/|feat\.||featuring|ft\.).*', '', search_artist_lower).strip()
                
                # Normalize & and + in track artist as well
                track_artist = re.sub(r'\s*[&+]\s*', ' and ', track_artist)
                
                # Check if artist matches (case-insensitive, partial match)
                # Match if main artist name is in the track artist or vice versa
                if (search_artist_main in track_artist or track_artist in search_artist_main or
                    search_artist_lower in track_artist or track_artist in search_artist_lower):
                    # Only add if we haven't already added this track in this run
                    if track.ratingKey not in seen_keys:
                        tracks.append((track, song))
                        seen_keys.add(track.ratingKey)
                    matched = True
                    break
            # If no artist match, skip this track (don't add wrong songs)
            if not matched:
                missing.append(song)
    
    added = 0
    if tracks:
        try:
            # Try to find existing playlist
            try:
                existing = plex.playlist(playlist_name)
                # Get existing track rating keys to avoid duplicates
                existing_keys = {item.ratingKey for item in existing.items()}
                # Filter out tracks already in playlist
                new_tracks = [track_song for track_song in tracks if track_song[0].ratingKey not in existing_keys]
                
                if new_tracks:
                    existing.addItems([ts[0] for ts in new_tracks])
                    for track, song in new_tracks:
                        # Auto-tag added songs
                        track.addLabel("Journey FM")
                        track.rate(5)
                    added = len(new_tracks)
                    added_songs.extend([f"{track.title} by {track.artist().title} ({song['source']})" for track, song in new_tracks])
                else:
                    added = 0
            except:
                # Playlist doesn't exist, create it
                plex.createPlaylist(playlist_name, [ts[0] for ts in tracks])
                for track, song in tracks:
                    # Auto-tag added songs
                    track.addLabel("Journey FM")
                    track.rate(5)
                added = len(tracks)
                added_songs.extend([f"{track.title} by {track.artist().title} ({song['source']})" for track, song in tracks])
        except Exception as e:
            added = 0
            added_songs = []
    else:
        print("No matching tracks found in Plex.")
        added = 0
        added_songs = []
    
    return added, added_songs, missing

def prompt_for_config():
    """Prompt user for configuration variables"""
    print("Configuration not found. Please provide the following:")
    plex_token = input("Enter your Plex token: ").strip()
    server_ip = input("Enter your Plex server IP: ").strip()
    playlist_name = input("Enter the playlist name: ").strip()
    config = {
        'PLEX_TOKEN': plex_token,
        'SERVER_IP': server_ip,
        'PLAYLIST_NAME': playlist_name
    }
    with open('config.json', 'w') as f:
        json.dump(config, f)
    return config

def init_history_db():
    """Initialize the history database"""
    conn = sqlite3.connect('playlist_history.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY,
        date TEXT,
        added_count INTEGER,
        added_songs TEXT,
        missing_count INTEGER,
        missing_songs TEXT
    )''')
    conn.commit()
    conn.close()

def save_history_entry(added_count, added_songs, missing_count, missing_songs):
    """Save a history entry to the database"""
    conn = sqlite3.connect('playlist_history.db')
    c = conn.cursor()
    date = datetime.now().isoformat()
    c.execute('INSERT INTO history (date, added_count, added_songs, missing_count, missing_songs) VALUES (?, ?, ?, ?, ?)',
              (date, added_count, json.dumps(added_songs), missing_count, json.dumps(missing_songs)))
    conn.commit()
    conn.close()

def setup_scheduler(params):
    """Run the setup_scheduler.ps1 with parameters"""
    cmd = ['powershell.exe', '-File', 'setup_scheduler.ps1']
    for k, v in params.items():
        cmd.extend(['-' + k, str(v)])
    try:
        subprocess.run(cmd, check=True)
        print("Scheduler setup completed.")
    except subprocess.CalledProcessError as e:
        print(f"Scheduler setup failed: {e}")

def main():
    global PLEX_TOKEN, SERVER_IP, PLAYLIST_NAME
    # Load or prompt for config
    selected_stations = ['journey_fm', 'spirit_fm']  # default
    if os.path.exists('config.json'):
        with open('config.json', 'r') as f:
            config = json.load(f)
        PLEX_TOKEN = config.get('PLEX_TOKEN', PLEX_TOKEN)
        SERVER_IP = config.get('SERVER_IP', SERVER_IP)
        PLAYLIST_NAME = config.get('PLAYLIST_NAME', PLAYLIST_NAME)
        # Load selected stations
        selected_stations_str = config.get('SELECTED_STATIONS', 'journey_fm,spirit_fm')
        if isinstance(selected_stations_str, str):
            selected_stations = selected_stations_str.split(',')
    else:
        # If no config file, use defaults (GUI should handle this)
        pass
    
    # Log start time
    start_time = datetime.now()
    
    # Initialize history database
    init_history_db()
    
    # Scrape songs with selected stations
    songs = scrape_recently_played(selected_stations)
    
    # Connect to Plex via MyPlexAccount
    account = MyPlexAccount(token=PLEX_TOKEN)
    resources = account.resources()
    
    # Find the server by IP
    server_resource = None
    for r in resources:
        for conn in r.connections:
            if SERVER_IP in conn.address:
                server_resource = r
                break
        if server_resource:
            break
    
    if not server_resource:
        print("Please claim the server: Open http://172.16.16.106:32400/web, sign in with your Plex account, and follow the claim prompts.")
        return
    
    plex = server_resource.connect()
    
    # Debug: list library sections
    
    # Debug: list existing playlists (handle unicode safely)
    playlists = plex.playlists()
    playlist_names = [p.title.encode('ascii', 'ignore').decode('ascii') if not p.title.isascii() else p.title for p in playlists]
    
    # Find matching songs in local library (optional, since Plex search might suffice)
    # But to filter only those in local library, perhaps skip or adjust
    # For now, assume all scraped songs are to be added if found in Plex
    
    # Create playlist
    if songs:
        added, added_songs, missing = create_playlist_in_plex(plex, songs, PLAYLIST_NAME)
    else:
        print("No songs found.")
        added, added_songs, missing = 0, [], []
    
    # Save to history
    save_history_entry(added, added_songs, len(missing), missing)
    
    # Create Amazon buy list for missing songs
    if missing:
        
        # Read existing buy list
        existing_songs = set()
        if os.path.exists('amazon_buy_list.txt'):
            try:
                with open('amazon_buy_list.txt', 'r') as f:
                    content = f.read()
                lines = content.split('\n')
                i = 0
                while i < len(lines):
                    if lines[i].startswith('Songs not in your library'):
                        i += 2  # Skip header
                        continue
                    if lines[i].strip() and not lines[i].startswith('http'):
                        if ' - ' in lines[i]:
                            artist, title = lines[i].split(' - ', 1)
                            existing_songs.add((artist.strip(), title.strip()))
                    i += 1
            except Exception as e:
                pass
        
        # Filter new missing songs
        new_missing = []
        for song in missing:
            key = (song['artist'], song['title'])
            if key not in existing_songs:
                new_missing.append(song)
                existing_songs.add(key)
        
        if new_missing:
            with open('amazon_buy_list.txt', 'a') as f:  # Append mode
                if not os.path.exists('amazon_buy_list.txt') or os.path.getsize('amazon_buy_list.txt') == 0:
                    f.write("Songs not in your library - Amazon search links:\n\n")
                for song in new_missing:
                    artist = song['artist']
                    title = song['title']
                    # Create Amazon search URL
                    query = urllib.parse.quote(f"{artist} {title}")
                    url = f"https://www.amazon.com/s?k={query}&i=digital-music"
                    f.write(f"{artist} - {title}\n{url}\n\n")
        else:
            print("No new songs to add to buy list.")
        
        print("Buy list updated.")
    
    # Log completion
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

def update_playlist():
    """Function to update playlist, callable from GUI"""
    main()

if __name__ == '__main__':
    main()
