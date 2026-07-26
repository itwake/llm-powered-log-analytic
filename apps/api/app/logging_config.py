from __future__ import annotations

import logging

from app.config import Settings

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(app_settings: Settings) -> None:
    level = getattr(logging, app_settings.log_level.strip().upper(), logging.INFO)
    logging.basicConfig(level=level, format=LOG_FORMAT)
