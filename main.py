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
from bs4 import BeautifulSoup
import os
from plexapi.myplex import MyPlexAccount
from mutagen.easyid3 import EasyID3
import re
from datetime import datetime
import json
import subprocess

# Configuration (defaults, will be overridden by config.json)
PLEX_TOKEN = 'pU-m3HWYUZU6iXJFhJyA'  # Your Plex.tv token
SERVER_IP = '172.16.16.106'  # Your local server IP
PLAYLIST_NAME = 'Journey FM Recently Played'

def scrape_recently_played():
    """Scrape recently played songs from myjourneyfm.com using Selenium"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--remote-debugging-port=9222")
    options.add_argument("--user-data-dir=/tmp/chromium")
    options.add_argument("--no-first-run")
    options.add_argument("--disable-extensions")
    options.binary_location = "/usr/bin/chromium-browser"
    service = Service()
    driver = webdriver.Chrome(service=service, options=options)
    
    url = 'https://www.myjourneyfm.com/recently-played/'
    driver.get(url)
    
    # Wait for initial load
    time.sleep(5)
    
    # Click "View More" button if exists
    try:
        more_button = driver.find_element(By.ID, "moreSongs")
        more_button.click()
        time.sleep(5)  # Wait for more songs to load
    except:
        pass  # Button not found or already loaded
    
    html = driver.page_source
    driver.quit()
    
    # Optional: save HTML to file for debugging (comment out if not needed)
    # with open('page.html', 'w', encoding='utf-8') as f:
    #     f.write(html)
    
    soup = BeautifulSoup(html, 'html.parser')
    
    songs = []
    # Find elements (div, li) that contain time in their text
    song_elements = soup.find_all(lambda tag: tag.name in ['div', 'li', 'p'] and re.search(r'\d+:\d+ [AP]M', tag.get_text()))
    for element in song_elements:
        spans = element.find_all('span')
        if len(spans) >= 3:
            title = spans[0].get_text().strip()
            artist = spans[1].get_text().strip()
            # Ignore time
            songs.append({'artist': artist, 'title': title})
        else:
            # Fallback to text parsing
            full_text = element.get_text().strip()
            match = re.search(r'(\d+:\d+ [AP]M)', full_text)
            if match:
                play_time = match.group(1)
                before = full_text.split(play_time)[0].strip()
                if ' by ' in before:
                    title, artist = before.split(' by ', 1)
                    title = title.strip()
                    artist = artist.strip()
                else:
                    # Split on capital letters
                    parts = re.findall(r'[A-Z][^A-Z]*', before)
                    if len(parts) == 4:
                        title = ' '.join(parts[:2])
                        artist = ' '.join(parts[2:])
                    else:
                        title = ' '.join(parts[:3])
                        artist = ' '.join(parts[3:])
                if title and artist:
                    songs.append({'artist': artist, 'title': title})
    
    return songs

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
    """Create playlist in Plex and return added count and missing songs"""
    # Assuming Plex has a music library named 'Music'
    music_library = plex.library.section('Music')
    tracks = []
    seen_keys = set()  # Track which ratingKeys we've already added to prevent duplicates within this run
    missing = []
    
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
                        tracks.append(track)
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
                new_tracks = [track for track in tracks if track.ratingKey not in existing_keys]
                
                if new_tracks:
                    existing.addItems(new_tracks)
                    print(f"Added {len(new_tracks)} new songs to existing playlist '{playlist_name}':")
                    for track in new_tracks:
                        print(f"  + '{track.title}' by {track.artist().title}")
                    added = len(new_tracks)
                else:
                    print(f"No new songs to add - all {len(tracks)} matching songs already in playlist.")
                    added = 0
            except:
                # Playlist doesn't exist, create it
                plex.createPlaylist(playlist_name, tracks)
                print(f"Created playlist '{playlist_name}' with {len(tracks)} songs:")
                for track in tracks:
                    print(f"  + '{track.title}' by {track.artist().title}")
                added = len(tracks)
        except Exception as e:
            print(f"Error with playlist: {e}")
            added = 0
    else:
        print("No matching tracks found in Plex.")
        added = 0
    
    return added, missing

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

def prompt_for_scheduler():
    """Prompt user for scheduler setup"""
    setup = input("Do you want to set up a scheduled task? (y/n): ").strip().lower()
    if setup != 'y':
        return None
    print("Choose schedule type:")
    print("1. Interval (e.g., every 15 minutes)")
    print("2. At startup")
    print("3. Both")
    choice = input("Enter choice (1/2/3): ").strip()
    if choice == '1':
        interval = int(input("Enter interval number: ").strip())
        unit = input("Enter unit (Minutes/Hours/Days): ").strip()
        return {'Type': 'Interval', 'Interval': interval, 'Unit': unit}
    elif choice == '2':
        return {'Type': 'Startup'}
    elif choice == '3':
        return {'Type': 'Both'}
    else:
        print("Invalid choice.")
        return None

def setup_scheduler(params):
    """Run the setup_scheduler.ps1 with parameters"""
    cmd = ['powershell.exe', '-File', 'setup_scheduler.ps1']
    for k, v in params.items():
        cmd.extend(['-' + k, str(v)])
    try:
        subprocess.run(cmd, check=True)
        print("Scheduler setup completed.")
    except subprocess.CalledProcessError as e:
        print(f"Error setting up scheduler: {e}")

def main():
    global PLEX_TOKEN, SERVER_IP, PLAYLIST_NAME
    # Load or prompt for config
    if os.path.exists('config.json'):
        with open('config.json', 'r') as f:
            config = json.load(f)
        PLEX_TOKEN = config.get('PLEX_TOKEN', PLEX_TOKEN)
        SERVER_IP = config.get('SERVER_IP', SERVER_IP)
        PLAYLIST_NAME = config.get('PLAYLIST_NAME', PLAYLIST_NAME)
    else:
        # If no config file, use defaults (GUI should handle this)
        pass
    
    # Log start time
    start_time = datetime.now()
    print(f"\n{'='*60}")
    print(f"Journey FM Playlist Update - {start_time.strftime('%Y-%m-%d %I:%M:%S %p')}")
    print(f"{'='*60}\n")
    
    # Scrape songs
    songs = scrape_recently_played()
    print(f"Found {len(songs)} recently played songs.")
    
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
        print(f"Server at {SERVER_IP} not found in your claimed resources.")
        print("Please claim the server: Open http://172.16.16.106:32400/web, sign in with your Plex account, and follow the claim prompts.")
        return
    
    plex = server_resource.connect()
    print(f"Connected to server: {plex.friendlyName}, ID: {plex.machineIdentifier}")
    
    # Debug: list library sections
    print(f"Library sections: {[s.title for s in plex.library.sections()]}")
    
    # Debug: list existing playlists (handle unicode safely)
    playlists = plex.playlists()
    playlist_names = [p.title.encode('ascii', 'ignore').decode('ascii') if not p.title.isascii() else p.title for p in playlists]
    print(f"Existing playlists: {len(playlists)} total")
    
    # Find matching songs in local library (optional, since Plex search might suffice)
    # But to filter only those in local library, perhaps skip or adjust
    # For now, assume all scraped songs are to be added if found in Plex
    
    # Create playlist
    if songs:
        added, missing = create_playlist_in_plex(plex, songs, PLAYLIST_NAME)
    else:
        print("No songs found.")
        added, missing = 0, []
    
    # Create Amazon buy list for missing songs
    if missing:
        print(f"\n{len(missing)} songs not found in your library. Creating Amazon buy list...")
        with open('amazon_buy_list.txt', 'w') as f:
            f.write("Songs not in your library - Amazon search links:\n\n")
            for song in missing:
                artist = song['artist']
                title = song['title']
                # Create Amazon search URL
                query = f"{artist} {title}".replace(' ', '+')
                url = f"https://www.amazon.com/s?k={query}&i=digital-music"
                f.write(f"{artist} - {title}\n{url}\n\n")
                print(f"  - {artist} - {title}: {url}")
        print("Buy list saved to amazon_buy_list.txt")
    
    # Log completion
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    print(f"\nCompleted in {duration:.1f} seconds at {end_time.strftime('%I:%M:%S %p')}")
    print(f"{'='*60}\n")

if __name__ == '__main__':
    main()
