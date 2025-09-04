from __future__ import annotations

import logging
import tempfile
from typing import Any, Tuple

from django.core.management.base import BaseCommand
from openpyxl import Workbook

from pagasys.models import Employee
from capture.aws import (
    fetch_enroll_images,
    index_faces,
    company_collection_id,
)
from capture.models import FaceEnrollment


def rebuild_from_s3(logger: logging.Logger) -> Tuple[str, list[tuple[str, str]], list[str]]:
    reenrolled: list[tuple[str, str]] = []
    skipped: list[str] = []

    for emp in Employee.objects.all():
        logger.info("Processing %s (ID %s)", emp.get_full_name(), emp.id)
        if emp.company is None:
            logger.warning("Skipping %s: no company", emp.get_full_name())
            skipped.append(emp.get_full_name())
            continue
        images = fetch_enroll_images(emp.company.id, emp.id)
        logger.info("Found %d image(s) for %s", len(images), emp.get_full_name())
        if len(images) < 4:
            logger.warning(
                "Skipping %s: only %d image(s)", emp.get_full_name(), len(images)
            )
            skipped.append(emp.get_full_name())
            continue
        face_ids: list[str] = []
        for img in images:
            indexed = index_faces(emp.company.id, emp.id, img)
            face_ids.extend(indexed)
        FaceEnrollment.objects.update_or_create(
            employee=emp,
            defaults={
                "collection_id": company_collection_id(emp.company.id),
                "face_ids": face_ids,
                "status": "active",
            },
        )
        branch_name = emp.branch.name if emp.branch else "Unknown"
        reenrolled.append((branch_name, emp.get_full_name()))
        logger.info(
            "Reenrolled %s with %d face(s)", emp.get_full_name(), len(face_ids)
        )

    wb = Workbook()
    ws_re = wb.create_sheet("Reenrolled")
    ws_sk = wb.create_sheet("Skipped")
    wb.remove(wb.active)

    ws_re.append(["Branch", "Employee"])
    for branch, name in reenrolled:
        ws_re.append([branch, name])

    ws_sk.append(["Employee"])
    for name in skipped:
        ws_sk.append([name])

    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    wb.save(tmp.name)
    tmp.close()
    logger.info("Report written to %s", tmp.name)
    return tmp.name, reenrolled, skipped


class Command(BaseCommand):
    help = "Rebuild face enrollments from images stored in S3"

    def handle(self, *args: Any, **options: Any):
        logger = logging.getLogger(__name__)
        handler = logging.StreamHandler(self.stdout)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        path, reenrolled, skipped = rebuild_from_s3(logger)
        total = len(reenrolled) + len(skipped)
        logger.info(
            "Summary: processed %d employees, reenrolled %d, skipped %d",
            total,
            len(reenrolled),
            len(skipped),
        )
        if skipped:
            logger.info("Skipped employees: %s", ", ".join(skipped))
        else:
            logger.info("Skipped employees: none")
        logger.removeHandler(handler)
        self.reenrolled = reenrolled
        self.skipped = skipped
        return path
