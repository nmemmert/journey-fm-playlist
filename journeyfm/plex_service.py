import urllib.parse

from plexapi.myplex import MyPlexAccount
from plexapi.server import PlexServer


class PlexConnectionError(RuntimeError):
    pass


def normalize_server_target(server_ip):
    target = (server_ip or "").strip()
    if not target:
        return ""
    if "://" not in target:
        target = f"http://{target}"
    parsed = urllib.parse.urlparse(target)
    return (parsed.hostname or "").strip().lower()


def resolve_plex_server_url(token, server_ip):
    target_host = normalize_server_target(server_ip)
    if not token:
        raise PlexConnectionError("Missing Plex token")
    if not target_host:
        raise PlexConnectionError("Missing Plex server address")

    try:
        account = MyPlexAccount(token=token)
    except Exception as exc:
        raise PlexConnectionError(f"Failed to authenticate with Plex: {exc}") from exc

    for resource in account.resources():
        for connection in resource.connections:
            connection_host = normalize_server_target(connection.uri)
            address = (connection.address or "").strip().lower()
            if connection_host == target_host or target_host == address or target_host in address:
                return connection.uri

    raise PlexConnectionError(
        f"Server not found at {server_ip}. Verify the configured address and that Plex is reachable."
    )


def connect_to_plex_server(token, server_ip):
    server_url = resolve_plex_server_url(token, server_ip)
    try:
        return PlexServer(server_url, token)
    except Exception as exc:
        raise PlexConnectionError(f"Failed to connect to Plex server at {server_url}: {exc}") from exc


def playlist_item_count(playlist):
    leaf_count = getattr(playlist, "leafCount", None)
    if isinstance(leaf_count, int):
        return leaf_count
    try:
        return len(playlist.items())
    except Exception:
        return 0


def fetch_playlists(token, server_ip, music_only=False):
    plex = connect_to_plex_server(token, server_ip)
    return fetch_playlists_for_plex(plex, music_only)


def fetch_playlists_for_plex(plex, music_only=False):
    playlists = []
    for playlist in plex.playlists():
        playlist_type = getattr(playlist, "playlistType", "unknown")
        if music_only and playlist_type != "audio":
            continue
        playlists.append(
            {
                "title": playlist.title,
                "playlist_type": playlist_type,
                "item_count": playlist_item_count(playlist),
            }
        )
    playlists.sort(key=lambda item: (item["title"].lower(), item["playlist_type"]))
    return playlists


def validate_playlist_target(token, server_ip, playlist_name, music_only=False):
    plex = connect_to_plex_server(token, server_ip)
    playlist_name = (playlist_name or "").strip()
    if not playlist_name:
        raise PlexConnectionError("Playlist name is required")

    playlists = fetch_playlists_for_plex(plex, music_only=False)
    for playlist in playlists:
        if playlist["title"].strip().lower() == playlist_name.lower():
            if music_only and playlist["playlist_type"] != "audio":
                raise PlexConnectionError("Selected playlist is not a music playlist")
            return {
                "exists": True,
                "playlist": playlist,
                "message": f"Ready to write to existing playlist '{playlist_name}'",
            }

    try:
        plex.library.section("Music")
    except Exception as exc:
        raise PlexConnectionError(f"Music library is not accessible on this server: {exc}") from exc

    return {
        "exists": False,
        "playlist": {
            "title": playlist_name,
            "playlist_type": "audio",
            "item_count": 0,
        },
        "message": f"Playlist '{playlist_name}' will be created on first sync",
    }


def _normalize_artist(name):
    """Return a simplified artist token for fuzzy comparison."""
    import re
    name = name.lower()
    # Drop featured artists — everything after feat/ft/with/w/
    name = re.sub(r"\s+(feat\.?|ft\.?|featuring|w/|with)\s+.*", "", name)
    # Drop parenthetical / bracketed suffixes
    name = re.sub(r"[\(\[].*?[\)\]]", "", name)
    # Expand & / + to "and"
    name = re.sub(r"\s*[&+]\s*", " and ", name)
    # Collapse articles at start: "the foo" → "foo"
    name = re.sub(r"^(the|a|an)\s+", "", name)
    # Remove common punctuation that Plex sometimes strips
    name = re.sub(r"['\.\-,]", "", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


def _artists_match(search_artist, track_artist_raw):
    """
    Return True if the station artist string plausibly refers to the same
    artist stored in Plex, using several normalisation / containment passes.
    """
    sa = _normalize_artist(search_artist)
    ta = _normalize_artist(track_artist_raw)

    if not sa or not ta:
        return False

    # Exact normalised match
    if sa == ta:
        return True

    # One fully contains the other (e.g. "Brandon Lake" in "Brandon Lake & Maverick")
    if sa in ta or ta in sa:
        return True

    # Token-set overlap: every token in the shorter name appears in the longer
    sa_tokens = set(sa.split())
    ta_tokens = set(ta.split())
    if sa_tokens and ta_tokens:
        shorter = sa_tokens if len(sa_tokens) <= len(ta_tokens) else ta_tokens
        longer  = ta_tokens if len(sa_tokens) <= len(ta_tokens) else sa_tokens
        # All tokens of the shorter name found in the longer (handles "for king country" ↔ "for king and country")
        if shorter <= longer:
            return True
        # At least >60 % of tokens match (handles minor word-count diffs)
        overlap = len(shorter & longer)
        if overlap / len(shorter) >= 0.6:
            return True

    return False


def create_or_update_playlist(plex, songs, playlist_name, dry_run=False):
    import re
    music_library = plex.library.section("Music")
    tracks = []
    seen_keys = set()
    missing = []
    skipped = []
    added_songs = []
    duplicate_songs = []

    for song in songs:
        clean_title = re.sub(r"\([^)]*\)", "", song["title"]).strip()
        clean_title = re.sub(r"\s+", " ", clean_title)
        clean_artist = re.sub(r"\([^)]*\)", "", song["artist"]).strip()
        clean_artist = re.sub(r"\s+", " ", clean_artist)

        if not clean_title or len(clean_title) < 3 or clean_title.lower() in {"by", "recently played", "now playing:", "search"}:
            skipped.append({"title": song["title"], "artist": song["artist"], "reason": "invalid-title"})
            continue
        if re.match(r"^[!?\s]+$", clean_title):
            skipped.append({"title": song["title"], "artist": song["artist"], "reason": "punctuation-only-title"})
            continue

        search_title = re.sub(r"[!?]", "", clean_title).strip()
        search_artist = re.sub(r"[!?]", "", clean_artist).strip()
        # Expand & / + in title for Plex search (artist expansion handled by _artists_match)
        search_title = re.sub(r"\s*[&+]\s*", " and ", search_title, flags=re.IGNORECASE)

        results = music_library.searchTracks(title=search_title)
        if not results:
            # Secondary search: try the raw title in case Plex stores it differently
            results = music_library.searchTracks(title=clean_title)
        if not results:
            missing.append({"title": song["title"], "artist": song["artist"], "reason": "not-found"})
            continue

        matched = False
        for track in results:
            try:
                track_artist_raw = track.artist().title
            except Exception:
                continue

            if _artists_match(search_artist, track_artist_raw):
                if track.ratingKey not in seen_keys:
                    tracks.append((track, song))
                    seen_keys.add(track.ratingKey)
                matched = True
                break

        if not matched:
            missing.append({"title": song["title"], "artist": song["artist"], "reason": "artist-mismatch"})

    matched_count = len(tracks)
    added_count = 0
    if tracks:
        try:
            try:
                existing = plex.playlist(playlist_name)
                existing_keys = {item.ratingKey for item in existing.items()}
                new_tracks = []
                for track, song in tracks:
                    if track.ratingKey in existing_keys:
                        duplicate_songs.append({"title": track.title, "artist": track.artist().title, "reason": "already-in-playlist"})
                        continue
                    new_tracks.append((track, song))

                if new_tracks:
                    if not dry_run:
                        existing.addItems([item[0] for item in new_tracks])
                        for track, song in new_tracks:
                            track.addLabel("Journey FM")
                            track.rate(5)
                            added_songs.append(f"{track.title} by {track.artist().title} ({song['source']})")
                    else:
                        for track, song in new_tracks:
                            added_songs.append(f"{track.title} by {track.artist().title} ({song['source']})")
                    added_count = len(new_tracks)
            except Exception:
                if not dry_run:
                    plex.createPlaylist(playlist_name, [item[0] for item in tracks])
                    for track, song in tracks:
                        track.addLabel("Journey FM")
                        track.rate(5)
                        added_songs.append(f"{track.title} by {track.artist().title} ({song['source']})")
                else:
                    for track, song in tracks:
                        added_songs.append(f"{track.title} by {track.artist().title} ({song['source']})")
                added_count = len(tracks)
        except Exception as exc:
            raise PlexConnectionError(f"Failed updating playlist '{playlist_name}': {exc}") from exc

    return {
        "matched_count": matched_count,
        "added_count": added_count,
        "added_songs": added_songs,
        "missing_songs": missing,
        "duplicate_count": len(duplicate_songs),
        "duplicate_songs": duplicate_songs,
        "skipped_songs": skipped,
    }
