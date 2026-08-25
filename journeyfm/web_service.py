import json
import logging
import queue
import sqlite3
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from journeyfm.config_store import get_secret, load_runtime_config, save_runtime_config
from journeyfm.paths import data_path
from journeyfm.update_service import run_update_job

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

_sync_state = {"running": False}
_sync_lock = threading.Lock()


class _QueueLogHandler(logging.Handler):
    def __init__(self, q):
        super().__init__()
        self.q = q
        self.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    def emit(self, record):
        try:
            self.q.put_nowait(self.format(record))
        except Exception:
            pass


# ── Data loaders ──────────────────────────────────────────────

def load_recent_stats(db_path=None):
    db_path = db_path or data_path("playlist_history.db")
    stats = {
        "total_updates": 0, "total_scraped": 0, "total_matched": 0,
        "total_added": 0, "total_missing": 0, "total_duplicates": 0,
        "total_skipped": 0, "last_attempted": None, "last_success": None,
        "station_counts": {}, "song_counts": {},
    }
    if not Path(db_path).exists():
        return stats
    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*), SUM(added_count), SUM(duplicate_count), SUM(skipped_count) FROM history"
        )
        row = c.fetchone() or ()
        stats["total_updates"] = int(row[0] or 0)
        stats["total_added"] = int(row[1] or 0)
        stats["total_duplicates"] = int(row[2] or 0)
        stats["total_skipped"] = int(row[3] or 0)
        c.execute("SELECT MAX(date), MAX(CASE WHEN status='success' THEN date END) FROM history")
        last_row = c.fetchone() or ()
        stats["last_attempted"] = last_row[0]
        stats["last_success"] = last_row[1]
        c.execute("SELECT scraped_songs, missing_songs FROM history")
        scraped_seen = set()
        missing_seen = set()
        for scraped_songs_json, missing_songs_json in c.fetchall():
            try:
                for song in json.loads(scraped_songs_json or "[]"):
                    sname = song.get("source", "Unknown")
                    title = song.get("title", "?")
                    artist = song.get("artist", "?")
                    k = (artist, title)
                    if k not in scraped_seen:
                        scraped_seen.add(k)
                        stats["song_counts"].setdefault(sname, {})
                        dk = f"{artist} - {title}"
                        stats["song_counts"][sname][dk] = stats["song_counts"][sname].get(dk, 0) + 1
            except Exception:
                pass
            try:
                for song in json.loads(missing_songs_json or "[]"):
                    artist = song.get("artist", "?")
                    title = song.get("title", "?")
                    missing_seen.add((artist, title))
            except Exception:
                pass
        for sname, songs in stats["song_counts"].items():
            stats["station_counts"][sname] = len(songs)
        stats["total_scraped"] = len(scraped_seen)
        stats["total_missing"] = len(missing_seen)
        # matched from most recent successful run (per-run count is accurate)
        c.execute(
            "SELECT matched_count FROM history WHERE status='success' ORDER BY date DESC LIMIT 1"
        )
        r = c.fetchone()
        stats["total_matched"] = int(r[0] or 0) if r else 0
    finally:
        conn.close()
    return stats


def load_history_entries(db_path=None, limit=200):
    db_path = db_path or data_path("playlist_history.db")
    if not Path(db_path).exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()
        c.execute(
            "SELECT id, date, status, scraped_count, matched_count, added_count,"
            " missing_count, duplicate_count, skipped_count, station_breakdown"
            " FROM history ORDER BY date DESC LIMIT ?", (limit,)
        )
        return [
            {"id": r[0], "date": r[1], "status": r[2], "scraped_count": r[3],
             "matched_count": r[4], "added_count": r[5], "missing_count": r[6],
             "duplicate_count": r[7], "skipped_count": r[8],
             "station_breakdown": json.loads(r[9] or "[]")}
            for r in c.fetchall()
        ]
    except Exception:
        return []
    finally:
        conn.close()


def load_buy_list(buy_list_path=None):
    buy_list_path = buy_list_path or data_path("amazon_buy_list.txt")
    if not Path(buy_list_path).exists():
        return []
    try:
        with open(buy_list_path, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()
                    and not ln.startswith("http")
                    and ln.strip() != "Songs not in your library - Amazon search links:"]
    except Exception:
        return []


def load_buy_list_rich(buy_list_path=None):
    buy_list_path = buy_list_path or data_path("amazon_buy_list.txt")
    if not Path(buy_list_path).exists():
        return []
    entries = []
    try:
        with open(buy_list_path, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        i = 0
        while i < len(lines):
            line = lines[i]
            if not line or line.startswith("Songs not in") or line.startswith("http"):
                i += 1
                continue
            url = None
            if i + 1 < len(lines) and lines[i + 1].startswith("http"):
                url = lines[i + 1]
                i += 2
            else:
                i += 1
            entries.append({"song": line, "url": url})
    except Exception:
        return []
    return entries


def dedup_buy_list(buy_list_path=None):
    buy_list_path = buy_list_path or data_path("amazon_buy_list.txt")
    entries = load_buy_list_rich(buy_list_path)
    seen = set()
    unique = []
    for e in entries:
        key = e["song"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(e)
    removed = len(entries) - len(unique)
    with open(buy_list_path, "w", encoding="utf-8") as f:
        f.write("Songs not in your library - Amazon search links:\n\n")
        for e in unique:
            f.write(f"{e['song']}\n")
            if e["url"]:
                f.write(f"{e['url']}\n\n")
            else:
                f.write("\n")
    return {"original": len(entries), "removed": removed, "remaining": len(unique)}


# ── Config ────────────────────────────────────────────────────

def get_web_config():
    config = load_runtime_config()
    token = config.get("PLEX_TOKEN", "")
    config["_has_token"] = bool(token)
    config["PLEX_TOKEN"] = ""
    stations = config.get("SELECTED_STATIONS", [])
    if isinstance(stations, str):
        stations = [s.strip() for s in stations.split(",") if s.strip()]
    config["SELECTED_STATIONS"] = stations
    return config


def save_web_config(data):
    config = {}
    config["SERVER_IP"] = str(data.get("SERVER_IP", "")).strip()
    config["PLAYLIST_NAME"] = str(data.get("PLAYLIST_NAME", "")).strip()
    stations = data.get("SELECTED_STATIONS", [])
    if isinstance(stations, str):
        stations = [s.strip() for s in stations.split(",") if s.strip()]
    config["SELECTED_STATIONS"] = stations
    config["AUTO_UPDATE"] = bool(data.get("AUTO_UPDATE", False))
    try:
        config["UPDATE_INTERVAL"] = int(data.get("UPDATE_INTERVAL", 15))
    except (ValueError, TypeError):
        config["UPDATE_INTERVAL"] = 15
    config["UPDATE_UNIT"] = str(data.get("UPDATE_UNIT", "Minutes"))
    token = str(data.get("PLEX_TOKEN", "")).strip()
    config["PLEX_TOKEN"] = token if token else get_secret("PLEX_TOKEN")
    save_runtime_config(config)


# ── Playlist ──────────────────────────────────────────────────

def get_playlist_tracks():
    from journeyfm.plex_service import connect_to_plex_server
    config = load_runtime_config()
    plex = connect_to_plex_server(config.get("PLEX_TOKEN", ""), config.get("SERVER_IP", ""))
    name = config.get("PLAYLIST_NAME", "")
    playlist = plex.playlist(name)
    tracks = []
    for item in playlist.items():
        tracks.append({
            "title": item.title,
            "artist": getattr(item, "grandparentTitle", ""),
            "album": getattr(item, "parentTitle", ""),
            "rating_key": str(item.ratingKey),
            "duration_ms": item.duration or 0,
        })
    return {"name": name, "tracks": tracks}


def remove_playlist_tracks(rating_keys):
    from journeyfm.plex_service import connect_to_plex_server
    config = load_runtime_config()
    plex = connect_to_plex_server(config.get("PLEX_TOKEN", ""), config.get("SERVER_IP", ""))
    name = config.get("PLAYLIST_NAME", "")
    playlist = plex.playlist(name)
    keys = set(str(k) for k in rating_keys)
    to_remove = [item for item in playlist.items() if str(item.ratingKey) in keys]
    if to_remove:
        playlist.removeItems(to_remove)
    return len(to_remove)


# ── HTML ──────────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Journey FM</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0b0c14;--sf:#141624;--sf2:#1c1e2e;--bd:rgba(255,255,255,.06);
  --am:#f0a040;--am-d:rgba(240,160,64,.13);
  --bl:#4a9eff;--bl-d:rgba(74,158,255,.13);
  --gr:#3ec87a;--gr-d:rgba(62,200,122,.13);
  --rd:#e05555;--rd-d:rgba(224,85,85,.13);
  --tx:#bec2d8;--mt:#505870;--st:#e2e6f2;
  --sb:220px
}
@media(prefers-color-scheme:light){:root:not([data-theme="dark"]){
  --bg:#eff0f6;--sf:#fff;--sf2:#e4e7f2;--bd:rgba(0,0,0,.07);
  --am:#b87018;--am-d:rgba(184,112,24,.1);
  --bl:#1658cc;--bl-d:rgba(22,88,204,.08);
  --gr:#1a7a48;--gr-d:rgba(26,122,72,.08);
  --rd:#c02828;--rd-d:rgba(192,40,40,.08);
  --tx:#2c3048;--mt:#7a80a0;--st:#0e1020
}}
:root[data-theme="light"]{
  --bg:#eff0f6;--sf:#fff;--sf2:#e4e7f2;--bd:rgba(0,0,0,.07);
  --am:#b87018;--am-d:rgba(184,112,24,.1);
  --bl:#1658cc;--bl-d:rgba(22,88,204,.08);
  --gr:#1a7a48;--gr-d:rgba(26,122,72,.08);
  --rd:#c02828;--rd-d:rgba(192,40,40,.08);
  --tx:#2c3048;--mt:#7a80a0;--st:#0e1020
}
:root[data-theme="dark"]{
  --bg:#0b0c14;--sf:#141624;--sf2:#1c1e2e;--bd:rgba(255,255,255,.06);
  --am:#f0a040;--am-d:rgba(240,160,64,.13);
  --bl:#4a9eff;--bl-d:rgba(74,158,255,.13);
  --gr:#3ec87a;--gr-d:rgba(62,200,122,.13);
  --rd:#e05555;--rd-d:rgba(224,85,85,.13);
  --tx:#bec2d8;--mt:#505870;--st:#e2e6f2
}
body{font-family:'Outfit',system-ui,sans-serif;background:var(--bg);color:var(--tx);min-height:100vh;display:flex}
/* sidebar */
#sb{width:var(--sb);background:var(--sf);border-right:1px solid var(--bd);position:fixed;top:0;left:0;height:100vh;display:flex;flex-direction:column;z-index:100}
.sb-brand{padding:1.35rem 1.2rem .9rem;border-bottom:1px solid var(--bd)}
.sb-eye{font-size:.6rem;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--mt);display:block;margin-bottom:.25rem}
.sb-title{font-size:1rem;font-weight:600;color:var(--st);display:flex;align-items:center;gap:.5rem}
.beacon{width:7px;height:7px;border-radius:50%;background:var(--am);box-shadow:0 0 6px var(--am);flex-shrink:0;transition:background .3s,box-shadow .3s}
.beacon.ok{background:var(--gr);box-shadow:0 0 6px var(--gr)}.beacon.err{background:var(--rd);box-shadow:0 0 6px var(--rd)}
nav{flex:1;padding:.6rem .6rem;display:flex;flex-direction:column;gap:2px;overflow-y:auto}
.nb{display:flex;align-items:center;gap:.55rem;padding:.52rem .75rem;border-radius:8px;cursor:pointer;font-size:.84rem;font-weight:500;color:var(--mt);border:none;background:none;width:100%;text-align:left;transition:color .15s,background .15s;font-family:inherit}
.nb:hover{color:var(--tx);background:var(--sf2)}.nb.active{color:var(--am);background:var(--am-d)}
.nic{width:15px;text-align:center;flex-shrink:0;font-style:normal;font-size:.88rem}
.sb-foot{padding:.85rem 1.2rem;border-top:1px solid var(--bd);font-size:.72rem;color:var(--mt)}
.sb-ll{font-size:.6rem;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.2rem}
.sb-lv{font-family:'JetBrains Mono',monospace;font-size:.7rem;color:var(--tx)}
/* main */
#main{margin-left:var(--sb);flex:1;display:flex;flex-direction:column;min-height:100vh}
#tb{position:sticky;top:0;z-index:50;background:var(--bg);border-bottom:1px solid var(--bd);padding:.7rem 1.75rem;display:flex;align-items:center;justify-content:space-between;gap:1rem}
.tb-ttl{font-size:.95rem;font-weight:600;color:var(--st)}
.tb-r{display:flex;align-items:center;gap:.65rem}
.chip{display:inline-flex;align-items:center;gap:.35rem;font-size:.72rem;font-weight:500;padding:.28rem .65rem;border-radius:100px;font-family:'JetBrains Mono',monospace}
.chip.ok{background:var(--gr-d);color:var(--gr)}.chip.err{background:var(--rd-d);color:var(--rd)}.chip.pend{background:var(--am-d);color:var(--am)}
#ct{flex:1;padding:1.75rem 1.75rem}
.sec{display:none}.sec.active{display:block}
/* stat cards */
.sg{display:grid;grid-template-columns:repeat(auto-fill,minmax(155px,1fr));gap:.9rem;margin-bottom:1.25rem}
.sc{background:var(--sf);border:1px solid var(--bd);border-radius:12px;padding:1.05rem 1.2rem}
.sl{font-size:.63rem;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--mt);margin-bottom:.35rem}
.sv{font-family:'JetBrains Mono',monospace;font-size:1.7rem;font-weight:500;font-variant-numeric:tabular-nums;line-height:1}
.ca{color:var(--am)}.cb{color:var(--bl)}.cg{color:var(--gr)}.cr{color:var(--rd)}.cm{color:var(--mt)}
/* charts */
.cc{background:var(--sf);border:1px solid var(--bd);border-radius:12px;padding:1.1rem 1.35rem}
.cl{font-size:.63rem;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--mt);margin-bottom:.85rem}
.charts-row{display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:1.25rem}
/* tables */
.tc{background:var(--sf);border:1px solid var(--bd);border-radius:12px;overflow:hidden;margin-bottom:1.25rem}
.th{padding:.85rem 1.35rem;border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:.8rem;flex-wrap:wrap}
.tht{font-size:.63rem;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--mt);margin-right:auto}
.ts{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.85rem}
th{font-size:.63rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--mt);padding:.6rem 1.2rem;text-align:left;border-bottom:1px solid var(--bd);white-space:nowrap;cursor:pointer;user-select:none;background:var(--sf)}
th:hover{color:var(--tx)}th.asc::after{content:" ↑";color:var(--am)}th.desc::after{content:" ↓";color:var(--am)}
td{padding:.62rem 1.2rem;border-bottom:1px solid var(--bd);color:var(--tx)}
tr:last-child td{border-bottom:none}tr:hover td{background:var(--sf2)}
.mono{font-family:'JetBrains Mono',monospace;font-size:.78rem;font-variant-numeric:tabular-nums}
.sdot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:.4rem;vertical-align:middle}
.sdot.ok{background:var(--gr)}.sdot.err{background:var(--rd)}
/* expand row */
.xrow td{background:var(--sf2)!important;padding:.6rem 1.2rem!important}
/* inputs */
.fin{background:var(--sf2);border:1px solid var(--bd);color:var(--tx);border-radius:8px;padding:.42rem .8rem;font-size:.83rem;font-family:inherit;outline:none;transition:border-color .15s}
.fin:focus{border-color:var(--am)}.fin::placeholder{color:var(--mt)}
.fin[type=search]{width:190px}.fin[type=date]{width:148px}select.fin{cursor:pointer}
/* buttons */
.btn{display:inline-flex;align-items:center;gap:.38rem;padding:.45rem 1rem;border-radius:8px;font-size:.83rem;font-weight:500;font-family:inherit;cursor:pointer;border:none;transition:opacity .15s,transform .1s;text-decoration:none;white-space:nowrap}
.btn:active{transform:scale(.97)}.btn:disabled{opacity:.4;cursor:not-allowed}
.bta{background:var(--am);color:#0b0c14}.bta:hover:not(:disabled){opacity:.85}
.bts{background:var(--sf2);color:var(--tx);border:1px solid var(--bd)}.bts:hover:not(:disabled){border-color:var(--mt)}
.btg{background:transparent;color:var(--mt);border:1px solid var(--bd)}.btg:hover{color:var(--tx)}
.btd{background:var(--rd-d);color:var(--rd);border:1px solid var(--rd-d)}
.spin{width:13px;height:13px;border:2px solid rgba(255,255,255,.2);border-top-color:currentColor;border-radius:50%;animation:sp .7s linear infinite;display:none}
.btn.ld .spin{display:inline-block}.btn.ld .bl{display:none}
@keyframes sp{to{transform:rotate(360deg)}}
/* alerts */
.al{padding:.65rem 1rem;border-radius:8px;font-size:.83rem;margin-bottom:1rem;display:flex;align-items:center;gap:.5rem}
.al-ok{background:var(--gr-d);color:var(--gr);border:1px solid var(--gr-d)}
.al-err{background:var(--rd-d);color:var(--rd);border:1px solid var(--rd-d)}
.al-info{background:var(--bl-d);color:var(--bl);border:1px solid var(--bl-d)}
/* buy list */
.bg{display:grid;grid-template-columns:repeat(auto-fill,minmax(285px,1fr));gap:.65rem;padding:1rem 1.2rem}
.bc{background:var(--sf2);border:1px solid var(--bd);border-radius:10px;padding:.78rem 1rem;display:flex;align-items:center;gap:.7rem}
.bs{flex:1;font-size:.84rem;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
/* settings */
.sgrp{background:var(--sf);border:1px solid var(--bd);border-radius:12px;margin-bottom:1rem;overflow:hidden}
.sgh{padding:.85rem 1.2rem;border-bottom:1px solid var(--bd);font-size:.63rem;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--mt)}
.sgb{padding:1rem 1.2rem;display:flex;flex-direction:column;gap:.85rem}
.fl{display:flex;flex-direction:column;gap:.28rem}
.fl-l{font-size:.8rem;font-weight:500;color:var(--st)}.fl-h{font-size:.72rem;color:var(--mt)}
.fi{background:var(--sf2);border:1px solid var(--bd);border-radius:8px;color:var(--tx);font-size:.84rem;font-family:inherit;padding:.5rem .8rem;outline:none;transition:border-color .15s;width:100%}
.fi:focus{border-color:var(--am)}.fi::placeholder{color:var(--mt)}
.fr{display:flex;gap:.65rem}.fr .fl{flex:1}
.stc{display:flex;flex-direction:column;gap:.42rem}
.ck{display:flex;align-items:center;gap:.55rem;cursor:pointer;font-size:.85rem;padding:.4rem .7rem;border-radius:7px;border:1px solid var(--bd);background:var(--sf2);transition:border-color .15s}
.ck:hover{border-color:var(--am)}.ck input{width:15px;height:15px;accent-color:var(--am)}.ck-m{margin-left:auto;font-size:.72rem;color:var(--mt)}
.tog{position:relative;width:38px;height:20px;flex-shrink:0}
.tog input{opacity:0;width:0;height:0}
.tog-t{position:absolute;inset:0;background:var(--sf2);border:1px solid var(--bd);border-radius:100px;cursor:pointer;transition:background .2s}
.tog input:checked+.tog-t{background:var(--am);border-color:var(--am)}
.tog-t::after{content:'';position:absolute;left:3px;top:50%;transform:translateY(-50%);width:12px;height:12px;background:#fff;border-radius:50%;transition:left .2s}
.tog input:checked+.tog-t::after{left:calc(100% - 15px)}
.tog-r{display:flex;align-items:center;gap:.7rem}
/* history trend */
.tr-row{display:flex;gap:.9rem;flex-wrap:wrap;margin-bottom:1.25rem}
.tm{background:var(--sf);border:1px solid var(--bd);border-radius:12px;padding:.88rem 1.1rem;flex:1;min-width:120px}
.tm-l{font-size:.6rem;text-transform:uppercase;letter-spacing:.08em;font-weight:600;color:var(--mt);margin-bottom:.2rem}
.tm-v{font-family:'JetBrains Mono',monospace;font-size:1.3rem;font-weight:500}
/* sync log drawer */
.log-drawer{position:fixed;bottom:2px;left:var(--sb);right:0;height:260px;background:var(--sf);border-top:2px solid var(--am);z-index:300;display:flex;flex-direction:column;box-shadow:0 -6px 24px rgba(0,0,0,.35)}
.ld-hd{padding:.58rem 1.2rem;border-bottom:1px solid var(--bd);display:flex;align-items:center;gap:.7rem;flex-shrink:0}
.ld-ttl{font-size:.65rem;font-weight:600;text-transform:uppercase;letter-spacing:.1em;color:var(--mt)}
.ld-body{flex:1;overflow-y:auto;padding:.7rem 1.2rem;font-family:'JetBrains Mono',monospace;font-size:.73rem;line-height:1.65;color:var(--tx)}
.ll{white-space:pre-wrap}.ll-err{color:var(--rd)}.ll-warn{color:var(--am)}.ll-ok{color:var(--gr)}.ll-dim{color:var(--mt)}
/* progress */
.prog{height:2px;background:var(--bd);position:fixed;bottom:0;left:var(--sb);right:0;z-index:200}
.pf{height:100%;background:var(--am);transition:width 1s linear}
/* empty */
.empty{text-align:center;padding:2.5rem 1rem;color:var(--mt);font-size:.88rem}
/* theme btn */
.thb{background:var(--sf2);border:1px solid var(--bd);border-radius:8px;padding:.38rem .55rem;cursor:pointer;font-size:.85rem;color:var(--mt);transition:color .15s;line-height:1}
.thb:hover{color:var(--tx)}
/* responsive */
@media(max-width:768px){:root{--sb:0px}#sb{transform:translateX(-220px);width:220px;transition:transform .25s}#sb.open{transform:translateX(0)}#main{margin-left:0}.sg{grid-template-columns:repeat(2,1fr)}#ct{padding:1rem}.log-drawer{left:0}.prog{left:0}}
</style>
</head>
<body>

<div id="sb">
  <div class="sb-brand">
    <span class="sb-eye">Plex Sync</span>
    <div class="sb-title"><span class="beacon" id="beacon"></span>Journey FM</div>
  </div>
  <nav>
    <button class="nb active" data-sec="overview"><i class="nic">◈</i> Overview</button>
    <button class="nb" data-sec="songs"><i class="nic">♫</i> Top Songs</button>
    <button class="nb" data-sec="history"><i class="nic">◷</i> History</button>
    <button class="nb" data-sec="buylist"><i class="nic">◎</i> Buy List</button>
    <button class="nb" data-sec="playlist"><i class="nic">▤</i> Playlist</button>
    <button class="nb" data-sec="settings"><i class="nic">◧</i> Settings</button>
  </nav>
  <div class="sb-foot"><div class="sb-ll">Last sync</div><div class="sb-lv" id="sb-last">—</div></div>
</div>

<div id="main">
  <div id="tb">
    <div class="tb-ttl" id="tb-ttl">Overview</div>
    <div class="tb-r">
      <button class="thb" id="thb" title="Toggle theme">☾</button>
      <button class="btn bta" id="sync-btn" onclick="doSync()"><span class="bl">↺ Sync Now</span><span class="spin"></span></button>
    </div>
  </div>

  <div id="ct">

    <!-- OVERVIEW -->
    <div id="sec-overview" class="sec active">
      <div class="sg">
        <div class="sc"><div class="sl">Scraped</div><div class="sv cb" id="v-sc">—</div></div>
        <div class="sc"><div class="sl">Matched (last run)</div><div class="sv cg" id="v-ma">—</div></div>
        <div class="sc"><div class="sl">Added</div><div class="sv ca" id="v-ad">—</div></div>
        <div class="sc"><div class="sl">Missing</div><div class="sv cr" id="v-mi">—</div></div>
        <div class="sc"><div class="sl">Duplicates</div><div class="sv cm" id="v-du">—</div></div>
        <div class="sc"><div class="sl">Total Runs</div><div class="sv cm" id="v-ru">—</div></div>
      </div>
      <div class="charts-row">
        <div class="cc" style="flex:3;min-width:240px">
          <div class="cl">Station breakdown — all-time scrapes</div>
          <div style="position:relative;height:165px">
            <canvas id="chart-st"></canvas>
            <div class="empty" id="st-empty" style="display:none">No station data yet</div>
          </div>
        </div>
        <div class="cc" style="flex:2;min-width:200px">
          <div class="cl">Library match rate</div>
          <div style="position:relative;height:165px;display:flex;align-items:center;justify-content:center">
            <canvas id="chart-dn"></canvas>
            <div style="position:absolute;text-align:center;pointer-events:none">
              <div id="dn-pct" style="font-family:'JetBrains Mono',monospace;font-size:1.5rem;font-weight:500;color:var(--am)">—</div>
              <div style="font-size:.6rem;color:var(--mt);text-transform:uppercase;letter-spacing:.06em">in library</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- TOP SONGS -->
    <div id="sec-songs" class="sec">
      <div class="tc">
        <div class="th">
          <span class="tht">Top Tracks</span>
          <input class="fin" type="search" id="sq" placeholder="Search…" oninput="filterSongs()">
          <select class="fin" id="ss" onchange="filterSongs()"><option value="">All stations</option></select>
        </div>
        <div class="ts"><table>
          <thead><tr>
            <th style="width:44px">#</th>
            <th data-sort="station">Station</th>
            <th data-sort="song">Track</th>
            <th data-sort="count" class="desc">Plays</th>
          </tr></thead>
          <tbody id="songs-body"><tr><td colspan="4"><div class="empty">Loading…</div></td></tr></tbody>
        </table></div>
      </div>
    </div>

    <!-- HISTORY -->
    <div id="sec-history" class="sec">
      <div class="tr-row" id="hist-trends"></div>
      <div class="cc" style="margin-bottom:1.25rem">
        <div class="cl">Songs added per run — last 20</div>
        <div style="position:relative;height:150px"><canvas id="chart-hi"></canvas></div>
      </div>
      <div class="tc">
        <div class="th">
          <span class="tht">Run Log</span>
          <input class="fin" type="date" id="hf" onchange="applyHF()">
          <span style="color:var(--mt);font-size:.75rem">→</span>
          <input class="fin" type="date" id="ht" onchange="applyHF()">
          <button class="btn btg" style="font-size:.75rem;padding:.35rem .6rem" onclick="clearHF()">✕</button>
        </div>
        <div class="ts"><table>
          <thead><tr>
            <th>Date</th><th>Status</th><th>Scraped</th><th>Matched</th>
            <th>Added</th><th>Missing</th><th>Dupes</th><th>Skipped</th><th style="width:24px"></th>
          </tr></thead>
          <tbody id="hist-body"><tr><td colspan="9"><div class="empty">Loading…</div></td></tr></tbody>
        </table></div>
      </div>
    </div>

    <!-- BUY LIST -->
    <div id="sec-buylist" class="sec">
      <div id="buy-al" style="display:none"></div>
      <div class="tc">
        <div class="th">
          <span class="tht">Missing from Library</span>
          <span class="mono cm" id="buy-ct" style="font-size:.74rem"></span>
          <input class="fin" type="search" id="bq" placeholder="Search…" oninput="filterBuy()">
          <button class="btn bts" id="dedup-btn" onclick="doDedupBuyList()" style="font-size:.78rem">
            <span class="bl">Deduplicate</span><span class="spin"></span>
          </button>
          <button class="btn btg" onclick="copyAllLinks()" style="font-size:.78rem">Copy All Links</button>
        </div>
        <div class="bg" id="buy-grid"><div class="empty">Loading…</div></div>
      </div>
    </div>

    <!-- PLAYLIST -->
    <div id="sec-playlist" class="sec">
      <div id="pl-al" style="display:none"></div>
      <div class="tc">
        <div class="th">
          <span class="tht" id="pl-ttl">Playlist</span>
          <span class="mono cm" id="pl-ct" style="font-size:.74rem"></span>
          <input class="fin" type="search" id="plq" placeholder="Search…" oninput="filterPL()">
          <button class="btn bts" id="pl-btn" onclick="loadPlaylist()" style="font-size:.78rem">
            <span class="bl">↺ Load</span><span class="spin"></span>
          </button>
        </div>
        <div class="ts"><table>
          <thead><tr>
            <th data-psort="artist">Artist</th>
            <th data-psort="title">Title</th>
            <th data-psort="album">Album</th>
            <th style="width:90px;cursor:default"></th>
          </tr></thead>
          <tbody id="pl-body"><tr><td colspan="4"><div class="empty">Click Load to fetch your playlist from Plex</div></td></tr></tbody>
        </table></div>
      </div>
    </div>

    <!-- SETTINGS -->
    <div id="sec-settings" class="sec">
      <div id="cfg-al" style="display:none"></div>
      <div class="sgrp">
        <div class="sgh">Plex Connection</div>
        <div class="sgb">
          <div class="fl">
            <label class="fl-l" for="f-sv">Server IP</label>
            <input class="fi mono" id="f-sv" type="text" placeholder="192.168.1.100">
            <span class="fl-h">Local network address of your Plex server</span>
          </div>
          <div class="fl">
            <label class="fl-l" for="f-tk">Plex Token</label>
            <input class="fi mono" id="f-tk" type="password" placeholder="Leave blank to keep existing…">
            <span class="fl-h" id="tk-hint">—</span>
          </div>
          <div style="display:flex;align-items:center;gap:.75rem;flex-wrap:wrap">
            <button class="btn bts" id="test-btn" onclick="doTest()"><span class="bl">Test Connection</span><span class="spin"></span></button>
            <span id="test-r" style="font-size:.8rem"></span>
          </div>
        </div>
      </div>
      <div class="sgrp">
        <div class="sgh">Playlist</div>
        <div class="sgb">
          <div class="fl">
            <label class="fl-l" for="f-pl">Playlist Name</label>
            <input class="fi" id="f-pl" type="text" placeholder="Journey FM Recently Played">
          </div>
        </div>
      </div>
      <div class="sgrp">
        <div class="sgh">Stations</div>
        <div class="sgb">
          <div class="stc">
            <label class="ck"><input type="checkbox" id="st-j" value="journey_fm"><span>Journey FM</span><span class="ck-m">myjourneyfm.com</span></label>
            <label class="ck"><input type="checkbox" id="st-s" value="spirit_fm"><span>Spirit FM</span><span class="ck-m">spiritfm.com</span></label>
            <label class="ck"><input type="checkbox" id="st-k" value="klove"><span>K-LOVE</span><span class="ck-m">klove.com</span></label>
          </div>
        </div>
      </div>
      <div class="sgrp">
        <div class="sgh">Auto-Update</div>
        <div class="sgb">
          <div class="tog-r">
            <label class="tog"><input type="checkbox" id="f-au"><span class="tog-t"></span></label>
            <span class="fl-l">Enable automatic updates</span>
          </div>
          <div class="fr">
            <div class="fl"><label class="fl-l" for="f-in">Interval</label><input class="fi mono" id="f-in" type="number" min="1" max="999" value="15"></div>
            <div class="fl"><label class="fl-l" for="f-un">Unit</label><select class="fi" id="f-un"><option value="Minutes">Minutes</option><option value="Hours">Hours</option></select></div>
          </div>
        </div>
      </div>
      <button class="btn bta" id="save-btn" onclick="doSave()"><span class="bl">Save Changes</span><span class="spin"></span></button>
    </div>

  </div><!-- /ct -->
</div><!-- /main -->

<!-- Sync log drawer -->
<div class="log-drawer" id="log-drawer" style="display:none">
  <div class="ld-hd">
    <span class="ld-ttl">Live Sync</span>
    <span class="chip pend" id="log-chip">Running…</span>
    <button class="btn btg" style="margin-left:auto;padding:.3rem .6rem;font-size:.75rem" onclick="closeLog()">✕ Close</button>
  </div>
  <div class="ld-body" id="log-body"></div>
</div>

<div class="prog" id="prog-bar" style="display:none"><div class="pf" id="pf" style="width:100%"></div></div>

<script>
// ── Theme ─────────────────────────────────────────────────────
(function(){
  const s=localStorage.getItem('theme')||'';
  if(s)document.documentElement.setAttribute('data-theme',s);
  const btn=document.getElementById('thb');
  const dk=s==='dark'||(s===''&&window.matchMedia('(prefers-color-scheme:dark)').matches);
  btn.textContent=dk?'☀':'☾';
})();
document.getElementById('thb').onclick=function(){
  const c=document.documentElement.getAttribute('data-theme');
  const n=c==='dark'?'light':'dark';
  document.documentElement.setAttribute('data-theme',n);
  localStorage.setItem('theme',n);
  this.textContent=n==='dark'?'☀':'☾';
  rebuildCharts();
};

// ── Nav ───────────────────────────────────────────────────────
const TITLES={overview:'Overview',songs:'Top Songs',history:'Run History',buylist:'Buy List',playlist:'Playlist',settings:'Settings'};
const SECS=['overview','songs','history','buylist','playlist','settings'];
let cur='overview';
document.querySelectorAll('.nb').forEach(b=>b.addEventListener('click',()=>go(b.dataset.sec)));
function go(s){
  SECS.forEach(x=>document.getElementById('sec-'+x).classList.toggle('active',x===s));
  document.querySelectorAll('.nb').forEach(b=>b.classList.toggle('active',b.dataset.sec===s));
  document.getElementById('tb-ttl').textContent=TITLES[s]||s;
  cur=s;
  if(s==='songs'&&!songsReady&&statsData)buildSongs();
  if(s==='history'&&!histReady)loadHist();
  if(s==='buylist'&&!buyReady)loadBuy();
  if(s==='settings')loadCfg();
}

// ── State ─────────────────────────────────────────────────────
let statsData=null,songsData=[],histData=[],buyData=[],plData=[];
let songsReady=false,histReady=false,buyReady=false;
let sc='count',sd='desc',pc='artist',pd='asc';
let hfrom=null,hto=null;
let stChart=null,histChart=null,dnChart=null;
let syncES=null;
const TICK=60;let tick=TICK;

// ── Helpers ───────────────────────────────────────────────────
function fmt(n){return(n||0).toLocaleString();}
function ago(iso){
  const d=Math.floor((Date.now()-new Date(iso).getTime())/1000);
  if(d<60)return d+'s ago';if(d<3600)return Math.floor(d/60)+'m ago';
  if(d<86400)return Math.floor(d/3600)+'h ago';return Math.floor(d/86400)+'d ago';
}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function ld(btn,on){btn.classList.toggle('ld',on);btn.disabled=on;}
function showAl(id,type,msg){
  const el=document.getElementById(id);
  el.style.display='flex';el.className='al al-'+(type==='ok'?'ok':type==='info'?'info':'err');
  el.textContent=msg;setTimeout(()=>{el.style.display='none';},6000);
}
function cv(v){return getComputedStyle(document.documentElement).getPropertyValue(v).trim();}
function cc(){return{am:cv('--am'),bl:cv('--bl'),gr:cv('--gr'),rd:cv('--rd'),mt:cv('--mt'),bd:cv('--bd'),sf2:cv('--sf2')};}

// ── Stats ─────────────────────────────────────────────────────
function loadStats(){
  return fetch('/api/stats').then(r=>r.json()).then(d=>{
    statsData=d;
    document.getElementById('v-sc').textContent=fmt(d.total_scraped);
    document.getElementById('v-ma').textContent=fmt(d.total_matched);
    document.getElementById('v-ad').textContent=fmt(d.total_added);
    document.getElementById('v-mi').textContent=fmt(d.total_missing);
    document.getElementById('v-du').textContent=fmt(d.total_duplicates);
    document.getElementById('v-ru').textContent=fmt(d.total_updates);
    if(d.last_success)document.getElementById('sb-last').textContent=ago(d.last_success);
    drawSt(d.station_counts||{});
    drawDn(d);
    buildSongs();
  }).catch(()=>{});
}

// ── Charts ─────────────────────────────────────────────────────
function drawSt(counts){
  const canvas=document.getElementById('chart-st');
  const empty=document.getElementById('st-empty');
  const entries=Object.entries(counts);
  if(!entries.length||typeof Chart==='undefined'){canvas.style.display='none';empty.style.display='block';return;}
  empty.style.display='none';canvas.style.display='block';
  const s=entries.sort((a,b)=>b[1]-a[1]),C=cc();
  if(stChart)stChart.destroy();
  stChart=new Chart(canvas,{type:'bar',data:{labels:s.map(e=>e[0]),datasets:[{data:s.map(e=>e[1]),backgroundColor:C.am+'99',borderColor:C.am,borderWidth:1,borderRadius:5}]},
    options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` ${c.parsed.x.toLocaleString()} songs`}}},
      scales:{x:{grid:{color:C.bd},ticks:{color:C.mt,font:{family:"'JetBrains Mono',monospace",size:11}}},y:{grid:{display:false},ticks:{color:C.mt,font:{family:"'Outfit',sans-serif",size:12}}}}}});
}

function drawDn(d){
  const canvas=document.getElementById('chart-dn');
  if(typeof Chart==='undefined')return;
  const added=d.total_added||0,missing=d.total_missing||0,dupes=d.total_duplicates||0;
  const total=added+missing+dupes;
  if(!total){document.getElementById('dn-pct').textContent='—';return;}
  const pct=Math.round((added+dupes)/total*100);
  document.getElementById('dn-pct').textContent=pct+'%';
  const C=cc();
  if(dnChart)dnChart.destroy();
  dnChart=new Chart(canvas,{type:'doughnut',
    data:{labels:['Added','Duplicates','Missing'],datasets:[{data:[added,dupes,missing],backgroundColor:[C.am+'cc',C.sf2,C.rd+'cc'],borderColor:[C.am,C.bd,C.rd],borderWidth:1}]},
    options:{responsive:true,maintainAspectRatio:false,cutout:'72%',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` ${c.label}: ${c.parsed.toLocaleString()}`}}}}});
}

function drawHi(data){
  const canvas=document.getElementById('chart-hi');
  if(typeof Chart==='undefined')return;
  const recent=[...data].reverse().slice(-20);
  const C=cc();
  if(histChart)histChart.destroy();
  histChart=new Chart(canvas,{type:'line',
    data:{labels:recent.map(r=>r.date?r.date.slice(5,10):'—'),datasets:[{data:recent.map(r=>r.added_count||0),borderColor:C.am,backgroundColor:C.am+'22',borderWidth:2,pointRadius:3,pointBackgroundColor:C.am,fill:true,tension:.3}]},
    options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>` ${c.parsed.y} added`}}},
      scales:{x:{grid:{color:C.bd},ticks:{color:C.mt,font:{family:"'JetBrains Mono',monospace",size:10}}},y:{beginAtZero:true,grid:{color:C.bd},ticks:{color:C.mt,font:{family:"'JetBrains Mono',monospace",size:11},precision:0}}}}});
}

function rebuildCharts(){
  if(statsData){drawSt(statsData.station_counts||{});drawDn(statsData);}
  if(histData.length)drawHi(histData);
}

// ── Songs ─────────────────────────────────────────────────────
function buildSongs(){
  if(!statsData||!statsData.song_counts)return;
  songsData=[];
  for(const[st,songs]of Object.entries(statsData.song_counts))
    for(const[song,count]of Object.entries(songs))songsData.push({station:st,song,count});
  songsReady=true;
  const sel=document.getElementById('ss');
  const sts=[...new Set(songsData.map(r=>r.station))].sort();
  sel.innerHTML='<option value="">All stations</option>'+sts.map(s=>`<option value="${esc(s)}">${esc(s)}</option>`).join('');
  if(cur==='songs')filterSongs();
}
function filterSongs(){
  const q=document.getElementById('sq').value.toLowerCase();
  const st=document.getElementById('ss').value;
  let rows=songsData;
  if(st)rows=rows.filter(r=>r.station===st);
  if(q)rows=rows.filter(r=>r.song.toLowerCase().includes(q)||r.station.toLowerCase().includes(q));
  rows=[...rows].sort((a,b)=>{
    let av=a[sc],bv=b[sc];
    if(typeof av==='string'){av=av.toLowerCase();bv=bv.toLowerCase();}
    const dir=sd==='asc'?1:-1;return av<bv?-dir:av>bv?dir:0;
  });
  const tb=document.getElementById('songs-body');
  if(!rows.length){tb.innerHTML='<tr><td colspan="4"><div class="empty">No tracks found</div></td></tr>';return;}
  tb.innerHTML=rows.map((r,i)=>`<tr>
    <td class="mono cm">${i+1}</td>
    <td><span style="font-size:.73rem;background:var(--sf2);border-radius:4px;padding:.12rem .45rem;color:var(--mt)">${esc(r.station)}</span></td>
    <td>${esc(r.song)}</td><td class="mono ca">${r.count}</td></tr>`).join('');
}
document.querySelectorAll('#sec-songs th[data-sort]').forEach(th=>{
  th.addEventListener('click',()=>{
    const col=th.dataset.sort;
    if(sc===col)sd=sd==='asc'?'desc':'asc';else{sc=col;sd=col==='count'?'desc':'asc';}
    document.querySelectorAll('#sec-songs th').forEach(t=>t.classList.remove('asc','desc'));
    th.classList.add(sd);filterSongs();
  });
});

// ── History ───────────────────────────────────────────────────
function loadHist(){
  return fetch('/api/history').then(r=>r.json()).then(d=>{
    histData=d;histReady=true;
    const runs=d.length,ok=d.filter(r=>r.status==='success').length;
    const tot=d.reduce((a,r)=>a+(r.added_count||0),0),avg=runs?(tot/runs).toFixed(1):'0';
    const rate=runs?Math.round(100*ok/runs):0;
    document.getElementById('hist-trends').innerHTML=`
      <div class="tm"><div class="tm-l">Success Rate</div><div class="tm-v ${rate>80?'cg':rate>50?'ca':'cr'}">${rate}%</div></div>
      <div class="tm"><div class="tm-l">Total Runs</div><div class="tm-v cb">${runs.toLocaleString()}</div></div>
      <div class="tm"><div class="tm-l">Avg Added</div><div class="tm-v ca">${avg}</div></div>
      <div class="tm"><div class="tm-l">Total Added</div><div class="tm-v cg">${tot.toLocaleString()}</div></div>`;
    drawHi(d);renderHistTable(d);
  }).catch(()=>{});
}
function applyHF(){hfrom=document.getElementById('hf').value||null;hto=document.getElementById('ht').value||null;renderHistTable(histData);}
function clearHF(){document.getElementById('hf').value='';document.getElementById('ht').value='';hfrom=null;hto=null;renderHistTable(histData);}
function renderHistTable(data){
  let rows=data;
  if(hfrom)rows=rows.filter(r=>r.date&&r.date>=hfrom);
  if(hto)rows=rows.filter(r=>r.date&&r.date<=(hto+'T23:59:59'));
  const tb=document.getElementById('hist-body');
  if(!rows.length){tb.innerHTML='<tr><td colspan="9"><div class="empty">No runs in this range</div></td></tr>';return;}
  tb.innerHTML=rows.map(r=>{
    const ds=(r.date||'').replace('T',' ').slice(0,16);
    const hb=(r.station_breakdown||[]).length>0;
    return`<tr class="hr" data-id="${r.id}" style="cursor:${hb?'pointer':'default'}" onclick="${hb?`xHist(${r.id},this)`:'void 0'}">
      <td class="mono" style="font-size:.74rem">${esc(ds)}</td>
      <td><span class="sdot ${r.status==='success'?'ok':'err'}"></span>${esc(r.status)}</td>
      <td class="mono">${r.scraped_count||0}</td><td class="mono">${r.matched_count||0}</td>
      <td class="mono ca">${r.added_count||0}</td><td class="mono cr">${r.missing_count||0}</td>
      <td class="mono">${r.duplicate_count||0}</td><td class="mono">${r.skipped_count||0}</td>
      <td style="color:var(--mt);font-size:.72rem;padding-right:.6rem">${hb?'▸':''}</td></tr>`;
  }).join('');
}
function xHist(id,rowEl){
  const ex=document.getElementById('x'+id);
  if(ex){ex.remove();const ind=rowEl.querySelector('td:last-child');if(ind)ind.textContent='▸';return;}
  const ind=rowEl.querySelector('td:last-child');if(ind)ind.textContent='▾';
  const row=histData.find(r=>r.id===id);if(!row)return;
  const bd=row.station_breakdown||[];
  const chips=bd.map(s=>`<span style="display:inline-flex;align-items:center;gap:.35rem;margin:.1rem .3rem .1rem 0;background:var(--sf);border:1px solid var(--bd);border-radius:6px;padding:.22rem .5rem;font-size:.73rem">
    <span>${esc(s.display_name||s.station||'?')}</span>
    <b style="color:${s.success?'var(--am)':'var(--rd)'}">${s.scraped_count||0}</b>
    ${!s.success?'<span style="color:var(--rd);font-size:.65rem">failed</span>':''}
  </span>`).join('');
  const xr=document.createElement('tr');
  xr.id='x'+id;xr.className='xrow';
  xr.innerHTML=`<td colspan="9"><div style="font-size:.62rem;color:var(--mt);text-transform:uppercase;letter-spacing:.07em;font-weight:600;margin-bottom:.3rem">Station breakdown</div><div>${chips||'<span style="color:var(--mt)">No detail</span>'}</div></td>`;
  rowEl.insertAdjacentElement('afterend',xr);
}

// ── Buy List ──────────────────────────────────────────────────
function loadBuy(){
  return fetch('/api/buy-list-rich').then(r=>r.json()).then(d=>{
    buyData=d;buyReady=true;
    document.getElementById('buy-ct').textContent=d.length+' songs';
    renderBuy(d);
  }).catch(()=>fetch('/api/buy-list').then(r=>r.json()).then(d=>{
    buyData=d.map(s=>({song:s,url:null}));buyReady=true;
    document.getElementById('buy-ct').textContent=d.length+' songs';
    renderBuy(buyData);
  }));
}
function renderBuy(data){
  const g=document.getElementById('buy-grid');
  if(!data.length){g.innerHTML='<div class="empty" style="padding:2.5rem">Your library has every scraped song 🎉</div>';return;}
  g.innerHTML=data.map(i=>{
    const s=typeof i==='string'?i:i.song,u=typeof i==='object'?i.url:null;
    return`<div class="bc"><span class="bs" title="${esc(s)}">${esc(s)}</span>${u?`<a class="btn btg" href="${esc(u)}" target="_blank" rel="noopener" style="font-size:.73rem;flex-shrink:0">Amazon ↗</a>`:''}</div>`;
  }).join('');
}
function filterBuy(){
  const q=document.getElementById('bq').value.toLowerCase();
  renderBuy(q?buyData.filter(i=>(typeof i==='string'?i:i.song).toLowerCase().includes(q)):buyData);
}
function doDedupBuyList(){
  const btn=document.getElementById('dedup-btn');ld(btn,true);
  fetch('/api/buy-list-dedup',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    .then(r=>r.json()).then(d=>{
      ld(btn,false);
      if(d.removed!==undefined){
        showAl('buy-al',d.removed>0?'ok':'info',d.removed>0?`Removed ${d.removed} duplicates — ${d.remaining} remain`:'No duplicates found');
        buyReady=false;loadBuy();
      }else showAl('buy-al','err',d.message||'Error');
    }).catch(e=>{ld(btn,false);showAl('buy-al','err',String(e));});
}
function copyAllLinks(){
  fetch('/api/buy-list-links').then(r=>r.json()).then(links=>{
    const text=links.join('\n');
    (navigator.clipboard?navigator.clipboard.writeText(text):Promise.reject()).catch(()=>{
      const ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand('copy');document.body.removeChild(ta);
    }).then?.(()=>{}).catch?.(()=>{});
    showAl('buy-al','ok',`Copied ${links.length} Amazon links to clipboard`);
  });
}

// ── Playlist ──────────────────────────────────────────────────
function loadPlaylist(){
  const btn=document.getElementById('pl-btn');ld(btn,true);
  fetch('/api/playlist').then(r=>r.json()).then(d=>{
    ld(btn,false);
    if(d.error){document.getElementById('pl-body').innerHTML=`<tr><td colspan="4"><div class="empty">${esc(d.error)}</div></td></tr>`;return;}
    plData=d.tracks||[];
    document.getElementById('pl-ttl').textContent=d.name||'Playlist';
    document.getElementById('pl-ct').textContent=plData.length+' tracks';
    filterPL();
  }).catch(e=>{ld(btn,false);document.getElementById('pl-body').innerHTML=`<tr><td colspan="4"><div class="empty">Error: ${esc(String(e))}</div></td></tr>`;});
}
function filterPL(){
  const q=document.getElementById('plq').value.toLowerCase();
  let rows=plData;
  if(q)rows=rows.filter(r=>r.title.toLowerCase().includes(q)||r.artist.toLowerCase().includes(q)||r.album.toLowerCase().includes(q));
  rows=[...rows].sort((a,b)=>{
    let av=(a[pc]||'').toLowerCase(),bv=(b[pc]||'').toLowerCase();
    const dir=pd==='asc'?1:-1;return av<bv?-dir:av>bv?dir:0;
  });
  const tb=document.getElementById('pl-body');
  if(!rows.length){tb.innerHTML='<tr><td colspan="4"><div class="empty">No tracks</div></td></tr>';return;}
  tb.innerHTML=rows.map(r=>`<tr>
    <td>${esc(r.artist)}</td><td>${esc(r.title)}</td>
    <td style="color:var(--mt);font-size:.82rem">${esc(r.album)}</td>
    <td><button class="btn btd" style="font-size:.72rem;padding:.28rem .55rem" onclick="removeTrack('${esc(r.rating_key)}',this)">Remove</button></td>
  </tr>`).join('');
}
document.querySelectorAll('#sec-playlist th[data-psort]').forEach(th=>{
  th.addEventListener('click',()=>{
    const col=th.dataset.psort;
    if(pc===col)pd=pd==='asc'?'desc':'asc';else{pc=col;pd='asc';}
    document.querySelectorAll('#sec-playlist th').forEach(t=>t.classList.remove('asc','desc'));
    th.classList.add(pd);filterPL();
  });
});
function removeTrack(rk,btn){
  if(!confirm('Remove this track from the playlist?'))return;
  btn.disabled=true;btn.textContent='…';
  fetch('/api/playlist/remove',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({rating_keys:[rk]})})
    .then(r=>r.json()).then(d=>{
      if(d.status==='ok'){
        plData=plData.filter(t=>t.rating_key!==rk);
        document.getElementById('pl-ct').textContent=plData.length+' tracks';
        filterPL();
      }else{btn.disabled=false;btn.textContent='Remove';showAl('pl-al','err',d.message||'Error');}
    }).catch(e=>{btn.disabled=false;btn.textContent='Remove';showAl('pl-al','err',String(e));});
}

// ── Settings ──────────────────────────────────────────────────
function loadCfg(){
  fetch('/api/config').then(r=>r.json()).then(cfg=>{
    document.getElementById('f-sv').value=cfg.SERVER_IP||'';
    document.getElementById('f-pl').value=cfg.PLAYLIST_NAME||'';
    document.getElementById('f-au').checked=!!cfg.AUTO_UPDATE;
    document.getElementById('f-in').value=cfg.UPDATE_INTERVAL||15;
    document.getElementById('f-un').value=cfg.UPDATE_UNIT||'Minutes';
    const sts=cfg.SELECTED_STATIONS||[];
    document.getElementById('st-j').checked=sts.includes('journey_fm');
    document.getElementById('st-s').checked=sts.includes('spirit_fm');
    document.getElementById('st-k').checked=sts.includes('klove');
    const h=document.getElementById('tk-hint');
    h.textContent=cfg._has_token?'✓ Token saved — leave blank to keep it':'No token saved yet';
    h.style.color=cfg._has_token?'var(--gr)':'var(--mt)';
  });
}
function doSave(){
  const btn=document.getElementById('save-btn');ld(btn,true);
  const stations=[];
  if(document.getElementById('st-j').checked)stations.push('journey_fm');
  if(document.getElementById('st-s').checked)stations.push('spirit_fm');
  if(document.getElementById('st-k').checked)stations.push('klove');
  fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
    SERVER_IP:document.getElementById('f-sv').value.trim(),
    PLEX_TOKEN:document.getElementById('f-tk').value.trim(),
    PLAYLIST_NAME:document.getElementById('f-pl').value.trim(),
    SELECTED_STATIONS:stations,
    AUTO_UPDATE:document.getElementById('f-au').checked,
    UPDATE_INTERVAL:parseInt(document.getElementById('f-in').value)||15,
    UPDATE_UNIT:document.getElementById('f-un').value,
  })}).then(r=>r.json()).then(d=>{
    ld(btn,false);
    if(d.status==='ok'){showAl('cfg-al','ok','Settings saved');document.getElementById('f-tk').value='';loadCfg();}
    else showAl('cfg-al','err',d.message||'Save failed');
  }).catch(e=>{ld(btn,false);showAl('cfg-al','err',String(e));});
}
function doTest(){
  const btn=document.getElementById('test-btn'),res=document.getElementById('test-r');
  ld(btn,true);res.textContent='';
  fetch('/api/test-connection').then(r=>r.json()).then(d=>{
    ld(btn,false);
    res.style.color=d.status==='ok'?'var(--gr)':'var(--rd)';
    res.textContent=(d.status==='ok'?'✓ ':'✗ ')+(d.message||'');
  }).catch(e=>{ld(btn,false);res.style.color='var(--rd)';res.textContent='✗ '+e;});
}

// ── Sync + SSE log ────────────────────────────────────────────
function doSync(){
  const btn=document.getElementById('sync-btn');
  ld(btn,true);
  if(syncES){syncES.close();syncES=null;}
  const drawer=document.getElementById('log-drawer');
  const body=document.getElementById('log-body');
  const chip=document.getElementById('log-chip');
  body.innerHTML='';
  chip.className='chip pend';chip.textContent='Running…';
  drawer.style.display='flex';
  document.getElementById('prog-bar').style.display='block';
  syncES=new EventSource('/api/sync-stream');
  syncES.onmessage=function(e){
    const d=JSON.parse(e.data),msg=d.msg||'';
    const line=document.createElement('div');
    const lc=msg.includes('ERROR')||msg.includes('error')?'ll-err':msg.includes('WARN')?'ll-warn':msg.includes('Added')||msg.includes('Matched')?'ll-ok':msg.startsWith('DEBUG')?'ll-dim':'ll';
    line.className='ll '+lc;line.textContent=msg;
    body.appendChild(line);body.scrollTop=body.scrollHeight;
  };
  syncES.addEventListener('done',function(e){
    ld(btn,false);
    const d=JSON.parse(e.data);
    syncES.close();syncES=null;
    if(d.error){chip.className='chip err';chip.textContent='✗ Failed';}
    else{
      chip.className='chip ok';chip.textContent='✓ Done';
      const r=d.result||{};
      const sum=document.createElement('div');
      sum.className='ll ll-ok';
      sum.textContent=`─── Added: ${r.added_count||0}  Missing: ${r.missing_count||0}  Duplicates: ${r.duplicate_count||0} ───`;
      body.appendChild(sum);body.scrollTop=body.scrollHeight;
    }
    loadStats();
    histReady=false;buyReady=false;
    if(cur==='history')loadHist();
    if(cur==='buylist')loadBuy();
    tick=TICK;
  });
  syncES.onerror=function(){
    ld(btn,false);chip.className='chip err';chip.textContent='✗ Disconnected';
    if(syncES){syncES.close();syncES=null;}
  };
}
function closeLog(){
  if(syncES){syncES.close();syncES=null;}
  document.getElementById('log-drawer').style.display='none';
  document.getElementById('prog-bar').style.display='block';
}

// ── Auto countdown ────────────────────────────────────────────
document.getElementById('prog-bar').style.display='block';
setInterval(()=>{
  tick=Math.max(0,tick-1);
  document.getElementById('pf').style.width=(tick/TICK*100)+'%';
  if(tick===0){tick=TICK;loadStats();}
},1000);

// ── Init ──────────────────────────────────────────────────────
loadStats();
</script>
</body>
</html>
"""


def render_dashboard_html(stats):
    return DASHBOARD_HTML


def _build_handler(stats_supplier):
    class Handler(BaseHTTPRequestHandler):

        def do_GET(self):
            p = self.path.split("?")[0]
            if p in ("/", "/index.html"):
                self._html(DASHBOARD_HTML.encode("utf-8"))
            elif p == "/api/stats":
                self._json(stats_supplier())
            elif p == "/api/config":
                self._json(get_web_config())
            elif p == "/api/test-connection":
                try:
                    from journeyfm.plex_service import connect_to_plex_server
                    cfg = load_runtime_config()
                    connect_to_plex_server(cfg.get("PLEX_TOKEN", ""), cfg.get("SERVER_IP", ""))
                    self._json({"status": "ok", "message": "Connected to Plex successfully"})
                except Exception as exc:
                    self._json({"status": "error", "message": str(exc)})
            elif p == "/api/sync-stream":
                self._sse_sync()
            elif p == "/api/refresh":
                try:
                    result = run_update_job(load_runtime_config())
                    self._json({"status": "ok", "result": result})
                except Exception as exc:
                    self._json({"status": "error", "message": str(exc), "trace": traceback.format_exc()}, 500)
            elif p == "/api/preview":
                try:
                    result = run_update_job(load_runtime_config(), dry_run=True, persist_history=False, write_buy_list=False)
                    self._json(result)
                except Exception as exc:
                    self._json({"status": "error", "message": str(exc)}, 500)
            elif p == "/api/buy-list":
                self._json(load_buy_list())
            elif p == "/api/buy-list-rich":
                self._json(load_buy_list_rich())
            elif p == "/api/buy-list-links":
                self._json([e["url"] for e in load_buy_list_rich() if e.get("url")])
            elif p == "/api/history":
                self._json(load_history_entries())
            elif p == "/api/playlist":
                try:
                    self._json(get_playlist_tracks())
                except Exception as exc:
                    self._json({"error": str(exc), "tracks": []})
            else:
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"404 Not Found")

        def do_POST(self):
            p = self.path.split("?")[0]
            body = self._read_body()
            if p == "/api/config":
                try:
                    save_web_config(json.loads(body))
                    self._json({"status": "ok"})
                except Exception as exc:
                    self._json({"status": "error", "message": str(exc)}, 400)
            elif p == "/api/playlist/remove":
                try:
                    data = json.loads(body)
                    removed = remove_playlist_tracks(data.get("rating_keys", []))
                    self._json({"status": "ok", "removed": removed})
                except Exception as exc:
                    self._json({"status": "error", "message": str(exc)}, 400)
            elif p == "/api/buy-list-dedup":
                try:
                    self._json(dedup_buy_list())
                except Exception as exc:
                    self._json({"status": "error", "message": str(exc)}, 500)
            else:
                self.send_response(404)
                self.end_headers()

        def _sse_sync(self):
            with _sync_lock:
                if _sync_state["running"]:
                    self._json({"status": "error", "message": "A sync is already in progress"}, 409)
                    return
                _sync_state["running"] = True

            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            q = queue.Queue()
            handler = _QueueLogHandler(q)

            def run():
                root = logging.getLogger()
                root.addHandler(handler)
                try:
                    result = run_update_job(load_runtime_config())
                    q.put({"_done": True, "result": result})
                except Exception as exc:
                    q.put(f"ERROR: {exc}")
                    q.put({"_done": True, "result": None, "error": str(exc)})
                finally:
                    root.removeHandler(handler)
                    _sync_state["running"] = False

            threading.Thread(target=run, daemon=True).start()

            try:
                while True:
                    try:
                        item = q.get(timeout=120)
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        continue
                    if isinstance(item, dict) and item.get("_done"):
                        payload = json.dumps({"result": item.get("result"), "error": item.get("error")}, default=str)
                        self.wfile.write(f"event: done\ndata: {payload}\n\n".encode())
                        self.wfile.flush()
                        break
                    else:
                        payload = json.dumps({"msg": str(item)}, default=str)
                        self.wfile.write(f"data: {payload}\n\n".encode())
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                _sync_state["running"] = False

        def _read_body(self):
            length = int(self.headers.get("Content-Length", 0))
            return self.rfile.read(length).decode("utf-8") if length else "{}"

        def _json(self, data, status=200):
            body = json.dumps(data, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, body):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    return Handler


def start_dashboard_server(host=DEFAULT_HOST, port=DEFAULT_PORT, open_browser_if_possible=True):
    httpd = ThreadingHTTPServer((host, port), _build_handler(load_recent_stats))

    def serve():
        try:
            if open_browser_if_possible:
                webbrowser.open(f"http://{host}:{port}")
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
