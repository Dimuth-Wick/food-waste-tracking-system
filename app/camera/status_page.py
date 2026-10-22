"""The Camera status page: is each buffet camera reachable, and a button to check now."""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.camera.health import shown_time
from app.web import render, url_path


router = APIRouter(include_in_schema=False)


def _rows(request: Request) -> list[dict]:
    monitor = request.app.state.camera_monitor
    return [{"name": state.name, "status": state.status, "failures": state.failures,
             "last_ok": shown_time(state.last_ok_at), "checked": shown_time(state.checked_at),
             "since": shown_time(state.offline_since), "problem": state.last_error, "note": state.note}
            for state in monitor.snapshot()]


def _page(request: Request, *, checked=False):
    settings = request.app.state.settings
    return render(request, "cameras.html", active_page="cameras", cameras=_rows(request), checked=checked,
                  minutes=settings["CAMERA_CHECK_MINUTES"], after=settings["CAMERA_OFFLINE_AFTER"],
                  alerts=settings["CAMERA_ALERTS"],
                  scheduled=getattr(request.app.state, "capture_scheduler", None) is not None)


@router.get("/cameras", name="camera_status")
def camera_status(request: Request, checked: str = ""):
    return _page(request, checked=bool(checked))


@router.post("/cameras/check", name="check_cameras")
def check_cameras(request: Request):
    """Look at every camera right now (this can take a few seconds when one does not answer)."""
    request.app.state.camera_monitor.check_all(force=True)
    return RedirectResponse(url_path(request.app, "camera_status") + "?checked=1", status_code=303)
