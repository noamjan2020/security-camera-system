from __future__ import annotations

import logging
import shutil
from threading import Event, Thread

from .config import Settings
from .database import EventDatabase
from .event_service import EventService

logger = logging.getLogger(__name__)


class MaintenanceService:
    def __init__(self, database: EventDatabase, events: EventService, settings: Settings):
        self.database = database
        self.events = events
        self.settings = settings
        self._stop = Event()
        self._thread: Thread | None = None
        self.disk_free_mb = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="maintenance-service", daemon=True)
        self._thread.start()
        logger.info("Maintenance service started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Maintenance service stopped")

    def run_once(self) -> None:
        self.events.cleanup(self.settings.retention_minutes)
        usage = shutil.disk_usage(self.settings.data_dir)
        self.disk_free_mb = int(usage.free / 1024 / 1024)
        if self.disk_free_mb < self.settings.disk_warning_mb:
            logger.error(
                "Low disk space: %d MB free (warning threshold %d MB)",
                self.disk_free_mb,
                self.settings.disk_warning_mb,
            )
        else:
            logger.debug("Disk free: %d MB", self.disk_free_mb)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                logger.exception("Maintenance cycle failed")
            self._stop.wait(self.settings.cleanup_interval_seconds)
