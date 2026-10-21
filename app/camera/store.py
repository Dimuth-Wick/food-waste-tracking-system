"""The capture tables: every photo the cameras take, what was counted in it, and the foods to look for.

Every photo stays on disk (instance/captures/...) and in the captures table, and its counts are written
both to capture_counts and to a .json file next to the photo, so they can later become a labelled
training dataset.
"""

from datetime import datetime, timezone
import json
import logging
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageOps
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.camera.capture import CaptureEvent, KINDS, slug
from app.database.tables import CameraFoodRow, CaptureCountRow, CaptureRow, MealCheckDraftRow


logger = logging.getLogger(__name__)

# A food counts when the model is at least this sure (the Food counting page's default). Weaker
# matches down to the model's minimum are still stored with their scores, for the training dataset.
COUNT_CONFIDENCE = 30

# What the cameras look for until the kitchen edits the list: count label, menu dish, kg per piece.
DEFAULT_FOODS = [
    ("bread roll", "Bread", 0.05),
    ("egg", "Egg curry", 0.06),
    ("donut", "Dessert pudding", 0.07),
    ("cupcake", "Dessert pudding", 0.06),
    ("apple", "Fruit platter", 0.18),
]

_PHOTO_NAME = re.compile(r"(?P<station>[A-Za-z0-9_-]+?)_(?P<time>\d{6})(?:-\d+)?\.jpg")
_TABLES = (CaptureRow.__table__, CaptureCountRow.__table__, CameraFoodRow.__table__, MealCheckDraftRow.__table__)


def _now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_camera_tables(db: Session) -> None:
    """Create the capture tables in databases made before they existed, and the default food list."""
    bind = db.get_bind()
    for table in _TABLES:
        table.create(bind, checkfirst=True)
    if db.scalar(select(CameraFoodRow.id).limit(1)) is None:
        db.add_all(CameraFoodRow(count_label=label, dish=dish, kg_per_piece=kg, active=1)
                   for label, dish, kg in DEFAULT_FOODS)
        db.commit()


def camera_tables_exist(db: Session) -> bool:
    return inspect(db.get_bind()).has_table(CaptureRow.__tablename__)


def foods_for(db: Session, station: str) -> list[CameraFoodRow]:
    """The foods to look for at a station: its own list if it has one, otherwise the shared list."""
    rows = db.scalars(select(CameraFoodRow).where(CameraFoodRow.active == 1)).all()
    own = [row for row in rows if row.station == station]
    return own or [row for row in rows if row.station is None]


def record_event(db: Session, event: CaptureEvent, directory: Path) -> list[int]:
    """Store every photo of a capture event, including failed ones. Returns the ids of the photos to count."""
    ensure_camera_tables(db)
    rows = []
    for photo in event.photos:
        rows.append(CaptureRow(
            captured_at=_utc(photo.captured_at), capture_date=photo.captured_at.strftime("%Y-%m-%d"),
            meal_type=event.meal, kind=event.kind, station=photo.station,
            file_path=photo.relative, status="ok" if photo.ok else "failed", error=photo.error,
            count_status="pending" if photo.ok else "not_counted", created_at=_now_text(),
        ))
    db.add_all(rows)
    db.commit()
    return [row.id for row in rows if row.status == "ok"]


def sync_from_disk(db: Session, directory: Path, cameras: list[dict], timezone_name: str) -> list[int]:
    """Add photos found in the captures folder that the database does not know yet (for example ones
    taken before this table existed). Returns their ids. Files that do not fit the folder layout are left alone.
    """
    ensure_camera_tables(db)
    directory = Path(directory)
    if not directory.is_dir():
        return []
    known = set(db.scalars(select(CaptureRow.file_path).where(CaptureRow.file_path.is_not(None))))
    names = {slug(camera["name"]): camera["name"] for camera in cameras}
    zone = ZoneInfo(timezone_name)
    rows = []
    for path in sorted(directory.glob("*/*/*/*.jpg")):
        relative = path.relative_to(directory).as_posix()
        if relative in known:
            continue
        day, meal, kind, name = relative.split("/")
        match = _PHOTO_NAME.fullmatch(name)
        if not (match and kind in KINDS and re.fullmatch(r"[a-z]{3,20}", meal)):
            continue
        try:
            taken = datetime.strptime(f"{day} {match['time']}", "%Y-%m-%d %H%M%S").replace(tzinfo=zone)
        except ValueError:
            continue
        station = names.get(match["station"], match["station"].replace("-", " "))
        rows.append(CaptureRow(captured_at=_utc(taken), capture_date=day, meal_type=meal, kind=kind,
                               station=station, file_path=relative, status="ok", count_status="pending",
                               created_at=_now_text()))
    db.add_all(rows)
    db.commit()
    if rows:
        logger.info("Found %d photos in the captures folder that were not in the database yet.", len(rows))
    return [row.id for row in rows]


def pending_ids(db: Session) -> list[int]:
    return list(db.scalars(select(CaptureRow.id).where(CaptureRow.count_status == "pending").order_by(CaptureRow.id)))


def count_capture(db: Session, capture_id: int, counter, directory: Path, model_name: str) -> str:
    """Count every food of the station in one photo and store the result. Returns the new count status.

    ``counter(image, labels, min_confidence)`` returns [{"label", "confidence", "box"}]. Never raises:
    a problem is stored on the photo as count_status "failed" with the reason.
    """
    row = db.get(CaptureRow, capture_id)
    if row is None or row.status != "ok" or row.count_status not in ("pending", "failed", "needs_setup"):
        return row.count_status if row else "missing"
    try:
        foods = foods_for(db, row.station)
        if not foods:
            row.count_status, row.count_error = "needs_setup", "No foods are set up for this station yet."
            db.commit()
            return row.count_status
        labels = list(dict.fromkeys(food.count_label for food in foods))
        path = Path(directory) / row.file_path
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
        from app.vision.counting import MIN_CONFIDENCE
        found = counter(image, labels, MIN_CONFIDENCE)

        db.query(CaptureCountRow).filter(CaptureCountRow.capture_id == row.id).delete()
        now = _now_text()
        summary = {}
        for label in labels:
            matches = [match for match in found if match["label"] == label]
            count = sum(1 for match in matches if match["confidence"] >= COUNT_CONFIDENCE)
            boxes = [{"confidence": round(match["confidence"], 1), "box": [round(v, 1) for v in match["box"]]}
                     for match in matches]
            db.add(CaptureCountRow(capture_id=row.id, label=label, count=count, confidence_threshold=COUNT_CONFIDENCE,
                                   model_name=model_name, detections=json.dumps(boxes), created_at=now))
            summary[label] = {"count": count, "detections": boxes}
        row.count_status, row.count_error, row.counted_at = "counted", None, now
        db.commit()
        _write_sidecar(path, row, summary, model_name, image.size)
        return row.count_status
    except Exception as error:
        db.rollback()
        logger.exception("Counting photo %s failed.", capture_id)
        row = db.get(CaptureRow, capture_id)
        row.count_status = "failed"
        row.count_error = f"Counting failed ({type(error).__name__}). It will be tried again when the app restarts."
        db.commit()
        return row.count_status


def _write_sidecar(path: Path, row: CaptureRow, summary: dict, model_name: str, size) -> None:
    """The counts and boxes next to the photo, so the captures folder alone is a labelled dataset."""
    sidecar = path.with_suffix(".json")
    data = {"photo": path.name, "station": row.station, "meal": row.meal_type, "kind": row.kind,
            "captured_at": row.captured_at, "image_size": list(size), "model": model_name,
            "count_confidence": COUNT_CONFIDENCE, "foods": summary}
    try:
        sidecar.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        logger.warning("Could not write %s", sidecar)


def photo_counts(db: Session, capture_ids: list[int]) -> dict[int, dict[str, int]]:
    """{capture id: {label: count}} for counted photos."""
    rows = db.execute(select(CaptureCountRow.capture_id, CaptureCountRow.label, CaptureCountRow.count)
                      .where(CaptureCountRow.capture_id.in_(capture_ids))).all()
    counts = {}
    for capture_id, label, count in rows:
        counts.setdefault(capture_id, {})[label] = count
    return counts


def combined_counts(per_photo: list[dict[str, int]], kind: str) -> dict[str, int]:
    """One count per food for a capture event: the HIGHEST at the start of a meal (nothing hidden yet),
    the LOWEST at the end (the plate least blocked by people or serving spoons)."""
    pick = max if kind == "start" else min
    labels = {label for counts in per_photo for label in counts}
    return {label: pick(counts.get(label, 0) for counts in per_photo) for label in sorted(labels)}
