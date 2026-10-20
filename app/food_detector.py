"""Object-detection demo using the pretrained hustvl/yolos-small COCO model.

Unlike the Food-101 classifier, which names one dish for the whole photo,
YOLOS finds every object it recognises and returns a bounding box for each.
It was trained on COCO, so it only knows 80 everyday object classes; of those,
only the ones in ``FOOD_LABELS`` are food.
"""

from flask import current_app, render_template, request
from PIL import ImageDraw, ImageFont

from app.image_upload import UploadError, jpeg_preview, read_uploaded_image


MODEL_NAME = "hustvl/yolos-small"
THRESHOLDS = (50, 70, 90)
DEFAULT_THRESHOLD = 70

FOOD_LABELS = frozenset({
    "apple", "banana", "broccoli", "cake", "carrot", "donut", "hot dog",
    "orange", "pizza", "sandwich",
})
TABLEWARE_LABELS = frozenset({
    "bottle", "bowl", "cup", "dining table", "fork", "knife", "spoon",
    "wine glass",
})
GROUP_COLOURS = {"food": "#1f8a5b", "tableware": "#d08a1f", "other": "#6b7c86"}


def _group(label):
    if label in FOOD_LABELS:
        return "food"
    if label in TABLEWARE_LABELS:
        return "tableware"
    return "other"


def _load_detector():
    """Build a ``detect(image, threshold)`` callable around the YOLOS model."""
    import torch
    from transformers import AutoImageProcessor, AutoModelForObjectDetection

    name = current_app.config.get("FOOD_DETECTOR_MODEL_NAME", MODEL_NAME)
    processor = AutoImageProcessor.from_pretrained(name)
    model = AutoModelForObjectDetection.from_pretrained(name).eval()

    def detect(image, threshold):
        inputs = processor(images=image, return_tensors="pt")
        with torch.inference_mode():
            outputs = model(**inputs)
        result = processor.post_process_object_detection(
            outputs, threshold=threshold,
            target_sizes=torch.tensor([image.size[::-1]]),
        )[0]
        return [
            {"label": model.config.id2label[int(label)], "score": float(score),
             "box": [float(value) for value in box]}
            for score, label, box in zip(
                result["scores"], result["labels"], result["boxes"])
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


def _detect(image, threshold):
    width, height = image.size
    detections = []
    for item in _get_detector()(image, threshold / 100):
        x0, y0, x1, y1 = item["box"]
        box = (max(0.0, min(x0, x1)), max(0.0, min(y0, y1)),
               min(float(width), max(x0, x1)), min(float(height), max(y0, y1)))
        if box[2] - box[0] < 1 or box[3] - box[1] < 1:
            continue
        detections.append({
            "label": item["label"].title(),
            "group": _group(item["label"]),
            "confidence": item["score"] * 100,
            "box": box,
        })
    detections.sort(key=lambda item: item["confidence"], reverse=True)
    return detections


def _draw_boxes(image, detections):
    """Return a copy of ``image`` with each detection outlined and labelled."""
    image = image.copy()
    draw = ImageDraw.Draw(image)
    line = max(2, round(max(image.size) / 300))
    font = ImageFont.load_default(size=max(12, round(max(image.size) / 45)))
    for number, item in enumerate(detections, start=1):
        colour = GROUP_COLOURS[item["group"]]
        draw.rectangle(item["box"], outline=colour, width=line)
        caption = f"{number}. {item['label']} {item['confidence']:.0f}%"
        left, top = item["box"][0], item["box"][1]
        text_box = draw.textbbox((left, top), caption, font=font)
        text_height = text_box[3] - text_box[1] + line * 2
        top = top - text_height if top >= text_height else top
        text_box = draw.textbbox((left + line, top + line), caption, font=font)
        draw.rectangle((left, top, text_box[2] + line, text_box[3] + line), fill=colour)
        draw.text((left + line, top + line), caption, fill="#ffffff", font=font)
    return image


def _threshold_from_form():
    try:
        value = int(request.form.get("threshold", DEFAULT_THRESHOLD))
    except ValueError:
        value = DEFAULT_THRESHOLD
    return value if value in THRESHOLDS else DEFAULT_THRESHOLD


def food_detection():
    """Show the upload form and temporary, unsaved detections."""
    context = {"active_page": "food_detection", "detections": None,
               "thresholds": THRESHOLDS, "threshold": DEFAULT_THRESHOLD}
    if request.method == "GET":
        return render_template("food_detection.html", **context)

    context["threshold"] = _threshold_from_form()
    try:
        image = read_uploaded_image("Choose an image before detecting.")
        context["detections"] = _detect(image, context["threshold"])
    except UploadError as error:
        context["error"] = error.message
        return render_template("food_detection.html", **context), error.status
    except ImportError:
        current_app.logger.exception("Food detector dependencies are missing")
        context["error"] = ("The detection model needs PyTorch and Transformers. "
                            "Install requirements.txt and restart the server.")
        return render_template("food_detection.html", **context), 503
    except Exception:
        current_app.logger.exception("Food detection failed")
        context["error"] = ("Detection failed. The first run downloads the model, so "
                            "check the internet connection and the server logs.")
        return render_template("food_detection.html", **context), 500

    context["food_count"] = sum(item["group"] == "food" for item in context["detections"])
    context["preview"] = jpeg_preview(_draw_boxes(image, context["detections"]))
    return render_template("food_detection.html", **context)
