import json
import sqlite3
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from journeyfm.config_store import load_runtime_config
from journeyfm.paths import data_path
from journeyfm.update_service import run_update_job
from journeyfm.config_store import load_runtime_config
from journeyfm.update_service import run_update_job

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def load_recent_stats(db_path=None):
    db_path = db_path or data_path("playlist_history.db")
    stats = {
        "total_updates": 0,
        "total_scraped": 0,
        "total_matched": 0,
        "total_added": 0,
        "total_missing": 0,
        "total_duplicates": 0,
        "total_skipped": 0,
        "last_attempted": None,
        "last_success": None,
        "station_counts": {},
        "song_counts": {},
    }

    if not Path(db_path).exists():
        return stats

    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*), SUM(scraped_count), SUM(matched_count), SUM(added_count), SUM(missing_count), SUM(duplicate_count), SUM(skipped_count) FROM history"
        )
        row = c.fetchone() or ()
        stats["total_updates"] = int(row[0] or 0)
        stats["total_scraped"] = int(row[1] or 0)
        stats["total_matched"] = int(row[2] or 0)
        stats["total_added"] = int(row[3] or 0)
        stats["total_missing"] = int(row[4] or 0)
        stats["total_duplicates"] = int(row[5] or 0)
        stats["total_skipped"] = int(row[6] or 0)

        c.execute("SELECT MAX(date), MAX(CASE WHEN status='success' THEN date END) FROM history")
        last_row = c.fetchone() or ()
        stats["last_attempted"] = last_row[0]
        stats["last_success"] = last_row[1]

        c.execute("SELECT station_breakdown, scraped_songs FROM history")
        station_rows = c.fetchall()
        for station_json, scraped_songs_json in station_rows:
            try:
                for station in json.loads(station_json or "[]"):
                    if station.get("success"):
                        key = station.get("display_name") or station.get("station") or "Unknown"
                        stats["station_counts"][key] = stats["station_counts"].get(key, 0) + int(station.get("scraped_count", 0))
            except Exception:
                pass

            try:
                songs = json.loads(scraped_songs_json or "[]")
                if "seen_song_keys" not in stats:
                    stats["seen_song_keys"] = set()
                for song in songs:
                    station_name = song.get("source", "Unknown")
                    title = song.get("title", "?")
                    artist = song.get("artist", "?")
                    key = (station_name, artist, title)
                    if key in stats["seen_song_keys"]:
                        continue
                    stats["seen_song_keys"].add(key)
                    display_key = f"{artist} - {title}"
                    stats["song_counts"].setdefault(station_name, {})
                    stats["song_counts"][station_name][display_key] = stats["song_counts"][station_name].get(display_key, 0) + 1
            except Exception:
                pass
    finally:
        conn.close()

    return stats


def load_history_entries(db_path=None, limit=100):
    db_path = db_path or data_path("playlist_history.db")
    rows = []
    if not Path(db_path).exists():
        return rows
    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id, date, status, scraped_count, matched_count, added_count, missing_count, duplicate_count, skipped_count, station_breakdown FROM history ORDER BY date DESC LIMIT ?",
            (limit,)
        )
        result = c.fetchall()
        for r in result:
            rows.append({
                "id": r[0],
                "date": r[1],
                "status": r[2],
                "scraped_count": r[3],
                "matched_count": r[4],
                "added_count": r[5],
                "missing_count": r[6],
                "duplicate_count": r[7],
                "skipped_count": r[8],
                "station_breakdown": json.loads(r[9] or '[]'),
            })
    except Exception:
        return []
    finally:
        conn.close()
    return rows


def load_buy_list(buy_list_path=None):
    buy_list_path = buy_list_path or data_path("amazon_buy_list.txt")
    if not Path(buy_list_path).exists():
        return []
    entries = []
    try:
        with open(buy_list_path, 'r', encoding='utf-8') as f:
            lines = [ln.strip() for ln in f if ln.strip()]
            for ln in lines:
                if ln.startswith('http'):
                    continue
                entries.append(ln)
    except Exception:
        return []
    return entries


def render_dashboard_html(stats):
    title = "Journey FM Song Count Command Center"
    station_rows = "".join(
        f"<tr><td>{name}</td><td>{count}</td></tr>" for name, count in sorted(stats["station_counts"].items())
    )
    overall_count = sum(stats["station_counts"].values())

    # Build a flattened station-song ranking table for display
    top_song_rows = []
    for station_name, songs in sorted(stats.get("song_counts", {}).items()):
        sorted_songs = sorted(songs.items(), key=lambda kv: kv[1], reverse=True)
        for song_name, count in sorted_songs[:10]:
            top_song_rows.append(f"<tr><td>{station_name}</td><td>{song_name}</td><td>{count}</td></tr>")
    top_song_rows_html = ''.join(top_song_rows) or '<tr><td colspan="3">No song counts yet</td></tr>'

    template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title><!--TITLE--></title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; background: linear-gradient(135deg, #12163f 0%, #192a66 100%); color: #ffffff; }
        .container { max-width: 960px; margin: 2.5rem auto; padding: 2rem; background: rgba(255, 255, 255, .08); border-radius: 20px; box-shadow: 0 15px 45px rgba(0,0,0,.35); }
        h1 { margin-bottom: .25rem; font-size: 2.4rem; letter-spacing: 1px; }
        p.subtitle { color: #e3e8ff; margin: 0 0 1.6rem; }
        .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 1rem; }
        .stat-card { background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28); padding: 1rem 1rem; border-radius: 12px; }
        .stat-card h2 { margin: .2rem 0; font-size: 1.3rem; }
        .table-wrap { margin-top: 1.5rem; overflow-x: auto; }
        table { width: 100%; border-collapse: collapse; color: #f7f8ff; }
        th, td { text-align: left; padding: .7rem 0.8rem; border-bottom: 1px solid rgba(255,255,255,0.2); }
        th { text-transform: uppercase; font-size: .9rem; letter-spacing: .08em; color: #cdd5ff; }
        .footer { margin-top: 2rem; font-size: .9rem; color: #d6d9ff; }
        .button { background: linear-gradient(135deg,#34caff,#5f76ff); color:#fff; border:none; padding:.85rem 1.15rem; border-radius: 9px; text-decoration:none; font-weight:700; display:inline-block; margin-top:1rem; }
        .tab-bar { margin-bottom: 1rem; }
        .tab-button { background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.28); color: #ffffff; padding: 8px 14px; margin-right: 6px; border-radius: 8px; cursor: pointer; }
        .tab-button.active { background: #ffffff; color: #192a66; font-weight: 700; }
        .tab-content { display: none; }
        .tab-content.active { display: block; }
        body { opacity: 0; transition: opacity 0.8s ease; }
        body.loaded { opacity: 1; }
        #refresh-status { display: inline-block; margin-left: 10px; color: #a6d8ff; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Journey FM Song Count Command Center</h1>
        <p class="subtitle">Live track count breakdown by station with overall totals and history-driven health metrics.</p>

        <div class="tab-bar">
            <button class="tab-button active" data-tab="overview">Overview</button>
            <button class="tab-button" data-tab="stations">Stations</button>
            <button class="tab-button" data-tab="top-songs">Top Songs</button>
            <button class="tab-button" data-tab="app">App Controls</button>
            <button class="tab-button" data-tab="buy-list">Buy List</button>
            <button class="tab-button" data-tab="history">History</button>
            <button class="tab-button" data-tab="raw-api">Raw API</button>
        </div>

        <div id="overview" class="tab-content active">
            <div class="stats-grid">
                <div class="stat-card"><h2>Overall Find</h2><p><!--OVERALL_COUNT--></p></div>
                <div class="stat-card"><h2>Total Scraped</h2><p><!--TOTAL_SCRAPED--></p></div>
                <div class="stat-card"><h2>Total Matched</h2><p><!--TOTAL_MATCHED--></p></div>
                <div class="stat-card"><h2>Missing / Buy List</h2><p><!--TOTAL_MISSING--></p></div>
                <div class="stat-card"><h2>Duplicates</h2><p><!--TOTAL_DUPLICATES--></p></div>
                <div class="stat-card"><h2>Updates Run</h2><p><!--TOTAL_UPDATES--></p></div>
            </div>
        </div>

        <div id="stations" class="tab-content">
            <h3>Station totals</h3>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Station</th><th>Scraped this run</th></tr></thead>
                    <tbody><!--STATION_ROWS--></tbody>
                </table>
            </div>
        </div>

        <div id="top-songs" class="tab-content">
            <h3>Top tracks per station (historical play counts)</h3>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Station</th><th>Song</th><th>Count</th></tr></thead>
                    <tbody><!--TOP_SONG_ROWS--></tbody>
                </table>
            </div>
        </div>

        <div id="app" class="tab-content">
            <h3>App Controls (desktop features)</h3>
            <button class="button" onclick="refreshStats()">Update Playlist</button>
            <button class="button" onclick="previewStats()" style="margin-left:10px;">Preview Sync</button>
            <button class="button" onclick="fetchBuyList()" style="margin-left:10px;">Load Buy List</button>
            <button class="button" onclick="fetchHistory()" style="margin-left:10px;">Load History</button>
            <div id="app-result" style="margin-top:1rem; color:#d4ebe6;"></div>
        </div>

        <div id="buy-list" class="tab-content">
            <h3>Buy List</h3>
            <ul id="buy-list-items" style="padding-left:16px;"></ul>
        </div>

        <div id="history" class="tab-content">
            <h3>Run History</h3>
            <div class="table-wrap">
                <table>
                    <thead><tr><th>Date</th><th>Status</th><th>Scraped</th><th>Matched</th><th>Added</th><th>Missing</th><th>Duplicates</th><th>Skipped</th></tr></thead>
                    <tbody id="history-rows"></tbody>
                </table>
            </div>
        </div>

        <div id="raw-api" class="tab-content">
            <h3>Raw API snapshot</h3>
            <pre id="raw-data">Loading…</pre>
        </div>

        <div class="footer">
            Last attempted run: <!--LAST_ATTEMPTED--><br>
            Last successful run: <!--LAST_SUCCESS-->
        </div>

        <button class="button" id="refresh-button" onclick="refreshStats()">Refresh Now (scrape fresh data)</button>
        <span id="refresh-status"></span>
        <a class="button" href="/api/stats" style="margin-left:10px;">Download JSON stats</a>
    </div>

    <script>
        function setActiveTab(tabId) {
            document.querySelectorAll('.tab-button').forEach(function(btn) {
                btn.classList.toggle('active', btn.dataset.tab === tabId);
            });
            document.querySelectorAll('.tab-content').forEach(function(content) {
                content.classList.toggle('active', content.id === tabId);
            });
            if (tabId === 'raw-api') {
                refreshRawApi();
            }
        }

        document.addEventListener('DOMContentLoaded', function() {
            document.body.classList.add('loaded');
            document.querySelectorAll('.tab-button').forEach(function(btn) {
                btn.addEventListener('click', function() {
                    setActiveTab(this.dataset.tab);
                });
            });
            setActiveTab('overview');
        });

        function refreshRawApi() {
            var raw = document.getElementById('raw-data');
            raw.textContent = 'Loading...';
            fetch('/api/stats')
                .then(function(response) {
                    return response.json();
                })
                .then(function(data) {
                    raw.textContent = JSON.stringify(data, null, 2);
                })
                .catch(function(err) {
                    raw.textContent = 'Error loading API: ' + err;
                });
        }

        function refreshStats() {
            var status = document.getElementById('refresh-status');
            status.textContent = 'Refreshing ...';
            fetch('/api/refresh')
                .then(function(response) {
                    if (!response.ok) {
                        throw new Error('HTTP ' + response.status);
                    }
                    return response.json();
                })
                .then(function(data) {
                    if (data.status === 'ok') {
                        status.textContent = 'Refresh complete';
                        document.getElementById('app-result').textContent = JSON.stringify(data.result, null, 2);
                    } else {
                        status.textContent = 'Refresh failed';
                        document.getElementById('app-result').textContent = JSON.stringify(data, null, 2);
                    }
                    setTimeout(function() { status.textContent = ''; }, 4500);
                    setTimeout(function() { location.reload(); }, 1000);
                })
                .catch(function(err) {
                    status.textContent = 'Error: ' + err;
                    setTimeout(function() { status.textContent = ''; }, 6500);
                });
        }

        function previewStats() {
            var status = document.getElementById('refresh-status');
            status.textContent = 'Previewing ...';
            fetch('/api/preview')
                .then(function(response) { return response.json(); })
                .then(function(data) {
                    status.textContent = 'Preview complete';
                    document.getElementById('app-result').textContent = JSON.stringify(data, null, 2);
                    setTimeout(function() { status.textContent = ''; }, 4500);
                })
                .catch(function(err) {
                    status.textContent = 'Error: ' + err;
                    setTimeout(function() { status.textContent = ''; }, 6500);
                });
        }

        function fetchBuyList() {
            fetch('/api/buy-list')
                .then(function(response) { return response.json(); })
                .then(function(data) {
                    var container = document.getElementById('buy-list-items');
                    container.innerHTML = '';
                    data.forEach(function(item) {
                        var li = document.createElement('li');
                        li.textContent = item;
                        container.appendChild(li);
                    });
                    document.getElementById('app-result').textContent = 'Loaded buy list (' + data.length + ' items).';
                })
                .catch(function(err) {
                    document.getElementById('app-result').textContent = 'Error loading buy list: ' + err;
                });
        }

        function fetchHistory() {
            fetch('/api/history')
                .then(function(response) { return response.json(); })
                .then(function(data) {
                    var rows = document.getElementById('history-rows');
                    rows.innerHTML = '';
                    data.forEach(function(item) {
                        var tr = document.createElement('tr');
                        tr.innerHTML = '<td>' + item.date + '</td>' +
                            '<td>' + item.status + '</td>' +
                            '<td>' + item.scraped_count + '</td>' +
                            '<td>' + item.matched_count + '</td>' +
                            '<td>' + item.added_count + '</td>' +
                            '<td>' + item.missing_count + '</td>' +
                            '<td>' + item.duplicate_count + '</td>' +
                            '<td>' + item.skipped_count + '</td>';
                        rows.appendChild(tr);
                    });
                    document.getElementById('app-result').textContent = 'Loaded history (' + data.length + ' rows).';
                })
                .catch(function(err) {
                    document.getElementById('app-result').textContent = 'Error loading history: ' + err;
                });
        }
    </script>
</body>
</html>
"""

    return (
        template
        .replace("<!--TITLE-->", title)
        .replace("<!--OVERALL_COUNT-->", f"{overall_count:,}")
        .replace("<!--TOTAL_SCRAPED-->", f"{stats['total_scraped']:,}")
        .replace("<!--TOTAL_MATCHED-->", f"{stats['total_matched']:,}")
        .replace("<!--TOTAL_MISSING-->", f"{stats['total_missing']:,}")
        .replace("<!--TOTAL_DUPLICATES-->", f"{stats['total_duplicates']:,}")
        .replace("<!--TOTAL_UPDATES-->", f"{stats['total_updates']:,}")
        .replace("<!--STATION_ROWS-->", station_rows or '<tr><td colspan="2">No station data yet</td></tr>')
        .replace("<!--TOP_SONG_ROWS-->", top_song_rows_html)
        .replace("<!--LAST_ATTEMPTED-->", stats['last_attempted'] or 'N/A')
        .replace("<!--LAST_SUCCESS-->", stats['last_success'] or 'N/A')
    )


def _build_handler(stats_supplier):
    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/stats", "/index.html"):
                stats = stats_supplier()
                content = render_dashboard_html(stats).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            elif self.path == "/api/stats":
                stats = stats_supplier()
                content = json.dumps(stats, default=str).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            elif self.path == "/api/refresh":
                try:
                    result = run_update_job(load_runtime_config())
                    response = {"status": "ok", "result": result}
                    content = json.dumps(response, default=str).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                except Exception as exc:
                    trace = traceback.format_exc()
                    response = {
                        "status": "error",
                        "message": str(exc),
                        "trace": trace,
                    }
                    content = json.dumps(response, default=str).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
            elif self.path == "/api/preview":
                try:
                    result = run_update_job(load_runtime_config(), dry_run=True, persist_history=False, write_buy_list=False)
                    content = json.dumps(result, default=str).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                except Exception as exc:
                    response = {"status": "error", "message": str(exc)}
                    content = json.dumps(response, default=str).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
            elif self.path == "/api/buy-list":
                try:
                    entries = load_buy_list()
                    content = json.dumps(entries, default=str).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                except Exception as exc:
                    response = {"status": "error", "message": str(exc)}
                    content = json.dumps(response, default=str).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
            elif self.path == "/api/history":
                try:
                    history = load_history_entries()
                    content = json.dumps(history, default=str).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                except Exception as exc:
                    response = {"status": "error", "message": str(exc)}
                    content = json.dumps(response, default=str).encode("utf-8")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
            else:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"404 Not Found")

        def log_message(self, format, *args):
            # Keep server quiet; logging handled elsewhere
            pass

    return DashboardHandler


def start_dashboard_server(host=DEFAULT_HOST, port=DEFAULT_PORT, open_browser_if_possible=True):
    server_address = (host, port)
    httpd = HTTPServer(server_address, _build_handler(load_recent_stats))

    def serve():
        try:
            if open_browser_if_possible:
                webbrowser.open(f"http://{host}:{port}")
            print(f"Dashboard available at http://{host}:{port}/")
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return httpd, thread


def stop_dashboard_server(httpd):
    try:
        httpd.shutdown()
    except Exception:
        pass


def get_dashboard_url(host=DEFAULT_HOST, port=DEFAULT_PORT):
    return f"http://{host}:{port}/"
