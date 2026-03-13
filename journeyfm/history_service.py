import json
import sqlite3
from datetime import datetime

from journeyfm.paths import data_path

HISTORY_COLUMNS = {
    "status": "TEXT DEFAULT 'success'",
    "scraped_count": "INTEGER DEFAULT 0",
    "matched_count": "INTEGER DEFAULT 0",
    "duplicate_count": "INTEGER DEFAULT 0",
    "skipped_count": "INTEGER DEFAULT 0",
    "station_breakdown": "TEXT DEFAULT '[]'",
    "skipped_songs": "TEXT DEFAULT '[]'",
    "error_message": "TEXT DEFAULT ''",
}


def init_history_db(db_path=None):
    db_path = db_path or data_path("playlist_history.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY,
            date TEXT,
            added_count INTEGER,
            added_songs TEXT,
            missing_count INTEGER,
            missing_songs TEXT
        )
        """
    )
    cursor.execute("PRAGMA table_info(history)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    for column_name, definition in HISTORY_COLUMNS.items():
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE history ADD COLUMN {column_name} {definition}")
    conn.commit()
    conn.close()


def save_history_entry(result, db_path=None):
    db_path = db_path or data_path("playlist_history.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO history (
            date, added_count, added_songs, missing_count, missing_songs,
            status, scraped_count, matched_count, duplicate_count, skipped_count,
            station_breakdown, skipped_songs, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            result.get("added_count", 0),
            json.dumps(result.get("added_songs", [])),
            result.get("missing_count", 0),
            json.dumps(result.get("missing_songs", [])),
            result.get("status", "success"),
            result.get("scraped_count", 0),
            result.get("matched_count", 0),
            result.get("duplicate_count", 0),
            result.get("skipped_count", 0),
            json.dumps(result.get("station_breakdown", [])),
            json.dumps(result.get("skipped_songs", [])),
            result.get("error_message", ""),
        ),
    )
    conn.commit()
    conn.close()
