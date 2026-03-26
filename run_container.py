import logging
import os
import time

from journeyfm.config_store import load_runtime_config
from journeyfm.update_service import format_result_summary, run_update_job
from journeyfm.web_service import start_dashboard_server

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_sleep_seconds():
    interval = os.getenv("UPDATE_INTERVAL", "15").strip()
    unit = os.getenv("UPDATE_UNIT", "Minutes").strip().lower()
    try:
        interval_value = max(1, int(interval))
    except ValueError:
        interval_value = 15
    if unit.startswith("hour"):
        return interval_value * 3600
    return interval_value * 60


def main():
    os.environ.setdefault("JOURNEYFM_CONTAINER", "1")

    # Start the optional local web dashboard by default in container mode
    web_mode = os.getenv("ENABLE_WEB_DASHBOARD", "true").strip().lower()
    if web_mode not in ("false", "0", "no", "off"):
        start_dashboard_server(host="0.0.0.0", port=int(os.getenv("DASHBOARD_PORT", "8765")), open_browser_if_possible=False)
        logger.info("Started local web dashboard on port %s", os.getenv("DASHBOARD_PORT", "8765"))

    run_mode = os.getenv("CONTAINER_RUN_MODE", "loop").strip().lower()
    while True:
        result = run_update_job(load_runtime_config())
        logger.info(format_result_summary(result))
        if run_mode == "once":
            break
        sleep_seconds = get_sleep_seconds()
        logger.info("Sleeping %s seconds before next container sync", sleep_seconds)
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
