"""Shared upload handling for the computer-vision demo pages."""

import io
import warnings

from fastapi import UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_BYTES = 8 * 1024 * 1024
TOO_LARGE_MESSAGE = "Choose an image smaller than 8 MB."


class UploadError(Exception):
    """An upload problem the page should show to the user."""

    def __init__(self, message, status):
        super().__init__(message)
        self.message = message
        self.status = status


def read_uploaded_image(upload: UploadFile | None, missing_message: str):
    """Return the uploaded file as an upright RGB image or raise UploadError.

    Requests over 9 MB are already refused by app.web.RequestSizeLimit.
    """
    if upload is None or not upload.filename:
        raise UploadError(missing_message, 400)

    data = upload.file.read(MAX_IMAGE_BYTES + 1)
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

