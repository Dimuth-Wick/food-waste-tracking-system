"""Take photos from the buffet cameras and save them to disk.

``CaptureService.capture_event`` is what the scheduler and the run-now endpoint call. It never
raises because one camera is down: every failure is logged and returned, so the rest of the
cameras are still photographed.
"""

from dataclasses import dataclass, field
from datetime import datetime
import logging
import os
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


logger = logging.getLogger(__name__)

FRAME_WARMUP = 5            # frames thrown away first: cameras often send a dark or blurry start
RETRIES = 2                 # extra attempts after the first one fails
RETRY_DELAY_SECONDS = 1.0
OPEN_TIMEOUT_MS = 8000
READ_TIMEOUT_MS = 8000
JPEG_QUALITY = 92
KINDS = ("start", "end")


class CameraError(Exception):
    """One camera could not give a picture. The message is safe to show: it never has the address."""


class CameraUnavailable(Exception):
    """Capturing is not possible at all: no cameras are set up, or OpenCV is missing."""


class CaptureBusy(Exception):
    """A capture is already running."""


def safe_url(source: str) -> str:
    """The camera address without any user name, password or query string, for logs."""
    if source.isdigit():
        return f"webcam {source}"
    parts = urlsplit(source)
    host = parts.hostname or "unknown-host"
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}{parts.path}"


def slug(name: str) -> str:
    """A station name that is safe in a file name: "Station 1" -> "Station-1"."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-") or "station"


def grab_jpeg(source: str, *, warmup: int = FRAME_WARMUP) -> bytes:
    """Open the camera, skip the warm-up frames, take one picture and ALWAYS release the camera.

    A live stream such as an IP camera's /video never ends, so it is read frame by frame with
    OpenCV rather than downloaded.
    """
    try:
        import cv2
    except ImportError as error:
        raise CameraUnavailable("OpenCV is not installed. Run: pip install -r requirements.txt") from error

    target = int(source) if source.isdigit() else source
    params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS, cv2.CAP_PROP_READ_TIMEOUT_MSEC, READ_TIMEOUT_MS]
    # Network streams (http, rtsp) go straight to the FFmpeg reader; a webcam number lets OpenCV choose.
    backend = cv2.CAP_ANY if isinstance(target, int) else cv2.CAP_FFMPEG
    try:
        camera = cv2.VideoCapture(target, backend, params)
    except TypeError:  # an older OpenCV without the timeout parameters
        camera = cv2.VideoCapture(target)
    try:
        if not camera.isOpened():
            raise CameraError("The camera could not be opened. Check that it is on and reachable.")
        frame = None
        for number in range(warmup + 1):
            worked, picture = camera.read()
            if not worked or picture is None:
                if frame is None:
                    raise CameraError("The camera opened but sent no picture.")
                break
            frame = picture
        encoded, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        if not encoded:
            raise CameraError("The picture could not be saved as a JPEG.")
        return buffer.tobytes()
    finally:
        camera.release()


@dataclass
class Photo:
    station: str
    ok: bool
    captured_at: datetime
    path: Path | None = None     # absolute path of the saved file
    relative: str | None = None  # path inside the captures folder, safe to show
    error: str | None = None


@dataclass
class CaptureEvent:
    meal: str
    kind: str
    started_at: datetime
    photos: list[Photo] = field(default_factory=list)

    @property
    def ok_count(self) -> int:
        return sum(1 for photo in self.photos if photo.ok)

    @property
    def failed_count(self) -> int:
        return len(self.photos) - self.ok_count


class CaptureService:
    """Takes and saves the photos of one capture event."""

    def __init__(self, settings, *, sleep=time.sleep):
        self.cameras = list(settings["CAMERA_SOURCES"])
        self.schedule = settings["MEAL_SCHEDULE"]
        self.photos_per_capture = settings["PHOTOS_PER_CAPTURE"]
        self.photo_gap = settings["PHOTO_GAP_SECONDS"]
        self.directory = Path(settings["CAPTURE_DIR"])
        self.timezone = ZoneInfo(settings["TIMEZONE"])
        self.grab = settings.get("FRAME_GRABBER") or grab_jpeg
        self.retry_delay = settings.get("CAPTURE_RETRY_DELAY", RETRY_DELAY_SECONDS)
        self._sleep = sleep
        self._busy = threading.Lock()

    def now(self) -> datetime:
        return datetime.now(self.timezone)

    def capture_event(self, meal: str, kind: str) -> CaptureEvent:
        """Photograph the buffet for this meal. One photo per camera, or several from a single camera.

        Raises CameraUnavailable (nothing set up) or CaptureBusy (already running). Anything that
        goes wrong with a single camera is returned in the event instead.
        """
        if meal not in self.schedule:
            raise ValueError(f"Unknown meal: {meal}")
        if kind not in KINDS:
            raise ValueError(f"Unknown kind: {kind}")
        if not self.cameras:
            raise CameraUnavailable("No cameras are set up. Set CAMERA_SOURCES, then restart the app.")
        if not self._busy.acquire(blocking=False):
            raise CaptureBusy("A capture is already running. Wait for it to finish.")
        try:
            event = CaptureEvent(meal=meal, kind=kind, started_at=self.now())
            if len(self.cameras) == 1:
                for number in range(self.photos_per_capture):
                    if number:
                        self._sleep(self.photo_gap)
                    event.photos.append(self._take(self.cameras[0], meal, kind))
            else:
                for camera in self.cameras:
                    event.photos.append(self._take(camera, meal, kind))
            logger.info("Capture %s/%s: %d photos saved, %d failed", meal, kind, event.ok_count, event.failed_count)
            return event
        finally:
            self._busy.release()

    def _take(self, camera: dict, meal: str, kind: str) -> Photo:
        """One photo from one camera, with retries. Never raises except CameraUnavailable."""
        error = "The camera failed."
        for attempt in range(RETRIES + 1):
            try:
                picture = self.grab(camera["url"])
                taken = self.now()
                path = self._save(picture, camera["name"], meal, kind, taken)
                return Photo(camera["name"], True, taken, path=path,
                             relative=path.relative_to(self.directory).as_posix())
            except CameraUnavailable:
                raise
            except CameraError as failure:
                error = str(failure)
            except Exception as failure:  # a broken camera must never stop the others
                error = f"The camera failed ({type(failure).__name__})."
            logger.warning("%s (%s): attempt %d of %d failed: %s", camera["name"], safe_url(camera["url"]),
                           attempt + 1, RETRIES + 1, error)
            if attempt < RETRIES:
                self._sleep(self.retry_delay)
        return Photo(camera["name"], False, self.now(), error=error)

    def _save(self, picture: bytes, station: str, meal: str, kind: str, taken: datetime) -> Path:
        """Write instance/captures/YYYY-MM-DD/<meal>/<kind>/<station>_<HHMMSS>.jpg."""
        folder = self.directory / taken.strftime("%Y-%m-%d") / meal / kind
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{slug(station)}_{taken.strftime('%H%M%S')}"
        path, number = folder / f"{name}.jpg", 1
        while path.exists():
            number += 1
            path = folder / f"{name}-{number}.jpg"
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(picture)
        os.replace(temporary, path)  # a half-written photo is never left behind
        return path
