"""Thin wrappers around AWS Rekognition and S3 for the capture layer."""

from __future__ import annotations

from django.utils import timezone
import hashlib
import uuid

import boto3
from django.conf import settings


def company_collection_id(company_id: int) -> str:
    """Return the Rekognition collection name for a company."""
    return f"reko-company-{company_id}"


def ensure_collection(collection_id: str) -> None:
    """Ensure the given Rekognition collection exists."""
    rk = boto3.client("rekognition", region_name=settings.AWS_REKOGNITION_REGION)
    try:
        rk.describe_collection(CollectionId=collection_id)
    except rk.exceptions.ResourceNotFoundException:
        rk.create_collection(CollectionId=collection_id)


def index_faces(company_id: int, employee_id: int, image_bytes: bytes) -> list[str]:
    """Index a face for an employee and return new FaceIds."""
    ensure_collection(company_collection_id(company_id))
    rk = boto3.client("rekognition", region_name=settings.AWS_REKOGNITION_REGION)
    resp = rk.index_faces(
        CollectionId=company_collection_id(company_id),
        Image={"Bytes": image_bytes},
        ExternalImageId=str(employee_id),
        DetectionAttributes=[],
        MaxFaces=1,
        QualityFilter="AUTO",
    )
    return [fr["Face"]["FaceId"] for fr in resp.get("FaceRecords", [])]


def delete_faces(company_id: int, face_ids: list[str]) -> None:
    """Delete the given FaceIds from the company's collection."""
    if not face_ids:
        return
    rk = boto3.client("rekognition", region_name=settings.AWS_REKOGNITION_REGION)
    rk.delete_faces(CollectionId=company_collection_id(company_id), FaceIds=face_ids)


def search_face_by_image(company_id: int, image_bytes: bytes, threshold: float):
    """Search for faces in the company's collection."""
    rk = boto3.client("rekognition", region_name=settings.AWS_REKOGNITION_REGION)
    return rk.search_faces_by_image(
        CollectionId=company_collection_id(company_id),
        Image={"Bytes": image_bytes},
        FaceMatchThreshold=int(threshold * 100) if threshold <= 1 else threshold,
        MaxFaces=3,
    )


def put_capture_to_s3(company_id: int, device_id: int, image_bytes: bytes) -> tuple[str, str]:
    """Upload capture image to S3 and return key and SHA256 hash."""
    today = timezone.localdate()
    key = (
        "attendance-capture/"
        f"{company_id}/{device_id}/{today:%Y/%m/%d}/"
        f"{uuid.uuid4().hex}.jpg"
    )
    return _put_to_s3(settings.AWS_S3_BUCKET_CAPTURE, key, image_bytes)


def put_enroll_to_s3(company_id: int, employee_id: int, image_bytes: bytes) -> tuple[str, str]:
    """Upload enrollment image to S3 and return key and SHA256 hash."""
    key = f"attendance-enroll/{company_id}/{employee_id}/{uuid.uuid4().hex}.jpg"
    return _put_to_s3(settings.AWS_S3_BUCKET_ENROLL, key, image_bytes)


def _put_to_s3(bucket: str, key: str, image_bytes: bytes) -> tuple[str, str]:
    s3 = boto3.client("s3")
    s3.put_object(Bucket=bucket, Key=key, Body=image_bytes, ContentType="image/jpeg")
    sha256 = hashlib.sha256(image_bytes).hexdigest()
    return key, sha256
