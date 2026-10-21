"""Turn counted photos into meal checks.

For each date, meal and station, the START photos are paired with the END photos. Once both sides have
counted photos a draft is created, "waiting for confirmation". The camera cannot know how many guests
came, so staff add that, can correct a count, and confirm. Only then are the meal checks (and through
them the waste and shortage records) saved, with the existing meal check code.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.camera.store import combined_counts, ensure_camera_tables, foods_for
from app.database.prices import FALLBACK_PRICE, food_for_camera, price_map
from app.database.queries import SHORTAGE_REASON, create_meal_check
from app.database.tables import CameraFoodRow, CaptureCountRow, CaptureRow, MealCheckDraftRow


MAX_PIECES = 10_000
MAX_GUESTS = 100_000


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def pair_drafts(db: Session) -> list[int]:
    """Create a waiting draft for every date, meal and station that has counted start AND end photos."""
    ensure_camera_tables(db)
    sides = {}
    for day, meal, station, kind in db.execute(
            select(CaptureRow.capture_date, CaptureRow.meal_type, CaptureRow.station, CaptureRow.kind)
            .where(CaptureRow.count_status == "counted").distinct()):
        sides.setdefault((day, meal, station), set()).add(kind)
    existing = {tuple(row) for row in db.execute(select(MealCheckDraftRow.capture_date, MealCheckDraftRow.meal_type,
                                                       MealCheckDraftRow.station))}
    new = [MealCheckDraftRow(capture_date=day, meal_type=meal, station=station, status="waiting", created_at=_now_text())
           for (day, meal, station), kinds in sorted(sides.items())
           if kinds == {"start", "end"} and (day, meal, station) not in existing]
    db.add_all(new)
    db.commit()
    return [row.id for row in new]


def _photo(row: CaptureRow, counts: dict, detections: list, directory: Path, photo_url) -> dict:
    size = None
    if row.file_path:
        try:
            with Image.open(Path(directory) / row.file_path) as image:   # reads only the header
                size = image.size
        except OSError:
            size = None
    return {
        "id": row.id, "url": photo_url(row.id) if size else None, "time": row.captured_at,
        "status": row.status if size or row.status == "failed" else "missing", "error": row.error,
        "countStatus": row.count_status, "countError": row.count_error,
        "counts": counts, "detections": detections, "width": size[0] if size else None, "height": size[1] if size else None,
    }


def _food_lines(db: Session, start: dict, end: dict, foods: list[CameraFoodRow]) -> list[dict]:
    """One line per food the station looks for: the start and end counts, what a piece weighs and what a kg costs."""
    pricing = price_map(db)
    lines = []
    for food in foods:
        category = food_for_camera(db, food.count_label, food.dish)
        lines.append({"label": food.count_label, "dish": food.dish, "kgPerPiece": food.kg_per_piece,
                      "pricePerKg": pricing["prices"].get(category.id, pricing["mixed"]),
                      "start": start.get(food.count_label, 0), "end": end.get(food.count_label, 0)})
    return lines


def day_view(db: Session, day: str | None, settings, photo_url) -> dict:
    """Everything the camera page shows for one date: photos by meal and station, counts, drafts, cameras."""
    ensure_camera_tables(db)
    pair_drafts(db)
    dates = list(db.scalars(select(CaptureRow.capture_date).distinct().order_by(CaptureRow.capture_date.desc())))
    zone = ZoneInfo(settings["TIMEZONE"])
    today = datetime.now(zone).strftime("%Y-%m-%d")
    day = day if day in dates else (dates[0] if dates else today)

    rows = db.scalars(select(CaptureRow).where(CaptureRow.capture_date == day).order_by(CaptureRow.captured_at, CaptureRow.id)).all()
    counts, detections = {}, {}
    for capture_id, label, count, found in db.execute(
            select(CaptureCountRow.capture_id, CaptureCountRow.label, CaptureCountRow.count, CaptureCountRow.detections)
            .where(CaptureCountRow.capture_id.in_([row.id for row in rows]))):
        counts.setdefault(capture_id, {})[label] = count
        detections.setdefault(capture_id, []).extend({**match, "label": label} for match in json.loads(found or "[]"))
    drafts = {(draft.meal_type, draft.station): draft for draft in db.scalars(
        select(MealCheckDraftRow).where(MealCheckDraftRow.capture_date == day))}

    schedule = settings["MEAL_SCHEDULE"]
    meals = list(schedule) + sorted({row.meal_type for row in rows} - set(schedule))
    cameras = [camera["name"] for camera in settings["CAMERA_SOURCES"]]
    view_meals = []
    for meal in meals:
        meal_rows = [row for row in rows if row.meal_type == meal]
        stations = list(dict.fromkeys(cameras + [row.station for row in meal_rows]))
        groups = []
        for station in stations:
            sides = {}
            for kind in ("start", "end"):
                photos = [row for row in meal_rows if row.station == station and row.kind == kind]
                counted = [counts.get(row.id, {}) for row in photos if row.count_status == "counted"]
                sides[kind] = {
                    "photos": [_photo(row, counts.get(row.id, {}), detections.get(row.id, []),
                                      settings["CAPTURE_DIR"], photo_url) for row in photos],
                    "combined": combined_counts(counted, kind) if counted else None,
                }
            draft = drafts.get((meal, station))
            groups.append({"station": station, "start": sides["start"], "end": sides["end"],
                           "draft": _draft_view(db, draft, sides) if draft else None})
        view_meals.append({"meal": meal, "times": schedule.get(meal), "stations": groups,
                           "photoCount": len(meal_rows)})

    return {"date": day, "dates": dates, "today": today, "meals": view_meals,
            "cameras": camera_status(db, cameras),
            "counting": db.query(CaptureRow).filter(CaptureRow.count_status == "pending").count()}


def _draft_view(db: Session, draft: MealCheckDraftRow, sides: dict) -> dict:
    view = {"id": draft.id, "status": draft.status, "confirmedAt": draft.confirmed_at}
    if draft.status == "confirmed":
        view.update(json.loads(draft.details or "{}"))
        return view
    foods = foods_for(db, draft.station)
    view["foods"] = _food_lines(db, sides["start"]["combined"] or {}, sides["end"]["combined"] or {}, foods)
    return view


def camera_status(db: Session, cameras: list[str]) -> list[dict]:
    """For each configured camera, whether its last photo worked."""
    status = []
    for name in cameras:
        last = db.scalars(select(CaptureRow).where(CaptureRow.station == name)
                          .order_by(CaptureRow.captured_at.desc(), CaptureRow.id.desc()).limit(1)).first()
        status.append({"station": name, "state": "none" if last is None else ("ok" if last.status == "ok" else "offline"),
                       "lastAt": last.captured_at if last else None, "error": last.error if last else None})
    return status


class DraftError(ValueError):
    def __init__(self, message, status=400, fields=None):
        super().__init__(message)
        self.status, self.fields = status, fields or {}


def confirm_draft(db: Session, draft_id: int, data: dict, settings, *, lookups, actor) -> dict:
    """Save the meal checks of a draft: one per food that was put out (or ran short).

    data: guest_count, area_id, reason_id, foods: [{label, start_count, end_count, short_count}].
    Raises DraftError with the problem fields; saves nothing in that case.
    """
    draft = db.get(MealCheckDraftRow, draft_id)
    if draft is None:
        raise DraftError("This meal check does not exist.", 404)
    if draft.status != "waiting":
        raise DraftError("This meal check was already confirmed.", 409)

    errors = {}
    guests = data.get("guest_count")
    if not isinstance(guests, int) or isinstance(guests, bool) or not 0 < guests <= MAX_GUESTS:
        errors["guest_count"] = "Enter how many guests came, at least 1."
    areas = {item.id: item for item in lookups["areas"]}
    reasons = {item.id: item for item in lookups["reasons"] if item.name != SHORTAGE_REASON}
    if data.get("area_id") not in areas:
        errors["area_id"] = "Choose an area."
    if data.get("reason_id") not in reasons:
        errors["reason_id"] = "Choose a reason for the leftovers."
    station_foods = {food.count_label: food for food in foods_for(db, draft.station)}
    lines = []
    for line in data.get("foods") or []:
        label = line.get("label")
        food = station_foods.get(label)
        values = [line.get(key, 0) for key in ("start_count", "end_count", "short_count")]
        if food is None:
            errors[f"foods.{label}"] = "This food is not on the station's list."
        elif not all(isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_PIECES for value in values):
            errors[f"foods.{label}"] = f"Counts must be whole numbers from 0 to {MAX_PIECES:,}."
        elif values[1] > values[0]:
            errors[f"foods.{label}"] = "There can't be more left at the end than at the start."
        else:
            lines.append((food, *values))
    if not errors and not any(start or short for _, start, _, short in lines):
        errors["foods"] = "No food was counted at the start of this meal, so there is nothing to save."
    if errors:
        raise DraftError("Check the highlighted fields.", 400, errors)

    end_time = settings["MEAL_SCHEDULE"].get(draft.meal_type, {}).get("end", "23:59")
    ended = datetime.fromisoformat(f"{draft.capture_date}T{end_time}").replace(tzinfo=ZoneInfo(settings["TIMEZONE"]))
    saved, waste_ids, summary = [], [], []
    pricing = price_map(db)
    for food, start, end, short in lines:
        if not (start or short):
            continue
        category = food_for_camera(db, food.count_label, food.dish)
        check, leftovers, shortage = create_meal_check(
            db, event_at=ended, meal_type=draft.meal_type.capitalize(), food_item=food.dish or food.count_label.capitalize(),
            count_label=food.count_label, start_count=start, end_count=end, short_count=short,
            kg_per_piece=food.kg_per_piece, guest_count=guests, area_id=data["area_id"], reason_id=data["reason_id"],
            user_id=actor.id, category_id=category.id)
        saved.append(check.id)
        waste_ids += [record.id for record in (leftovers, shortage) if record]
        price = pricing["prices"].get(category.id, pricing["mixed"])
        summary.append({"label": food.count_label, "dish": food.dish, "start": start, "end": end, "short": short,
                        "eatenKg": round(check.eaten_kg, 3), "wasteKg": round(end * food.kg_per_piece, 3),
                        "shortKg": round(short * food.kg_per_piece, 3), "wasteValue": round(end * food.kg_per_piece * price)})

    draft.status, draft.confirmed_at = "confirmed", _now_text()
    draft.meal_check_ids = json.dumps(saved)
    draft.details = json.dumps({"guests": guests, "area": areas[data["area_id"]].name,
                                "reason": reasons[data["reason_id"]].name, "foods": summary})
    db.commit()
    return {"meal_check_ids": saved, "waste_record_ids": waste_ids, "date": draft.capture_date}
