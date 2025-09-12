"""Thin wrappers around AWS Rekognition and S3 for the capture layer."""

from __future__ import annotations

import hashlib
import uuid

from django.conf import settings
from django.utils import timezone
import logging

try:  # pragma: no cover - boto3 is optional in tests
    import boto3  # type: ignore
    from botocore.exceptions import (  # type: ignore
        NoCredentialsError,
        ClientError,
    )
except ModuleNotFoundError:  # pragma: no cover
    boto3 = None  # type: ignore
    NoCredentialsError = Exception  # type: ignore
    ClientError = Exception  # type: ignore


logger = logging.getLogger(__name__)

_session: "boto3.session.Session | None" = None
_rk_client = None
_s3_client = None


def _get_session():
    """Return a cached boto3 session."""
    global _session
    if _session is None:  # pragma: no branch - simple cache
        if boto3 is None:  # pragma: no cover
            raise RuntimeError("boto3 is required for AWS operations")
        _session = boto3.session.Session()
    return _session


def get_rk_client():
    """Return a cached Rekognition client."""
    global _rk_client
    if _rk_client is None:
        _rk_client = _get_session().client(
            "rekognition", region_name=settings.AWS_REKOGNITION_REGION
        )
    return _rk_client


def get_s3_client():
    """Return a cached S3 client."""
    global _s3_client
    if _s3_client is None:
        _s3_client = _get_session().client("s3")
    return _s3_client


def reset_clients():  # pragma: no cover - used in tests
    global _session, _rk_client, _s3_client
    _session = _rk_client = _s3_client = None


def _aws_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except (NoCredentialsError, ClientError) as exc:  # pragma: no cover - simple wrapper
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if code in {"Throttling", "ThrottlingException"}:
            logger.warning("AWS throttling: %s", code)
        else:
            logger.warning("AWS call failed: %s", exc)
        raise


def company_collection_id(company_id: int) -> str:
    """Return the Rekognition collection name for a company."""
    return f"{settings.AWS_REKOGNITION_COLLECTION_PREFIX}-{company_id}"


def ensure_collection(collection_id: str) -> None:
    """Ensure the given Rekognition collection exists."""
    if boto3 is None:  # pragma: no cover
        raise RuntimeError("boto3 is required for Rekognition operations")
    rk = get_rk_client()
    try:
        _aws_call(rk.describe_collection, CollectionId=collection_id)
    except rk.exceptions.ResourceNotFoundException:
        _aws_call(rk.create_collection, CollectionId=collection_id)
    except NoCredentialsError:  # pragma: no cover
        # In environments without AWS credentials (e.g. tests), skip creating
        # the collection so calls depending on it can still proceed.
        pass


def index_faces(company_id: int, employee_id: int, image_bytes: bytes) -> list[str]:
    """Index a face for an employee and return new FaceIds."""
    ensure_collection(company_collection_id(company_id))
    if boto3 is None:  # pragma: no cover
        raise RuntimeError("boto3 is required for Rekognition operations")
    rk = get_rk_client()
    resp = _aws_call(
        rk.index_faces,
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
    if boto3 is None:  # pragma: no cover
        raise RuntimeError("boto3 is required for Rekognition operations")
    rk = get_rk_client()
    _aws_call(
        rk.delete_faces,
        CollectionId=company_collection_id(company_id),
        FaceIds=face_ids,
    )


def delete_all_employee_faces(company_id: int, employee_id: int) -> None:
    """Delete **all** faces for an employee from the company's collection.

    This scans the collection for any Face records matching the employee's
    ``ExternalImageId``. It ensures stale or previously untracked faces are
    also removed so they can no longer be recognized.
    """
    if boto3 is None:  # pragma: no cover
        raise RuntimeError("boto3 is required for Rekognition operations")
    rk = get_rk_client()
    collection = company_collection_id(company_id)
    face_ids: list[str] = []
    try:
        paginator = rk.get_paginator("list_faces")
        for page in paginator.paginate(CollectionId=collection):
            for face in page.get("Faces", []):
                if face.get("ExternalImageId") == str(employee_id):
                    face_ids.append(face["FaceId"])
    except rk.exceptions.ResourceNotFoundException:
        return
    if face_ids:
        _aws_call(
            rk.delete_faces, CollectionId=collection, FaceIds=face_ids
        )


def _company_collections(rk) -> list[str]:
    """Yield all Rekognition collections managed by this app."""
    collections: list[str] = []
    paginator = rk.get_paginator("list_collections")
    for page in paginator.paginate():
        for coll in page.get("CollectionIds", []):
            if coll.startswith(f"{settings.AWS_REKOGNITION_COLLECTION_PREFIX}-"):
                collections.append(coll)
    return collections


def count_all_faces() -> int:
    """Return the total number of faces across all company collections."""
    if boto3 is None:  # pragma: no cover
        raise RuntimeError("boto3 is required for Rekognition operations")
    rk = get_rk_client()
    total = 0
    paginator = rk.get_paginator("list_faces")
    for coll in _company_collections(rk):
        for page in paginator.paginate(CollectionId=coll):
            total += len(page.get("Faces", []))
    return total


def delete_all_faces() -> None:
    """Delete all faces from every company collection."""
    if boto3 is None:  # pragma: no cover
        raise RuntimeError("boto3 is required for Rekognition operations")
    rk = get_rk_client()
    paginator = rk.get_paginator("list_faces")
    for coll in _company_collections(rk):
        face_ids: list[str] = []
        for page in paginator.paginate(CollectionId=coll):
            for face in page.get("Faces", []):
                face_ids.append(face.get("FaceId"))
        if face_ids:
            _aws_call(rk.delete_faces, CollectionId=coll, FaceIds=face_ids)


def search_face_by_image(company_id: int, image_bytes: bytes, threshold: float):
    """Search for faces in the company's collection."""
    if boto3 is None:  # pragma: no cover
        raise RuntimeError("boto3 is required for Rekognition operations")
    rk = get_rk_client()
    collection = company_collection_id(company_id)
    try:
        return _aws_call(
            rk.search_faces_by_image,
            CollectionId=collection,
            Image={"Bytes": image_bytes},
            FaceMatchThreshold=int(threshold * 100) if threshold <= 1 else threshold,
            MaxFaces=3,
        )
    except rk.exceptions.ResourceNotFoundException:
        ensure_collection(collection)
        return _aws_call(
            rk.search_faces_by_image,
            CollectionId=collection,
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


def fetch_enroll_images(company_id: int, employee_id: int) -> list[bytes]:
    """Return enrollment images for an employee from S3."""
    if boto3 is None:  # pragma: no cover
        raise RuntimeError("boto3 is required for S3 operations")
    s3 = get_s3_client()
    prefix = f"attendance-enroll/{company_id}/{employee_id}/"
    images: list[bytes] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(
        Bucket=settings.AWS_S3_BUCKET_ENROLL, Prefix=prefix
    ):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            resp = s3.get_object(
                Bucket=settings.AWS_S3_BUCKET_ENROLL, Key=key
            )
            images.append(resp["Body"].read())
    return images


def _put_to_s3(bucket: str, key: str, image_bytes: bytes) -> tuple[str, str]:
    if boto3 is None:  # pragma: no cover
        raise RuntimeError("boto3 is required for S3 operations")
    s3 = get_s3_client()
    _aws_call(
        s3.put_object,
        Bucket=bucket,
        Key=key,
        Body=image_bytes,
        ContentType="image/jpeg",
    )
    sha256 = hashlib.sha256(image_bytes).hexdigest()
    return key, sha256
