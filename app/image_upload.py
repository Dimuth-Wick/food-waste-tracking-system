"""Shared upload handling for the computer-vision demo pages."""

import io
import warnings

from flask import request
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.exceptions import RequestEntityTooLarge


MAX_IMAGE_BYTES = 8 * 1024 * 1024
TOO_LARGE_MESSAGE = "Choose an image smaller than 8 MB."


class UploadError(Exception):
    """An upload problem the page should show to the user."""

    def __init__(self, message, status):
        super().__init__(message)
        self.message = message
        self.status = status


def read_uploaded_image(missing_message, field="image"):
    """Return the uploaded file as an upright RGB image or raise UploadError."""
    request.max_content_length = MAX_IMAGE_BYTES + 1024 * 1024
    try:
        uploaded = request.files.get(field)
    except RequestEntityTooLarge:
        raise UploadError(TOO_LARGE_MESSAGE, 413) from None
    if uploaded is None or not uploaded.filename:
        raise UploadError(missing_message, 400)

    data = uploaded.stream.read(MAX_IMAGE_BYTES + 1)
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise UploadError(TOO_LARGE_MESSAGE, 400)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                return ImageOps.exif_transpose(image).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        raise UploadError("The uploaded file is not a valid image.", 400) from None

