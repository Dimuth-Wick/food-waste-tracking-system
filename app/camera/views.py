"""Take a capture by hand: POST /api/captures/run-now."""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.camera.capture import KINDS, CameraUnavailable, CaptureBusy
from app.web import api_error


router = APIRouter(tags=["Camera captures"])


class RunNow(BaseModel):
    meal: str = Field(examples=["breakfast"])
    kind: str = Field(examples=["start"], description="start or end")


class PhotoOut(BaseModel):
    station: str
    ok: bool
    file: str | None = Field(None, description="Where the photo was saved, inside the captures folder")
    error: str | None = None


class RunNowOut(BaseModel):
    meal: str
    kind: str
    ok_count: int
    failed_count: int
    photos: list[PhotoOut]


@router.post("/api/captures/run-now", name="run_capture_now", response_model=RunNowOut,
             summary="Take the start or end photos of a meal now")
def run_now(request: Request, body: RunNow):
    """Photographs the buffet cameras straight away, as the scheduler would at that point of the meal.

    One photo per camera, or several from a single camera. Returns 502 if no camera gave a photo.
    """
    service = request.app.state.capture_service
    meal, kind = body.meal.strip().lower(), body.kind.strip().lower()
    if meal not in service.schedule:
        return api_error(f"meal must be one of: {', '.join(service.schedule)}.", 400)
    if kind not in KINDS:
        return api_error("kind must be start or end.", 400)
    try:
        event = service.capture_event(meal, kind)
    except CameraUnavailable as error:
        return api_error(str(error), 503)
    except CaptureBusy as error:
        return api_error(str(error), 409)

    photos = [PhotoOut(station=photo.station, ok=photo.ok, file=photo.relative, error=photo.error)
              for photo in event.photos]
    if not event.ok_count:
        return api_error("No camera gave a photo. Check that the cameras are on and reachable.", 502,
                         photos=[photo.model_dump() for photo in photos])
    return RunNowOut(meal=meal, kind=kind, ok_count=event.ok_count, failed_count=event.failed_count, photos=photos)
