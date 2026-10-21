"""Camera capture APIs: take photos now, the day's photos and drafts, confirm a draft, the food list."""

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.camera.capture import KINDS, CameraUnavailable, CaptureBusy
from app.camera.meals import DraftError, confirm_draft, day_view
from app.camera.store import ensure_camera_tables
from app.database.connection import get_session
from app.database.queries import get_user_by_username
from app.database.tables import CameraFoodRow, CaptureRow
from app.forecast.views import FOOD_ITEMS
from app.waste_records.common import DEMO_USERNAME, load_lookups
from app.web import api_error, url_path


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
    capture_ids: list[int] = Field(description="The stored photos; they are counted in the background")


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
    return RunNowOut(meal=meal, kind=kind, ok_count=event.ok_count, failed_count=event.failed_count, photos=photos,
                     capture_ids=event.capture_ids)


def _photo_url(request: Request):
    return lambda capture_id: url_path(request.app, "capture_photo", capture_id=capture_id)


@router.get("/api/captures", name="list_captures", summary="One day's camera photos, counts and meal checks")
def list_captures(request: Request, date: str = "", db: Session = Depends(get_session)) -> dict[str, Any]:
    """Photos grouped by meal and station, start next to end, with what was counted in each and the
    draft meal checks waiting for confirmation. Without a date, the newest day with photos."""
    try:
        return day_view(db, date.strip() or None, request.app.state.settings, _photo_url(request))
    except SQLAlchemyError:
        return api_error("The database is unavailable.", 503)


@router.get("/captures/{capture_id}/photo", name="capture_photo", include_in_schema=False)
def capture_photo(request: Request, capture_id: int, db: Session = Depends(get_session)):
    """A captured photo, looked up by its id so no file path ever comes from the browser."""
    row = db.get(CaptureRow, capture_id) if 0 < capture_id < 2**63 else None
    folder = Path(request.app.state.settings["CAPTURE_DIR"]).resolve()
    path = (folder / row.file_path).resolve() if row is not None and row.file_path else None
    if path is None or folder not in path.parents or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


class FoodLine(BaseModel):
    label: str
    start_count: int = 0
    end_count: int = 0
    short_count: int = 0


class ConfirmDraft(BaseModel):
    guest_count: Any = None
    area_id: Any = None
    reason_id: Any = None
    foods: list[FoodLine] = []


@router.post("/api/captures/drafts/{draft_id}/confirm", name="confirm_meal_check_draft",
             summary="Confirm a meal check counted from the cameras")
def confirm(request: Request, draft_id: int, body: ConfirmDraft, db: Session = Depends(get_session)):
    """Saves one meal check per food, with the existing meal check code: leftovers become waste records,
    shortages "Ran out" records, and what was eaten feeds the meal forecast."""
    try:
        ensure_camera_tables(db)
        lookups = load_lookups(db, active_only=True)
        actor = get_user_by_username(db, DEMO_USERNAME)
        if actor is None or not actor.active:
            return api_error("Demo entry data is missing. Initialize and seed the local database first.", 503)
        result = confirm_draft(db, draft_id, body.model_dump(), request.app.state.settings, lookups=lookups, actor=actor)
    except DraftError as error:
        return api_error(str(error), error.status, fields=error.fields)
    except SQLAlchemyError:
        db.rollback()
        return api_error("The meal check could not be saved. Try again.", 500)
    return {**result, "day_url": url_path(request.app, "day_details", day=result["date"])}


class CameraFood(BaseModel):
    id: int | None = None
    count_label: str
    dish: str | None = None
    kg_per_piece: float
    active: bool = True


def _food(row: CameraFoodRow) -> dict:
    return {"id": row.id, "count_label": row.count_label, "dish": row.dish, "kg_per_piece": row.kg_per_piece,
            "active": bool(row.active), "station": row.station}


@router.get("/api/camera-foods", name="list_camera_foods", summary="The foods the cameras look for")
def list_camera_foods(db: Session = Depends(get_session)):
    ensure_camera_tables(db)
    return {"foods": [_food(row) for row in db.scalars(select(CameraFoodRow).order_by(CameraFoodRow.id))],
            "dishes": FOOD_ITEMS}


@router.put("/api/camera-foods", name="save_camera_foods", summary="Change the foods the cameras look for")
def save_camera_foods(foods: list[CameraFood], db: Session = Depends(get_session)):
    """The whole shared list. A food left out is switched off (not deleted), so past counts keep their meaning."""
    ensure_camera_tables(db)
    errors, seen = {}, set()
    for index, food in enumerate(foods):
        label = " ".join(food.count_label.split()).lower()
        if not re.fullmatch(r"[a-z][a-z0-9 '\-]{1,39}", label):
            errors[f"{index}.count_label"] = "Use 2 to 40 letters, numbers, spaces or hyphens, such as bread roll."
        elif label in seen and food.active:
            errors[f"{index}.count_label"] = f"{label} is on the list twice."
        if food.dish and food.dish not in FOOD_ITEMS:
            errors[f"{index}.dish"] = "Choose a dish from the list, or leave it empty."
        if not 0 < food.kg_per_piece <= 20:
            errors[f"{index}.kg_per_piece"] = "Enter a weight above 0 and up to 20 kg."
        if food.active:
            seen.add(label)
    if errors:
        return api_error("Check the highlighted foods.", 400, fields=errors)

    shared = {row.id: row for row in db.scalars(select(CameraFoodRow).where(CameraFoodRow.station.is_(None)))}
    kept = set()
    for food in foods:
        row = shared.get(food.id) if food.id is not None else None
        if row is None:
            row = CameraFoodRow(station=None)
            db.add(row)
        row.count_label, row.dish = " ".join(food.count_label.split()).lower(), food.dish or None
        row.kg_per_piece, row.active = food.kg_per_piece, int(food.active)
        if food.id is not None:
            kept.add(food.id)
    for row_id, row in shared.items():
        if row_id not in kept:
            row.active = 0
    db.commit()
    return list_camera_foods(db)
