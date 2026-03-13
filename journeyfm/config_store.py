import json
import os
from pathlib import Path

from journeyfm.paths import data_path

try:
    import keyring
except Exception:
    keyring = None

CONFIG_PATH = data_path("config.json")
KEYRING_SERVICE = "JourneyFMPlaylistCreator"
DEFAULT_CONFIG = {
    "PLEX_TOKEN": "",
    "SERVER_IP": "",
    "PLAYLIST_NAME": "Journey FM Recently Played",
    "AUTO_UPDATE": False,
    "UPDATE_INTERVAL": 15,
    "UPDATE_UNIT": "Minutes",
    "SELECTED_STATIONS": ["journey_fm", "spirit_fm"],
}
NON_SECRET_KEYS = {
    "SERVER_IP",
    "PLAYLIST_NAME",
    "AUTO_UPDATE",
    "UPDATE_INTERVAL",
    "UPDATE_UNIT",
    "SELECTED_STATIONS",
}


def is_containerized():
    return os.path.exists("/.dockerenv") or os.getenv("JOURNEYFM_CONTAINER") == "1"


def _normalize_selected_stations(value):
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return list(DEFAULT_CONFIG["SELECTED_STATIONS"])


def _read_config_file(config_path=CONFIG_PATH):
    if not Path(config_path).exists():
        return {}
    try:
        with open(config_path, "r", encoding="utf-8") as file_handle:
            return json.load(file_handle)
    except Exception:
        return {}


def _write_config_file(config, config_path=CONFIG_PATH):
    with open(config_path, "w", encoding="utf-8") as file_handle:
        json.dump(config, file_handle, indent=2)


def get_secret(key):
    env_value = os.getenv(key, "").strip()
    if env_value:
        return env_value
    if not is_containerized() and keyring is not None:
        try:
            stored = keyring.get_password(KEYRING_SERVICE, key)
            if stored:
                return stored
        except Exception:
            pass
    file_config = _read_config_file()
    return str(file_config.get(key, "")).strip()


def set_secret(key, value):
    if not value:
        delete_secret(key)
        return
    if not is_containerized() and keyring is not None:
        try:
            keyring.set_password(KEYRING_SERVICE, key, value)
            return
        except Exception:
            pass
    file_config = _read_config_file()
    file_config[key] = value
    _write_config_file(file_config)


def delete_secret(key):
    if not is_containerized() and keyring is not None:
        try:
            keyring.delete_password(KEYRING_SERVICE, key)
        except Exception:
            pass
    file_config = _read_config_file()
    if key in file_config:
        del file_config[key]
        _write_config_file(file_config)


def migrate_legacy_secrets(config_path=CONFIG_PATH):
    file_config = _read_config_file(config_path)
    token = str(file_config.get("PLEX_TOKEN", "")).strip()
    if token and not is_containerized() and keyring is not None:
        try:
            keyring.set_password(KEYRING_SERVICE, "PLEX_TOKEN", token)
            del file_config["PLEX_TOKEN"]
            _write_config_file(file_config, config_path)
        except Exception:
            pass


def load_runtime_config(config_path=CONFIG_PATH):
    migrate_legacy_secrets(config_path)
    config = dict(DEFAULT_CONFIG)
    file_config = _read_config_file(config_path)
    config.update({key: value for key, value in file_config.items() if key in NON_SECRET_KEYS})
    config["PLEX_TOKEN"] = get_secret("PLEX_TOKEN")

    env_server = os.getenv("SERVER_IP", "").strip()
    env_playlist = os.getenv("PLAYLIST_NAME", "").strip()
    env_stations = os.getenv("SELECTED_STATIONS", "").strip()
    env_auto_update = os.getenv("AUTO_UPDATE", "").strip()
    env_interval = os.getenv("UPDATE_INTERVAL", "").strip()
    env_unit = os.getenv("UPDATE_UNIT", "").strip()

    if env_server:
        config["SERVER_IP"] = env_server
    if env_playlist:
        config["PLAYLIST_NAME"] = env_playlist
    if env_stations:
        config["SELECTED_STATIONS"] = _normalize_selected_stations(env_stations)
    else:
        config["SELECTED_STATIONS"] = _normalize_selected_stations(config.get("SELECTED_STATIONS"))
    if env_auto_update:
        config["AUTO_UPDATE"] = env_auto_update.lower() in {"1", "true", "yes", "on"}
    if env_interval:
        try:
            config["UPDATE_INTERVAL"] = int(env_interval)
        except ValueError:
            pass
    if env_unit:
        config["UPDATE_UNIT"] = env_unit

    return config


def save_runtime_config(config, config_path=CONFIG_PATH):
    config = dict(config)
    token = str(config.pop("PLEX_TOKEN", "")).strip()
    if token:
        set_secret("PLEX_TOKEN", token)

    persisted = {}
    for key in NON_SECRET_KEYS:
        if key not in config:
            continue
        value = config[key]
        if isinstance(value, list):
            persisted[key] = ",".join(value)
        else:
            persisted[key] = value
    _write_config_file(persisted, config_path)


def get_display_config(config_path=CONFIG_PATH):
    config = load_runtime_config(config_path)
    config["PLEX_TOKEN"] = get_secret("PLEX_TOKEN")
    return config
