import cv2
import numpy as np


class ImageValidationError(Exception):
    """Raised when an enrollment image fails quality checks."""


def validate_image(image_bytes: bytes) -> None:
    """Validate lighting, clarity, distance, and centering of a face image.

    Raises ImageValidationError if any check fails.
    """
    arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ImageValidationError("Invalid image data")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Lighting check (mean brightness between 60 and 200)
    mean = gray.mean()
    if mean < 60 or mean > 200:
        raise ImageValidationError("Improper lighting")

    # Blur check using Laplacian variance
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    if variance < 100:
        raise ImageValidationError("Image is blurry")

    # Face detection using Haar cascade
    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
    if len(faces) != 1:
        raise ImageValidationError("Face not detected properly")
    x, y, w, h = faces[0]
    img_h, img_w = gray.shape

    # Distance check based on face area ratio
    area_ratio = (w * h) / float(img_w * img_h)
    if area_ratio < 0.05 or area_ratio > 0.5:
        raise ImageValidationError("Face at incorrect distance")

    # Centering check
    cx, cy = x + w / 2.0, y + h / 2.0
    if abs(cx - img_w / 2.0) > img_w * 0.15 or abs(cy - img_h / 2.0) > img_h * 0.15:
        raise ImageValidationError("Face not centered")
