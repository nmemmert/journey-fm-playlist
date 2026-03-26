#!/usr/bin/env python3
"""Journey FM Playlist Creator CLI entrypoint."""

import argparse
import logging
import sys
import time

from journeyfm.config_store import load_runtime_config
from journeyfm.history_service import init_history_db
from journeyfm.paths import data_path
from journeyfm.plex_service import connect_to_plex_server
from journeyfm.update_service import format_result_summary, run_update_job
from journeyfm.web_service import get_dashboard_url, start_dashboard_server


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


def main_cli():
    parser = argparse.ArgumentParser(description='Journey FM Playlist CLI')
    parser.add_argument('--serve-web', action='store_true', help='Start local web dashboard server')
    parser.add_argument('--host', default='127.0.0.1', help='Dashboard host (default 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8765, help='Dashboard port (default 8765)')
    parser.add_argument('--no-open', action='store_true', help='Do not automatically open browser when serving web dashboard')
    args = parser.parse_args()

    if args.serve_web:
        init_history_db()
        result = run_update_job(load_runtime_config())
        summary = format_result_summary(result)
        print(summary)
        httpd, thread = start_dashboard_server(host=args.host, port=args.port, open_browser_if_possible=not args.no_open)
        print('Web dashboard URL:', get_dashboard_url(args.host, args.port))
        print('Press Ctrl+C to stop the web server.')
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            print('Shutting down dashboard server...')
            httpd.shutdown()
        return result

    return main()


if __name__ == '__main__':
    main_cli()
