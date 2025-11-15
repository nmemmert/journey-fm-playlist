# Journey FM Playlist Creator

This script automates the process of creating a Plex playlist from recently played songs on My Journey FM radio station.

## Features

- Scrapes recently played songs from https://www.myjourneyfm.com/recently-played/
- Checks your local music library for matching songs
- Creates a playlist in Plex with the found songs

## Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Configure the script:
   - Set `PLEX_URL` to your Plex server URL
   - Set `PLEX_TOKEN` to your Plex authentication token
   - Set `MUSIC_LIBRARY_PATH` to the path of your music library
3. Run the script: `python main.py`

## Requirements

- Python 3.6+
- Plex server
- Local music library with ID3 tags

## Note

The HTML scraping part may need adjustment based on the actual structure of the website. Inspect the page to find the correct selectors for artist and title.