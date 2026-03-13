#!/usr/bin/env python3
"""Journey FM Playlist Creator CLI entrypoint."""

import logging
import sys

from journeyfm.config_store import load_runtime_config
from journeyfm.history_service import init_history_db
from journeyfm.paths import data_path
from journeyfm.plex_service import connect_to_plex_server
from journeyfm.update_service import format_result_summary, run_update_job


def configure_logging():
    """Configure logging with quiet defaults for CLI and GUI entrypoints."""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    handlers = []

    try:
        handlers.append(logging.FileHandler(data_path('playlist_log.txt'), encoding='utf-8'))
    except Exception:
        pass

    stream = getattr(sys, 'stderr', None) or getattr(sys, 'stdout', None)
    if stream is not None:
        handlers.append(logging.StreamHandler(stream))

    logging.basicConfig(level=logging.INFO, format=log_format, handlers=handlers, force=True)
    for noisy_logger in ('webdriver_manager', 'WDM', 'matplotlib', 'urllib3', 'plexapi'):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


configure_logging()
logger = logging.getLogger(__name__)


def load_config():
    """Compatibility wrapper for existing callers."""
    return load_runtime_config()


def main():
    """Run one update cycle and print a concise result summary."""
    init_history_db()
    result = run_update_job(load_runtime_config())
    summary = format_result_summary(result)
    print(summary)
    if result.get('status') == 'error':
        logger.error(summary)
    return result


def update_playlist():
    """Compatibility wrapper used by the GUI."""
    return main()


if __name__ == '__main__':
    main()
