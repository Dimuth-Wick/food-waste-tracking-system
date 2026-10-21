"""Count captured photos in the background, one at a time, so neither the scheduler nor a page waits.

The OWLv2 model from app/vision/counting.py is loaded once (on the first photo) and reused.
"""

import logging
import queue
import threading

from app.camera.meals import pair_drafts
from app.camera.store import count_capture, pending_ids, record_event, sync_from_disk


logger = logging.getLogger(__name__)


class CountingWorker:
    def __init__(self, app):
        self.app = app
        self._queue: queue.Queue[int | None] = queue.Queue()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def enqueue(self, capture_ids) -> None:
        for capture_id in capture_ids:
            self._queue.put(capture_id)

    def start(self) -> None:
        """Pick up photos already on disk and any left uncounted, then start counting in the background."""
        if self.running:
            return
        try:
            with self.app.state.session_factory() as db:
                settings = self.app.state.settings
                sync_from_disk(db, settings["CAPTURE_DIR"], settings["CAMERA_SOURCES"], settings["TIMEZONE"])
                waiting = pending_ids(db)
        except Exception:
            logger.exception("Could not read the captures table; photos will not be counted.")
            return
        self.enqueue(waiting)
        self._thread = threading.Thread(target=self._run, name="capture-counting", daemon=True)
        self._thread.start()
        if waiting:
            logger.info("Counting %d photos in the background.", len(waiting))

    def stop(self) -> None:
        if self.running:
            self._queue.put(None)
            self._thread.join(timeout=5)
        self._thread = None

    def process_pending(self) -> int:
        """Count everything queued right now, in this thread (used by tests). Returns how many were counted."""
        done = 0
        while True:
            try:
                capture_id = self._queue.get_nowait()
            except queue.Empty:
                return done
            if capture_id is not None:
                self._count_one(capture_id)
                done += 1

    def _run(self) -> None:
        while True:
            capture_id = self._queue.get()
            if capture_id is None:
                return
            self._count_one(capture_id)

    def _count_one(self, capture_id: int) -> None:
        from app.vision.counting import MODEL_NAME, count_labels

        settings = self.app.state.settings
        model_name = settings.get("FOOD_COUNTER_MODEL_NAME", MODEL_NAME)
        try:
            with self.app.state.session_factory() as db:
                status = count_capture(db, capture_id,
                                       lambda image, labels, minimum: count_labels(self.app, image, labels, minimum),
                                       settings["CAPTURE_DIR"], model_name)
                if status == "counted":
                    pair_drafts(db)   # both sides of a meal counted: it is ready for staff to confirm
            logger.info("Photo %s: %s", capture_id, status)
        except Exception:  # the worker must keep going whatever happens to one photo
            logger.exception("Photo %s could not be counted.", capture_id)


def store_and_queue(app, event) -> list[int]:
    """Store a finished capture event and queue its photos for counting. Returns the stored photo ids."""
    with app.state.session_factory() as db:
        ids = record_event(db, event, app.state.settings["CAPTURE_DIR"])
    app.state.counting_worker.enqueue(ids)
    return ids
