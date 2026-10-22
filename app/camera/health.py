"""Watch the buffet cameras and warn when one goes offline.

Every capture photo and a regular check between meals report to ``CameraMonitor.record``. A camera that fails
CAMERA_OFFLINE_AFTER checks in a row (or a whole capture, which already retried) is offline: a warning shows on
every page and the managers on the weekly report list get one email. A second email says when it is back.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
import logging
import threading

from sqlalchemy import inspect, select
from sqlalchemy.exc import SQLAlchemyError

from app.camera.capture import CameraError, CameraUnavailable, grab_jpeg
from app.database.tables import CameraStatusRow
from app.reports import store
from app.reports.mailer import MailError, mail_ready, send_each
from app.waste_records.common import local_time


logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class State:
    name: str
    status: str = "unknown"        # unknown (not checked yet), online or offline
    failures: int = 0
    last_ok_at: str | None = None
    checked_at: str | None = None
    offline_since: str | None = None
    last_error: str = ""
    alerted_at: str | None = None
    note: str = ""                 # what happened to the alert email, for the Cameras page


def shown_time(text: str | None) -> str:
    """"14:20 on 22 Oct" in local time, or "" when there is no time."""
    if not text:
        return ""
    moment = local_time(text)
    return f"{moment:%H:%M} on {moment.day} {moment:%b}"


class CameraMonitor:
    def __init__(self, app):
        self.app = app
        settings = app.state.settings
        self.threshold = settings["CAMERA_OFFLINE_AFTER"]
        self.alerts = settings["CAMERA_ALERTS"]
        self.probe = settings.get("FRAME_GRABBER") or partial(grab_jpeg, warmup=0)
        self._lock = threading.RLock()
        self._loaded = False
        self._states: dict[str, State] = {}

    # ---- the state -------------------------------------------------------------------------------

    def _names(self) -> list[str]:
        return [camera["name"] for camera in self.app.state.settings["CAMERA_SOURCES"]]

    def _load(self) -> None:
        """Pick up what the database remembers, once, so an outage survives a restart."""
        with self._lock:
            if self._loaded:
                return
            self._loaded = True
            try:
                with self.app.state.session_factory() as db:
                    if inspect(db.get_bind()).has_table(CameraStatusRow.__tablename__):
                        for row in db.scalars(select(CameraStatusRow)):
                            self._states[row.name] = State(row.name, row.status, row.failures, row.last_ok_at, row.checked_at,
                                                           row.offline_since, row.last_error, row.alerted_at)
            except SQLAlchemyError:
                logger.exception("Could not read the camera status.")

    def _save(self, state: State) -> None:
        try:
            with self.app.state.session_factory() as db:
                CameraStatusRow.__table__.create(db.get_bind(), checkfirst=True)
                row = db.get(CameraStatusRow, state.name) or CameraStatusRow(name=state.name)
                row.status, row.failures, row.last_ok_at, row.checked_at = state.status, state.failures, state.last_ok_at, state.checked_at
                row.offline_since, row.last_error, row.alerted_at = state.offline_since, state.last_error, state.alerted_at
                db.add(row)
                db.commit()
        except SQLAlchemyError:
            logger.exception("Could not save the camera status.")

    def snapshot(self) -> list[State]:
        """Every camera that is set up, in order, with what is known about it."""
        self._load()
        with self._lock:
            return [self._states.get(name) or State(name) for name in self._names()]

    def offline(self) -> list[State]:
        return [state for state in self.snapshot() if state.status == "offline"]

    # ---- reports ---------------------------------------------------------------------------------

    def record(self, name: str, ok: bool, error: str = "", *, immediate: bool = False) -> None:
        """One result for one camera. ``immediate`` is for a capture that already failed after retries."""
        if name not in self._names():
            return
        self._load()
        with self._lock:
            state = self._states.setdefault(name, State(name))
            now = _now()
            state.checked_at = now
            came_back = alerted = False
            if ok:
                came_back = state.status == "offline"
                alerted = state.alerted_at is not None
                outage_start = state.offline_since
                state.status, state.failures, state.last_ok_at, state.last_error = "online", 0, now, ""
                state.offline_since = state.alerted_at = None
            else:
                state.failures += self.threshold if immediate else 1
                state.last_error = error
                if state.status != "offline" and state.failures >= self.threshold:
                    state.status, state.offline_since, state.alerted_at, state.note = "offline", now, None, ""
                    logger.warning("Camera %s is offline: %s", name, error)
            self._save(state)
            if came_back:
                logger.info("Camera %s is back online.", name)
                state.note = ""
                if alerted:
                    self._email_back(state, outage_start)
            elif state.status == "offline" and state.alerted_at is None:
                self._email_offline(state)   # also retries an email that could not be sent before

    def record_event(self, event) -> None:
        """Each station's result from a finished capture: online if any photo worked, else offline at once."""
        for name in dict.fromkeys(photo.station for photo in event.photos):
            photos = [photo for photo in event.photos if photo.station == name]
            failed = next((photo for photo in photos if not photo.ok), None)
            if any(photo.ok for photo in photos):
                self.record(name, True)
            else:
                self.record(name, False, failed.error or "The camera failed.", immediate=True)

    def check_all(self, *, force: bool = False) -> list[State]:
        """Look at every camera now. Skipped while a capture is running, since the camera is in use."""
        service = self.app.state.capture_service
        if service._busy.locked() and not force:
            return self.snapshot()
        for camera in service.cameras:
            try:
                self.probe(camera["url"])
                self.record(camera["name"], True)
            except CameraUnavailable:
                return self.snapshot()
            except CameraError as error:
                self.record(camera["name"], False, str(error))
            except Exception as error:   # whatever the camera does, the check must go on
                self.record(camera["name"], False, f"The camera failed ({type(error).__name__}).")
        return self.snapshot()

    # ---- email -----------------------------------------------------------------------------------

    def _recipients(self, state: State) -> list[str] | None:
        """Who to email, or None (with the reason in state.note) when no email can go."""
        settings = self.app.state.settings
        if not self.alerts:
            state.note = "Alert emails are turned off (CAMERA_ALERTS)."
        elif not mail_ready(settings):
            state.note = "No email sent: email is not set up (ADMIN_EMAIL and SMTP_HOST)."
        else:
            try:
                with self.app.state.session_factory() as db:
                    people = [row.email for row in store.list_recipients(db)]
            except SQLAlchemyError:
                logger.exception("Could not read the alert recipients.")
                people = []
            if people:
                return people
            state.note = "No email sent: nobody is on the Weekly report list yet."
        return None

    def _send(self, state: State, subject: str, text: str, html: str) -> bool:
        people = self._recipients(state)
        if people is None:
            return False
        try:
            reached = send_each(self.app.state.settings, people, subject, text, html)
        except MailError as error:
            state.note = f"The alert email could not be sent: {error}"
            return False
        state.note = f"Alert email sent to {len(reached)} address{'' if len(reached) == 1 else 'es'}."
        return True

    def _email_offline(self, state: State) -> None:
        link = self.app.state.settings["PUBLIC_URL"] + "/cameras"
        since = shown_time(state.offline_since)
        problem = state.last_error or "The camera did not answer."
        text = (f"The {state.name} camera is offline (since {since}).\n\nWhat Wastewise saw: {problem}\n"
                f"Last picture: {shown_time(state.last_ok_at) or 'none yet'}\n\n"
                "While it is offline no meal photos are taken, so meal checks for this station will be missing.\n"
                "Please check that the camera or phone is on, charged, on the hotel Wi-Fi and that its streaming app is running.\n\n"
                f"Camera status: {link}")
        html = (f'<div style="font-family:Segoe UI,Arial,sans-serif;max-width:560px;color:#17332a">'
                f'<div style="background:#c2540a;color:#fff;padding:18px 22px;border-radius:12px 12px 0 0;font-size:20px;font-weight:700">'
                f'{state.name} camera is offline</div>'
                f'<div style="background:#fff7f0;padding:18px 22px;border-radius:0 0 12px 12px;font-size:15px;line-height:1.5">'
                f'<p>Offline since <strong>{since}</strong>.<br>What Wastewise saw: {problem}<br>'
                f'Last picture: {shown_time(state.last_ok_at) or "none yet"}</p>'
                f'<p>While it is offline no meal photos are taken, so meal checks for this station will be missing. '
                f'Please check that the camera or phone is on, charged, on the hotel Wi-Fi and that its streaming app is running.</p>'
                f'<p><a href="{link}" style="background:#ff7a1a;color:#fff;text-decoration:none;font-weight:700;padding:10px 18px;border-radius:9px;display:inline-block">Camera status</a></p>'
                f'</div></div>')
        if self._send(state, f"Wastewise alert: {state.name} camera is offline", text, html):
            state.alerted_at = _now()
            self._save(state)

    def _email_back(self, state: State, since: str | None) -> None:
        text = f"Good news: the {state.name} camera is back online and taking photos again. It had been offline since {shown_time(since)}."
        html = (f'<div style="font-family:Segoe UI,Arial,sans-serif;max-width:560px;color:#17332a">'
                f'<div style="background:#0a8a54;color:#fff;padding:18px 22px;border-radius:12px;font-size:20px;font-weight:700">'
                f'{state.name} camera is back online</div>'
                f'<p>It had been offline since {shown_time(since)}.</p></div>')
        self._send(state, f"Wastewise: {state.name} camera is back online", text, html)
