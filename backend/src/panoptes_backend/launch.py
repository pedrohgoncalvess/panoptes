"""Run the API with a private virtual display for interactive Chromium on Linux."""

import logging
import os
import subprocess
import sys

import uvicorn


def main():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    display = None
    if (
        sys.platform == "linux"
        and not os.getenv("DISPLAY")
        and (
            os.getenv("BROWSER_MERCADO_LIVRE_HEADLESS", "false").lower() != "true"
            or os.getenv("BROWSER_RETAIL_HEADLESS", "false").lower() != "true"
        )
    ):
        display = subprocess.Popen(
            [
                "Xvfb",
                "-displayfd",
                "1",
                "-screen",
                "0",
                "1440x1000x24",
                "-nolisten",
                "tcp",
            ],
            stdout=subprocess.PIPE,
            text=True,
        )
        number = display.stdout.readline().strip()
        display.stdout.close()
        if not number.isdecimal():
            display.terminate()
            display.wait(timeout=5)
            raise RuntimeError(
                "Virtual display unavailable. Install Xvfb or configure DISPLAY."
            )
        os.environ["DISPLAY"] = f":{number}"
        logger.info("Virtual display ready: DISPLAY=%s", os.environ["DISPLAY"])
    try:
        uvicorn.run(
            "panoptes_backend.main:app",
            host="0.0.0.0",
            port=int(os.getenv("PORT", "8000")),
        )
    finally:
        if display:
            display.terminate()
            display.wait(timeout=5)


if __name__ == "__main__":
    main()
