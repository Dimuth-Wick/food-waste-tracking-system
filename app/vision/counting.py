"""Count food items in a photo with the OWLv2 open-vocabulary detector.

The user types what to count (for example "cupcake") and OWLv2 boxes every
match. Unlike a COCO detector such as YOLOS, OWLv2 is not limited to a fixed
list of classes, so it can count items it was never fine-tuned on.
"""

import logging
import re
import threading

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.connection import get_session
from app.vision.meal_check import meal_check_settings

from app.vision.uploads import UploadError, read_uploaded_image
from app.web import api_error, render, url_path


logger = logging.getLogger(__name__)
router = APIRouter(tags=["Food counting"])


MODEL_NAME = "google/owlv2-base-patch16-ensemble"
# The API returns every match down to this confidence; the page's slider
# then filters them in the browser without re-running the model.
MIN_CONFIDENCE = 20
DEFAULT_CONFIDENCE = 30
DEFAULT_ITEM = "cupcake"
QUICK_ITEMS = ("cupcake", "egg", "bread roll", "donut", "apple")
MAX_ITEM_LENGTH = 40

# Boxes that overlap this much are treated as the same item.
DUPLICATE_IOU = 0.5
# A box this much inside a stronger box is a part of that item, not a new one.
DUPLICATE_CONTAINED = 0.8
# Photos are shrunk to this longest side before counting (OWLv2 works at 960 px anyway), which keeps
# memory bounded for large camera frames. Boxes are scaled back to the original photo.
MAX_COUNT_SIDE = 1280

# One lock for loading and running the model: it is loaded once, and the camera worker and a page
# request never run it at the same moment (each run already uses every CPU core).
_MODEL_LOCK = threading.RLock()


def _load_detector(settings):
    """Build a ``detect(image, item, threshold)`` callable around OWLv2."""
    import torch
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    name = settings.get("FOOD_COUNTER_MODEL_NAME", MODEL_NAME)
    processor = AutoProcessor.from_pretrained(name)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(name).eval()

    def detect(image, item, threshold):
        inputs = processor(images=image, text=[[f"a photo of a {item}"]],
                           return_tensors="pt")
        with torch.inference_mode():
            outputs = model(**inputs)
        # OWLv2 pads the photo to a square, so boxes are scaled to that square.
        side = max(image.size)
        result = processor.post_process_grounded_object_detection(
            outputs, threshold=threshold, target_sizes=torch.tensor([[side, side]]),
        )[0]
        return [
            {"score": float(score), "box": [float(value) for value in box]}
            for score, box in zip(result["scores"], result["boxes"])
        ]

    def detect_many(image, labels, threshold):
        """Look for every label in one pass; each box comes back with the label it matched best."""
        inputs = processor(images=image, text=[[f"a photo of a {label}" for label in labels]],
                           return_tensors="pt")
        with torch.inference_mode():
            outputs = model(**inputs)
        side = max(image.size)
        result = processor.post_process_grounded_object_detection(
            outputs, threshold=threshold, target_sizes=torch.tensor([[side, side]]),
        )[0]
        return [
            {"label": labels[int(index)], "score": float(score), "box": [float(value) for value in box]}
            for score, box, index in zip(result["scores"], result["boxes"], result["labels"])
        ]

    detect.many = detect_many
    return detect


def _get_detector(app):
    """Load once per app; tests may supply a detector as settings["FOOD_COUNTER"]."""
    detector = app.state.settings.get("FOOD_COUNTER") or getattr(app.state, "food_counter", None)
    if detector is None:
        with _MODEL_LOCK:
            detector = getattr(app.state, "food_counter", None)
            if detector is None:
                detector = _load_detector(app.state.settings)
                app.state.food_counter = detector
    return detector


def _shrunk(image):
    """The photo at most MAX_COUNT_SIDE on its longest side, and the factor to scale boxes back."""
    longest = max(image.size)
    if longest <= MAX_COUNT_SIDE:
        return image, 1.0
    factor = MAX_COUNT_SIDE / longest
    return image.resize((round(image.width * factor), round(image.height * factor))), 1 / factor


def _inside(found_box, width, height, scale):
    """The box scaled back to the original photo and clipped to it, or None if nothing is left."""
    x0, y0, x1, y1 = (value * scale for value in found_box)
    box = (max(0.0, min(x0, x1)), max(0.0, min(y0, y1)),
           min(float(width), max(x0, x1)), min(float(height), max(y0, y1)))
    return box if box[2] - box[0] >= 1 and box[3] - box[1] >= 1 else None


def _one_per_item(candidates):
    """Strongest first; a box overlapping a stronger one is the same item and is dropped."""
    candidates.sort(key=lambda found: found["confidence"], reverse=True)
    kept = []
    for found in candidates:
        if not any(_is_duplicate(found["box"], other["box"]) for other in kept):
            kept.append(found)
    return kept


def count_labels(app, image, labels, threshold):
    """Count several foods in one photo: [{"label", "confidence", "box"}], one entry per item.

    Every food is looked for at once. An item matched by two labels (a cupcake that also looks like
    a donut) is counted once, under the label it matched best.
    """
    detector = _get_detector(app)
    small, scale = _shrunk(image)
    with _MODEL_LOCK:
        if hasattr(detector, "many"):
            found = detector.many(small, list(labels), threshold / 100)
        else:  # a simple detector (as in tests) answers one label at a time
            found = [{**match, "label": label} for label in labels for match in detector(small, label, threshold / 100)]
    candidates = []
    for match in found:
        box = _inside(match["box"], image.width, image.height, scale)
        if box is not None:
            candidates.append({"label": match["label"], "confidence": match["score"] * 100, "box": box})
    return _one_per_item(candidates)


def _area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def _is_duplicate(box, kept):
    left, top = max(box[0], kept[0]), max(box[1], kept[1])
    right, bottom = min(box[2], kept[2]), min(box[3], kept[3])
    overlap = max(0.0, right - left) * max(0.0, bottom - top)
    if not overlap:
        return False
    union = _area(box) + _area(kept) - overlap
    return (overlap / union >= DUPLICATE_IOU
            or overlap / min(_area(box), _area(kept)) >= DUPLICATE_CONTAINED)


def _count(app, image, item, threshold):
    """Return one detection per item, strongest first, inside the photo."""
    detector = _get_detector(app)
    small, scale = _shrunk(image)
    with _MODEL_LOCK:
        found = detector(small, item, threshold / 100)
    candidates = []
    for match in found:
        box = _inside(match["box"], image.width, image.height, scale)
        if box is not None:
            candidates.append({"confidence": match["score"] * 100, "box": box})
    return _one_per_item(candidates)


def _clean_item(raw: str) -> str | None:
    """Return the cleaned item name, or None if it is empty or unusable."""
    item = " ".join(raw.split()).lower()
    if not item or len(item) > MAX_ITEM_LENGTH or not re.fullmatch(r"[a-z0-9 '\-]+", item):
        return None
    return item


class ImageSize(BaseModel):
    width: int
    height: int


class Detection(BaseModel):
    confidence: float
    box: list[float]


class FoodCount(BaseModel):
    item: str
    image: ImageSize
    minConfidence: int
    detections: list[Detection]


@router.get("/food-counting", name="food_counting", include_in_schema=False)
def food_counting(request: Request, db: Session = Depends(get_session)):

    return render(
        request, "_react_page.html",
        react_page="counting",
        active_page="food_counting",
        heading="Food counting",
        description=("The buffet cameras photograph each meal at its start and end, and every food on the list "
                     "is counted automatically. Add the guests to a finished meal and confirm it: the pieces left "
                     "over are saved as waste, and what was eaten updates the meal forecast."),
        settings={
            "apiUrl": url_path(request.app, "count_food"),
            "defaultItem": DEFAULT_ITEM,
            "quickItems": QUICK_ITEMS,
            "maxItemLength": MAX_ITEM_LENGTH,
            "minConfidence": MIN_CONFIDENCE,
            "defaultConfidence": DEFAULT_CONFIDENCE,
            "mealCheck": meal_check_settings(request, db),
            "camera": {
                "capturesUrl": url_path(request.app, "list_captures"),
                "runNowUrl": url_path(request.app, "run_capture_now"),
                "foodsUrl": url_path(request.app, "list_camera_foods"),
                "confirmUrl": url_path(request.app, "confirm_meal_check_draft", draft_id=0).replace("/0/", "/{id}/"),
                "meals": list(request.app.state.settings["MEAL_SCHEDULE"]),
                "camerasConfigured": bool(request.app.state.settings["CAMERA_SOURCES"]),
                "testMode": request.app.state.settings["CAPTURE_TEST_MODE"],
                "timezone": request.app.state.settings["TIMEZONE"],
                "currency": request.app.state.settings["CURRENCY_SYMBOL"],
                "dayUrl": url_path(request.app, "day_details", day="DATE"),
            },
        },
    )


@router.post("/api/food-count", name="count_food", response_model=FoodCount,
             summary="Count one kind of food item in a photo")
def count_food(request: Request, image: UploadFile | None = File(None), item: str = Form("")):
    """Returns every match at or above MIN_CONFIDENCE with its box in pixels. Nothing is saved."""
    try:
        photo = read_uploaded_image(image, "Choose a photo before counting.")
    except UploadError as error:
        return api_error(error.message, error.status)

    cleaned = _clean_item(item)
    if cleaned is None:
        return api_error("Type the food item to count using letters, numbers, spaces "
                         f"or hyphens (up to {MAX_ITEM_LENGTH} characters).", 400)
    try:
        detections = _count(request.app, photo, cleaned, MIN_CONFIDENCE)
    except ImportError:
        logger.exception("Food counter dependencies are missing")
        return api_error("The counting model needs PyTorch and Transformers. "
                         "Install requirements.txt and restart the server.", 503)
    except Exception:
        logger.exception("Food counting failed")
        return api_error("Counting failed. The first run downloads the model, so "
                         "check the internet connection and the server logs.", 500)

    width, height = photo.size
    return FoodCount(
        item=cleaned,
        image=ImageSize(width=width, height=height),
        minConfidence=MIN_CONFIDENCE,
        detections=[Detection(confidence=round(found["confidence"], 1),
                              box=[round(value, 1) for value in found["box"]])
                    for found in detections],
    )
