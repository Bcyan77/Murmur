from __future__ import annotations

import logging

from murmur.config import load_config

logger = logging.getLogger(__name__)


class MurmurApp:
    def __init__(self) -> None:
        self.config = load_config()
        logger.info("Murmur config loaded")

    def run(self) -> int:
        logger.info("Murmur app starting (stub)")
        return 0
