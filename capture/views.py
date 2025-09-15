import logging
import secrets
import time
from datetime import timedelta

from django.conf import settings
from botocore.exceptions import ClientError
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions, generics, parsers, filters as drf_filters
from rest_framework.decorators import action
from rest_framework.response import Response
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiResponse, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from pagasys.utils import scope_queryset, ensure_in_scope
from pagasys.policy.permissions import (
    IsCompanyMember,
    ActionRolePermission,
    CompanyScopedQuerysetMixin,
)
from pagasys.policy.backends import ScopeFilterBackend
from pagasys.models import Company, Employee, RosterEntry, ShiftTemplate
from pagasys.openapi_utils import document_filters
from .models import AttendanceDevice, FaceEnrollment, EnrollmentLink, PunchEvent, PunchException
from .serializers import (
    AttendanceDeviceSerializer,
    RotateKeyResponseSerializer,
    FaceEnrollmentStatusSerializer,
    EnrollmentLinkCreateSerializer,
    EnrollmentLinkResponseSerializer,
    EnrollmentSubmitSerializer,
    EnrollmentSubmitResponseSerializer,
    PunchRequestSerializer,
    PunchResponseSerializer,
    PunchEventSerializer,
)
from .filters import AttendanceDeviceFilter, PunchEventFilter
from .authentication import DeviceKeyAuthentication
from .aws import (
    company_collection_id,
    ensure_collection,
    index_faces,
    delete_all_employee_faces,
    put_enroll_to_s3,
    put_capture_to_s3,
    search_face_by_image,
)
from .utils import (
    localize_to_company,
    compute_roster_date,
    within_device_scope,
    geofence_ok,
    get_face_threshold,
    get_geofence_requirement,
)
from .image_validators import validate_image, ImageValidationError

logger = logging.getLogger(__name__)

# --------- Device management ---------


@extend_schema_view(
    list=extend_schema(description="List registered capture devices."),
    create=extend_schema(description="Register a new capture device."),
    retrieve=extend_schema(description="Retrieve a specific capture device."),
    update=extend_schema(description="Update a capture device."),
    partial_update=extend_schema(description="Partially update a capture device."),
    destroy=extend_schema(description="Delete a capture device."),
)
@extend_schema(tags=["Capture"], description="Manage attendance capture devices and API keys.")
class AttendanceDeviceViewSet(CompanyScopedQuerysetMixin, viewsets.ModelViewSet):
    """CRUD interface for attendance capture devices."""

    permission_classes = [permissions.IsAuthenticated, IsCompanyMember, ActionRolePermission]
    serializer_class = AttendanceDeviceSerializer
    queryset = AttendanceDevice.objects.all()
    filter_backends = [ScopeFilterBackend, DjangoFilterBackend, drf_filters.OrderingFilter, drf_filters.SearchFilter]
    filterset_class = AttendanceDeviceFilter
    ordering = ["id"]
    search_fields = ["name", "api_key"]

    def _ensure_scope(self, serializer):
        for field in ("branch", "department", "project"):
            obj = serializer.validated_data.get(field)
            if obj:
                ensure_in_scope(obj, self.request.user, field)

    def get_queryset(self):
        qs = self.queryset.select_related("company", "branch", "department", "project")
        return super().get_queryset().filter(company=self.get_company())

    def perform_create(self, serializer):
        self._ensure_scope(serializer)
        serializer.save(company=self.get_company(), api_key=secrets.token_urlsafe(32))

    def perform_update(self, serializer):
        self._ensure_scope(serializer)
        serializer.save()

    @extend_schema(
        description="Generate a new API key for the device.",
        request=None,
        responses=RotateKeyResponseSerializer,
    )
    @action(detail=True, methods=["post"], url_path="rotate-key")
    def rotate_key(self, request, company_id=None, pk=None):
        device = self.get_object()
        device.api_key = secrets.token_urlsafe(32)
        device.save(update_fields=["api_key"])
        return Response(RotateKeyResponseSerializer({"api_key": device.api_key}).data)


# --------- Face Enrollment (authenticated, manager/admin scope) ---------


@extend_schema(tags=["Capture"], description="Manage employee face enrollments.")
class FaceEnrollmentViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, IsCompanyMember, ActionRolePermission]

    def _get_employee(self, company_id, employee_id):
        emp = get_object_or_404(Employee, pk=employee_id)
        allowed_emp_ids = set(scope_queryset(Employee.objects.all(), self.request.user).values_list("id", flat=True))
        if emp.id not in allowed_emp_ids:
            return Response({"detail": "Employee outside your scope", "errors": {}}, status=403)
        return emp

    @extend_schema(
        description="Retrieve face enrollment status for an employee.",
        responses=FaceEnrollmentStatusSerializer,
    )
    @action(detail=False, methods=["get"], url_path=r"employees/(?P<employee_id>\d+)/face")
    def status(self, request, company_id=None, employee_id=None):
        emp = self._get_employee(company_id, employee_id)
        if isinstance(emp, Response):
            return emp
        fe = getattr(emp, "face_enrollment", None)
        if not fe:
            return Response({"status": "none"})
        return Response(FaceEnrollmentStatusSerializer(fe).data)

    @extend_schema(
        description="Create or revoke a face enrollment link for an employee.",
        request=EnrollmentLinkCreateSerializer,
        responses={
            200: EnrollmentLinkResponseSerializer,
            204: OpenApiResponse(description="Link revoked"),
        },
    )
    @action(
        detail=False,
        methods=["post", "delete"],
        url_path=r"employees/(?P<employee_id>\d+)/face/enrollment-link",
    )
    def create_link(self, request, company_id=None, employee_id=None):
        emp = self._get_employee(company_id, employee_id)
        if isinstance(emp, Response):
            return emp
        if request.method == "POST":
            ensure_collection(company_collection_id(company_id))
            ser = EnrollmentLinkCreateSerializer(data=request.data or {})
            ser.is_valid(raise_exception=True)
            expires = timezone.now() + timedelta(
                hours=ser.validated_data["expires_in_hours"]
            )
            link = EnrollmentLink.objects.create(
                employee=emp,
                expires_at=expires,
                max_uses=ser.validated_data["max_uses"],
            )
            payload = {
                "url": link.url,
                "token": link.token,
                "expires_at": link.expires_at,
            }
            return Response(EnrollmentLinkResponseSerializer(payload).data)
        EnrollmentLink.objects.filter(
            employee=emp,
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).update(expires_at=timezone.now())
        return Response(status=204)

    @extend_schema(
        description="Revoke an employee's existing face enrollment, removing all stored face templates and enrollment data.",
        responses={
            204: OpenApiResponse(description="Enrollment revoked"),
            403: OpenApiResponse(description="Forbidden"),
            404: OpenApiResponse(description="Employee not found"),
        },
    )
    @action(detail=False, methods=["delete"], url_path=r"employees/(?P<employee_id>\d+)/face")
    def revoke(self, request, company_id=None, employee_id=None):
        emp = self._get_employee(company_id, employee_id)
        if isinstance(emp, Response):
            return emp
        fe = getattr(emp, "face_enrollment", None)
        if fe:
            fe.delete()
        return Response(status=204)


# --------- Public Enrollment Submit (token) ---------


@extend_schema(
    tags=["Capture"],
    description="Submit enrollment photos using a one-time token.",
)
class EnrollmentSubmitView(generics.GenericAPIView):
    permission_classes = []
    serializer_class = EnrollmentSubmitSerializer
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def get(self, request, token: str):
        link = get_object_or_404(EnrollmentLink, token=token)
        if not link.is_valid:
            return TemplateResponse(
                request,
                "capture/enroll.html",
                {"error": "Link invalid or expired"},
                status=403,
            )
        return TemplateResponse(request, "capture/enroll.html", {"token": token})

    @extend_schema(
        request=EnrollmentSubmitSerializer,
        responses={
            200: EnrollmentSubmitResponseSerializer,
            403: OpenApiResponse(description="Link invalid or expired"),
        },
    )
    def post(self, request, token: str):
        link = get_object_or_404(EnrollmentLink, token=token)
        if not link.is_valid:
            return Response({"detail": "Link invalid or expired"}, status=403)
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        emp = link.employee
        collection_id = company_collection_id(emp.company.id)
        ensure_collection(collection_id)
        fe = FaceEnrollment.objects.filter(employee=emp).first()
        if fe:
            delete_all_employee_faces(emp.company.id, emp.id)
        face_ids = []
        for img in ser.validated_data["images"]:
            bytes_ = img.read()
            try:
                validate_image(bytes_)
            except ImageValidationError as exc:
                return Response({"detail": str(exc)}, status=400)
            put_enroll_to_s3(emp.company.id, emp.id, bytes_)
            face_ids.extend(index_faces(emp.company.id, emp.id, bytes_))
        with transaction.atomic():
            FaceEnrollment.objects.update_or_create(
                employee=emp,
                defaults={
                    "collection_id": collection_id,
                    "face_ids": face_ids,
                    "status": "active",
                },
            )
        link.mark_used()
        payload = {"faces_indexed": len(face_ids)}
        return Response(EnrollmentSubmitResponseSerializer(payload).data)


# --------- Punch Capture (device-auth only) ---------


@method_decorator(
    ratelimit(key="ip", rate=settings.CAPTURE_PUNCH_RATE_LIMIT, block=True),
    name="post",
)
@extend_schema(
    tags=["Capture"],
    description="Capture a punch event from a device.",
    parameters=[
        OpenApiParameter(
            "X-Device-Key",
            OpenApiTypes.STR,
            OpenApiParameter.HEADER,
            description="Device API key",
            required=True,
        )
    ],
)
class CapturePunchView(generics.GenericAPIView):
    authentication_classes = [DeviceKeyAuthentication]
    permission_classes = []
    serializer_class = PunchRequestSerializer
    parser_classes = [parsers.MultiPartParser, parsers.JSONParser, parsers.FormParser]

    @extend_schema(
        request=PunchRequestSerializer,
        responses={
            200: PunchResponseSerializer,
            403: OpenApiResponse(PunchResponseSerializer, description="Punch rejected"),
        },
    )
    def post(self, request):
        device = request.device
        device.last_seen = timezone.now()
        device.save(update_fields=["last_seen"])
        company = device.company
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        image_bytes = None
        img_file = request.FILES.get("image") or request.FILES.get("file")
        if img_file:
            image_bytes = img_file.read()
        elif "image_b64" in request.data:
            import base64

            image_bytes = base64.b64decode(request.data["image_b64"])

        ext_id = data.get("external_id") or ""

        hinted_emp = None
        if data.get("employee_id"):
            hinted_emp = Employee.objects.filter(pk=data["employee_id"]).first()

        company_local_dt = localize_to_company(company, data["timestamp"])
        roster_date, roster_entry, roster_fallback = (None, None, False)
        matched_emp = None
        face_ok = False
        confidence = None
        requires_face = False
        face_mismatch = False
        geofence_rule = None

        if hinted_emp:
            roster_date, roster_entry, roster_fallback = compute_roster_date(
                hinted_emp, company_local_dt
            )

        s3_key, sha256 = ("", "")
        search_res = None
        if image_bytes:
            threshold = float(settings.FACE_MATCH_DEFAULT_MIN_CONF)
            if roster_entry:
                threshold = get_face_threshold(roster_entry.shift, roster_date)
                requires_face = roster_entry.shift.requires_face
                geofence_rule = get_geofence_requirement(roster_entry.shift, roster_date)

            timings: dict[str, float] = {}

            start_all = time.monotonic()

            # Upload image to S3 first
            start = time.monotonic()
            logger.debug("capture.upload.start")
            try:
                s3_key, sha256 = put_capture_to_s3(company.id, device.id, image_bytes)
            except Exception:
                logger.exception("put_capture_to_s3 failed")
                return Response({"detail": "image_upload_failed"}, status=400)
            finally:
                elapsed = time.monotonic() - start
                timings["upload"] = elapsed
                logger.debug("capture.upload.end %.3f", elapsed)

            # Then search face by image
            start = time.monotonic()
            logger.debug("capture.search.start")
            try:
                search_res = search_face_by_image(company.id, image_bytes, threshold)
            except ClientError:
                logger.exception("search_face_by_image failed")
                return Response({"detail": "face_search_failed"}, status=400)
            except Exception:
                logger.exception("search_face_by_image failed")
                return Response({"detail": "face_search_failed"}, status=400)
            finally:
                elapsed = time.monotonic() - start
                timings["search"] = elapsed
                logger.debug("capture.search.end %.3f", elapsed)

            total = time.monotonic() - start_all
            logger.info(
                "capture.timings upload=%.3f search=%.3f total=%.3f",
                timings.get("upload", 0.0),
                timings.get("search", 0.0),
                total,
            )

        if search_res is not None:
            matches = search_res.get("FaceMatches", []) or []
            if matches:
                top = max(matches, key=lambda m: m.get("Similarity", 0))
                sim = float(top.get("Similarity", 0))
                confidence = sim / 100.0 if sim > 1 else sim
                ext = top["Face"].get("ExternalImageId")
                if ext and ext.isdigit():
                    matched_emp = Employee.objects.filter(pk=int(ext)).first()
                    if matched_emp:
                        if data.get("employee_id") and matched_emp.id != data["employee_id"]:
                            face_mismatch = True
                        else:
                            face_ok = True
                    else:
                        face_mismatch = True
                else:
                    face_mismatch = True
            else:
                face_mismatch = True
        elif roster_entry:
            geofence_rule = get_geofence_requirement(roster_entry.shift, roster_date)

        employee = hinted_emp
        unrostered_face_match = False
        if hinted_emp:
            if roster_entry is None:
                roster_date, roster_entry, roster_fallback = compute_roster_date(
                    employee, company_local_dt
                )
            if roster_entry:
                requires_face = roster_entry.shift.requires_face
                if geofence_rule is None:
                    geofence_rule = get_geofence_requirement(
                        roster_entry.shift, roster_date
                    )
        elif matched_emp:
            roster_date, roster_entry, roster_fallback = compute_roster_date(
                matched_emp, company_local_dt
            )
            if roster_entry:
                employee = matched_emp
                requires_face = roster_entry.shift.requires_face
                if geofence_rule is None:
                    geofence_rule = get_geofence_requirement(
                        roster_entry.shift, roster_date
                    )
            else:
                face_mismatch = True
                unrostered_face_match = True


        out_scope = False
        if employee:
            out_scope = not within_device_scope(device, employee)
        geo_ok = geofence_ok(device, data.get("lat"), data.get("lon"))
        geofence_rule_violation = False
        geofence_rule_reason = None
        if geofence_rule is not None:
            if not (device.latitude and device.longitude and device.radius_m):
                geofence_rule_violation = True
                geofence_rule_reason = "missing_device_geofence"
            elif device.radius_m > geofence_rule:
                geofence_rule_violation = True
                geofence_rule_reason = "radius_exceeds_rule"
        if geofence_rule_violation:
            geo_ok = None

        accepted = True
        reason = None
        fe = getattr(employee, "face_enrollment", None) if employee else None
        if requires_face:
            if not (fe and fe.status == "active"):
                accepted = False
                reason = "no_enrollment"
            elif face_mismatch or not face_ok:
                accepted = False
                reason = "face_required_no_match"

        if geo_ok is False and getattr(settings, "CAPTURE_BLOCK_GEOFENCE", False):
            accepted = False
            reason = reason or "geofence"

        if geofence_rule_violation:
            accepted = False
            reason = "geofence_rule"

        if out_scope and getattr(settings, "CAPTURE_BLOCK_OUT_OF_SCOPE", False):
            accepted = False
            reason = reason or "outside_scope"

        if unrostered_face_match:
            accepted = False
            reason = "unrostered_face_match"

        if face_mismatch and reason is None:
            reason = "face_mismatch"

        try:
            with transaction.atomic():
                ev = PunchEvent.objects.create(
                    device=device,
                    company=company,
                    employee=employee,
                    matched_employee=matched_emp,
                    action=data["action"],
                    device_ts=company_local_dt,
                    s3_key=s3_key,
                    image_bytes_sha256=sha256,
                    face_matched=bool(face_ok),
                    face_confidence=confidence,
                    roster_date=roster_date,
                    requires_face=bool(requires_face),
                    out_of_scope=out_scope,
                    geofence_ok=geo_ok,
                    geofence_rule_violation=geofence_rule_violation,
                    roster_fallback=roster_fallback,
                    external_id=ext_id,
                    # TODO: remove notes in favor of explicit reason field
                    notes=reason or "",
                )
        except IntegrityError:
            ev = PunchEvent.objects.filter(device=device, external_id=ext_id).first()

        from .tasks import finalize_punch

        finalize_punch.delay(ev.id)

        if reason == "face_required_no_match":
            PunchException.objects.get_or_create(
                event=ev,
                defaults={"kind": "face_required_no_match", "details": {}},
            )
        elif reason == "no_enrollment":
            PunchException.objects.get_or_create(
                event=ev,
                defaults={"kind": "no_enrollment", "details": {}},
            )
        elif reason == "unrostered_face_match":
            PunchException.objects.get_or_create(
                event=ev,
                defaults={"kind": "unrostered_face_match", "details": {}},
            )
        elif out_scope and not settings.CAPTURE_BLOCK_OUT_OF_SCOPE:
            PunchException.objects.get_or_create(
                event=ev,
                defaults={"kind": "outside_scope", "details": {}},
            )
        elif geofence_rule_violation:
            PunchException.objects.get_or_create(
                event=ev,
                defaults={
                    "kind": "geofence_rule",
                    "details": {"reason": geofence_rule_reason} if geofence_rule_reason else {},
                },
            )
        elif geo_ok is False and not settings.CAPTURE_BLOCK_GEOFENCE:
            PunchException.objects.get_or_create(
                event=ev,
                defaults={"kind": "geofence", "details": {}},
            )
        elif face_mismatch:
            PunchException.objects.get_or_create(
                event=ev,
                defaults={"kind": "face_mismatch", "details": {}},
            )

        payload = {
            "accepted": bool(accepted),
            "roster_date": ev.roster_date.isoformat() if ev.roster_date else None,
            "matched_employee": ev.matched_employee_id,
            "face_confidence": float(ev.face_confidence) if ev.face_confidence is not None else None,
            "face_mismatch": face_mismatch,
            "requires_face": ev.requires_face,
            "out_of_scope": ev.out_of_scope,
            "geofence_ok": ev.geofence_ok,
            "geofence_rule_violation": ev.geofence_rule_violation,
            "roster_fallback": ev.roster_fallback,
            "reason": reason or "",
            "notes": ev.notes,  # Deprecated: use `reason`
            "event_id": ev.id,
        }
        status_code = 200 if accepted else 403
        return Response(PunchResponseSerializer(payload).data, status=status_code)


# --------- Punch event listing (RBAC & scope) ---------


@extend_schema_view(
    list=extend_schema(description="List captured punch events."),
    retrieve=extend_schema(description="Retrieve a captured punch event."),
)
@extend_schema(tags=["Capture"], description="Read-only access to captured punch events.")
class PunchEventViewSet(CompanyScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsCompanyMember, ActionRolePermission]
    serializer_class = PunchEventSerializer
    queryset = PunchEvent.objects.all()
    filter_backends = [ScopeFilterBackend, DjangoFilterBackend, drf_filters.OrderingFilter, drf_filters.SearchFilter]
    filterset_class = PunchEventFilter
    ordering = ["-server_ts"]
    search_fields = ["employee__username", "device__name", "external_id"]

    def get_queryset(self):
        qs = self.queryset.select_related("device", "company", "employee", "matched_employee")
        company = self.get_company()
        qs = qs.filter(company=company)
        allowed_emp_ids = scope_queryset(Employee.objects.all(), self.request.user).values_list("id", flat=True)
        allowed_dev_ids = scope_queryset(AttendanceDevice.objects.all(), self.request.user).values_list("id", flat=True)
        return qs.filter(
            (Q(employee_id__in=allowed_emp_ids) | Q(matched_employee_id__in=allowed_emp_ids))
            | Q(device_id__in=allowed_dev_ids)
        )


document_filters(AttendanceDeviceViewSet)
document_filters(PunchEventViewSet)
