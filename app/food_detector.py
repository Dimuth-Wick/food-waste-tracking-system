"""Count food items in a photo with the OWLv2 open-vocabulary detector.

The user types what to count (for example "cupcake") and OWLv2 boxes every
match. Unlike a COCO detector such as YOLOS, OWLv2 is not limited to a fixed
list of classes, so it can count items it was never fine-tuned on.
"""

import re

from flask import current_app, jsonify, render_template, request, url_for

from app.image_upload import UploadError, read_uploaded_image


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


def _load_detector():
    """Build a ``detect(image, item, threshold)`` callable around OWLv2."""
    import torch
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    name = current_app.config.get("FOOD_DETECTOR_MODEL_NAME", MODEL_NAME)
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

    return detect


def _get_detector():
    """Load once per Flask app; tests may supply a detector through config."""
    detector = current_app.config.get("FOOD_DETECTOR")
    if detector is not None:
        return detector
    detector = current_app.extensions.get("food_detector")
    if detector is None:
        detector = _load_detector()
        current_app.extensions["food_detector"] = detector
    return detector


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


def _count(image, item, threshold):
    """Return one detection per item, strongest first, inside the photo."""
    width, height = image.size
    candidates = []
    for found in _get_detector()(image, item, threshold / 100):
        x0, y0, x1, y1 = found["box"]
        box = (max(0.0, min(x0, x1)), max(0.0, min(y0, y1)),
               min(float(width), max(x0, x1)), min(float(height), max(y0, y1)))
        if box[2] - box[0] >= 1 and box[3] - box[1] >= 1:
            candidates.append({"confidence": found["score"] * 100, "box": box})
    candidates.sort(key=lambda found: found["confidence"], reverse=True)

    detections = []
    for found in candidates:
        if not any(_is_duplicate(found["box"], kept["box"]) for kept in detections):
            detections.append(found)
    return detections


def _item_from_form():
    """Return the cleaned item name, or None if it is empty or unusable."""
    item = " ".join(request.form.get("item", "").split()).lower()
    if not item or len(item) > MAX_ITEM_LENGTH or not re.fullmatch(r"[a-z0-9 '\-]+", item):
        return None
    return item


def _error(message, status):
    return jsonify({"error": message}), status


def food_detection():
    """``GET /food-detection`` - the React counting page."""
    return render_template(
        "food_detection.html",
        active_page="food_detection",
        settings={
            "apiUrl": url_for("count_food"),
            "defaultItem": DEFAULT_ITEM,
            "quickItems": QUICK_ITEMS,
            "maxItemLength": MAX_ITEM_LENGTH,
            "minConfidence": MIN_CONFIDENCE,
            "defaultConfidence": DEFAULT_CONFIDENCE,
        },
    )


def count_food():
    """``POST /api/food-count`` - count one kind of item in an uploaded photo.

    Returns every match at or above ``MIN_CONFIDENCE`` with its box in the
    photo's pixel coordinates. Nothing is saved.
    """
    try:
        # Read the upload first: it sets the request size limit before the
        # multipart body is parsed for the other form fields.
        image = read_uploaded_image("Choose a photo before counting.")
    except UploadError as error:
        return _error(error.message, error.status)

    item = _item_from_form()
    if item is None:
        return _error("Type the food item to count using letters, numbers, spaces "
                      f"or hyphens (up to {MAX_ITEM_LENGTH} characters).", 400)

    try:
        detections = _count(image, item, MIN_CONFIDENCE)
    except ImportError:
        current_app.logger.exception("Food counter dependencies are missing")
        return _error("The counting model needs PyTorch and Transformers. "
                      "Install requirements.txt and restart the server.", 503)
    except Exception:
        current_app.logger.exception("Food counting failed")
        return _error("Counting failed. The first run downloads the model, so "
                      "check the internet connection and the server logs.", 500)

    width, height = image.size
    return jsonify({
        "item": item,
        "image": {"width": width, "height": height},
        "minConfidence": MIN_CONFIDENCE,
        "detections": [
            {"confidence": round(found["confidence"], 1),
             "box": [round(value, 1) for value in found["box"]]}
            for found in detections
        ],
    })
