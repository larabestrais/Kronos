"""
LearningScheduler — thread de fond qui déclenche le cycle d'apprentissage
chaque jour à 22h00 (heure Bruxelles).
"""

import logging
import threading
from datetime import datetime
from typing import Callable, Optional

import pytz

logger = logging.getLogger(__name__)


class LearningScheduler:

    def __init__(
        self,
        callback: Callable[[], None],
        timezone: str = "Europe/Brussels",
        hour: int = 22,
        minute: int = 0,
    ):
        self.callback = callback
        self.tz = pytz.timezone(timezone)
        self.target_hour = hour
        self.target_minute = minute
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_run_date: Optional[str] = None  # "YYYY-MM-DD"

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            logger.warning("[Learning][Scheduler] déjà démarré")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="learning-scheduler"
        )
        self._thread.start()
        logger.info(
            f"[Learning][Scheduler] démarré, exécutera à {self.target_hour:02d}:"
            f"{self.target_minute:02d} ({self.tz})"
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("[Learning][Scheduler] arrêté")

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                now = datetime.now(self.tz)
                today_key = now.strftime("%Y-%m-%d")

                # On déclenche si on est à ou après l'heure cible et qu'on n'a pas déjà tourné aujourd'hui
                if (
                    now.hour > self.target_hour
                    or (now.hour == self.target_hour and now.minute >= self.target_minute)
                ) and self._last_run_date != today_key:
                    logger.info("[Learning][Scheduler] déclenchement du cycle quotidien")
                    try:
                        self.callback()
                    except Exception as e:
                        logger.exception(f"[Learning][Scheduler] erreur dans callback: {e}")
                    self._last_run_date = today_key

                # Sleep jusqu'à la prochaine vérif (toutes les 60 sec)
                self._stop_event.wait(60)
            except Exception as e:
                logger.exception(f"[Learning][Scheduler] erreur boucle: {e}")
                self._stop_event.wait(60)
