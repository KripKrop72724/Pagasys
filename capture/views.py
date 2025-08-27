import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import viewsets, permissions, generics, parsers, filters as drf_filters
from rest_framework.decorators import action
from rest_framework.response import Response

from pagasys.utils import scope_queryset
from pagasys.policy.permissions import (
    IsCompanyMember,
    ActionRolePermission,
    CompanyScopedQuerysetMixin,
)
from pagasys.models import Company, Employee, RosterEntry, ShiftTemplate
from .models import AttendanceDevice, FaceEnrollment, EnrollmentLink, PunchEvent, PunchException
from .serializers import (
    AttendanceDeviceSerializer,
    RotateKeyResponseSerializer,
    FaceEnrollmentStatusSerializer,
    EnrollmentLinkCreateSerializer,
    EnrollmentSubmitSerializer,
    PunchRequestSerializer,
    PunchEventSerializer,
)
from .filters import AttendanceDeviceFilter, PunchEventFilter
from .authentication import DeviceKeyAuthentication
from .aws import (
    company_collection_id,
    ensure_collection,
    index_faces,
    delete_faces,
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
)


# --------- Device management ---------


class AttendanceDeviceViewSet(CompanyScopedQuerysetMixin, viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsCompanyMember, ActionRolePermission]
    serializer_class = AttendanceDeviceSerializer
    filter_backends = [DjangoFilterBackend, drf_filters.OrderingFilter, drf_filters.SearchFilter]
    filterset_class = AttendanceDeviceFilter
    ordering = ["id"]
    search_fields = ["name", "api_key"]

    def get_queryset(self):
        qs = AttendanceDevice.objects.select_related("company", "branch", "department", "project")
        return super().get_queryset().filter(company=self.get_company())

    def perform_create(self, serializer):
        serializer.save(company=self.get_company(), api_key=secrets.token_urlsafe(32))

    @action(detail=True, methods=["post"], url_path="rotate-key")
    def rotate_key(self, request, company_id=None, pk=None):
        device = self.get_object()
        device.api_key = secrets.token_urlsafe(32)
        device.save(update_fields=["api_key"])
        return Response(RotateKeyResponseSerializer({"api_key": device.api_key}).data)


# --------- Face Enrollment (authenticated, manager/admin scope) ---------


class FaceEnrollmentViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated, IsCompanyMember, ActionRolePermission]

    def _get_employee(self, company_id, employee_id):
        emp = get_object_or_404(Employee, pk=employee_id)
        allowed_emp_ids = set(scope_queryset(Employee.objects.all(), self.request.user).values_list("id", flat=True))
        if emp.id not in allowed_emp_ids:
            return Response({"detail": "Employee outside your scope", "errors": {}}, status=403)
        return emp

    @action(detail=True, methods=["get"], url_path=r"employees/(?P<employee_id>\d+)/face")
    def status(self, request, company_id=None, pk=None, employee_id=None):
        emp = self._get_employee(company_id, employee_id)
        fe = getattr(emp, "face_enrollment", None)
        if not fe:
            return Response({"status": "none"})
        return Response(FaceEnrollmentStatusSerializer(fe).data)

    @action(detail=True, methods=["post"], url_path=r"employees/(?P<employee_id>\d+)/face/enrollment-link")
    def create_link(self, request, company_id=None, pk=None, employee_id=None):
        emp = self._get_employee(company_id, employee_id)
        ser = EnrollmentLinkCreateSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        token = secrets.token_urlsafe(32)
        expires = timezone.now() + timedelta(hours=ser.validated_data["expires_in_hours"])
        EnrollmentLink.objects.create(
            employee=emp,
            token=token,
            expires_at=expires,
            max_uses=ser.validated_data["max_uses"],
        )
        return Response({
            "url": f"{settings.PUBLIC_BASE_URL}/api/face/enroll/{token}",
            "token": token,
            "expires_at": expires,
        })

    @action(detail=True, methods=["delete"], url_path=r"employees/(?P<employee_id>\d+)/face")
    def revoke(self, request, company_id=None, pk=None, employee_id=None):
        emp = self._get_employee(company_id, employee_id)
        fe = getattr(emp, "face_enrollment", None)
        if fe:
            delete_faces(emp.company.id, fe.face_ids)
            fe.status = "revoked"
            fe.face_ids = []
            fe.save(update_fields=["status", "face_ids", "updated_at"])
        return Response(status=204)


# --------- Public Enrollment Submit (token) ---------


class EnrollmentSubmitView(generics.GenericAPIView):
    permission_classes = []
    serializer_class = EnrollmentSubmitSerializer
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request, token: str):
        link = get_object_or_404(EnrollmentLink, token=token)
        if not link.is_valid:
            return Response({"detail": "Link invalid or expired"}, status=403)
        ser = self.get_serializer(data=request.data)
        ser.is_valid(raise_exception=True)
        emp = link.employee
        ensure_collection(company_collection_id(emp.company.id))
        face_ids = []
        for img in ser.validated_data["images"]:
            bytes_ = img.read()
            put_enroll_to_s3(emp.company.id, emp.id, bytes_)
            face_ids.extend(index_faces(emp.company.id, emp.id, bytes_))
        fe, _ = FaceEnrollment.objects.get_or_create(
            employee=emp,
            defaults={
                "collection_id": company_collection_id(emp.company.id),
                "face_ids": face_ids,
                "status": "active",
            },
        )
        if fe and fe.pk:
            merged = list({*fe.face_ids, *face_ids})
            fe.face_ids = merged
            fe.status = "active"
            fe.save(update_fields=["face_ids", "status", "updated_at"])
        link.mark_used()
        return Response({"faces_indexed": len(face_ids)})


# --------- Punch Capture (device-auth only) ---------


class CapturePunchView(generics.GenericAPIView):
    authentication_classes = [DeviceKeyAuthentication]
    permission_classes = []
    serializer_class = PunchRequestSerializer
    parser_classes = [parsers.MultiPartParser, parsers.JSONParser, parsers.FormParser]

    def post(self, request):
        device = request.device
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

        s3_key, sha256 = ("", "")
        if image_bytes:
            s3_key, sha256 = put_capture_to_s3(company.id, device.id, image_bytes)

        company_local_dt = localize_to_company(company, data["timestamp"])
        roster_date, roster_entry = (None, None)
        matched_emp = None
        face_ok = False
        confidence = None
        requires_face = False

        if hinted_emp:
            roster_date, roster_entry = compute_roster_date(hinted_emp, company_local_dt)

        if image_bytes:
            threshold = float(settings.FACE_MATCH_DEFAULT_MIN_CONF)
            if roster_entry:
                threshold = get_face_threshold(roster_entry.shift, roster_date)
                requires_face = roster_entry.shift.requires_face
            res = search_face_by_image(company.id, image_bytes, threshold)
            matches = res.get("FaceMatches", []) or []
            if matches:
                top = max(matches, key=lambda m: m.get("Similarity", 0))
                sim = float(top.get("Similarity", 0))
                confidence = sim / 100.0 if sim > 1 else sim
                ext = top["Face"].get("ExternalImageId")
                try:
                    matched_emp = Employee.objects.get(pk=int(ext))
                except Exception:
                    matched_emp = hinted_emp
                face_ok = True

        employee = hinted_emp or matched_emp
        if employee:
            if roster_entry is None:
                roster_date, roster_entry = compute_roster_date(employee, company_local_dt)
            if roster_entry:
                requires_face = roster_entry.shift.requires_face

        out_scope = False
        if employee:
            out_scope = not within_device_scope(device, employee)
        geo_ok = geofence_ok(device, data.get("lat"), data.get("lon"))

        accepted = True
        reason = None
        if requires_face:
            fe = getattr(employee, "face_enrollment", None) if employee else None
            if not (fe and fe.status == "active" and face_ok):
                accepted = False
                reason = "face_required_no_match"

        if not geo_ok and getattr(settings, "CAPTURE_BLOCK_GEOFENCE", False):
            accepted = False
            reason = reason or "geofence"

        if out_scope and getattr(settings, "CAPTURE_BLOCK_OUT_OF_SCOPE", False):
            accepted = False
            reason = reason or "outside_scope"

        try:
            with transaction.atomic():
                ev = PunchEvent.objects.create(
                    device=device,
                    company=company,
                    employee=employee,
                    matched_employee=matched_emp,
                    action=data["action"],
                    device_ts=data["timestamp"],
                    s3_key=s3_key,
                    image_bytes_sha256=sha256,
                    face_matched=bool(face_ok),
                    face_confidence=confidence,
                    roster_date=roster_date,
                    requires_face=bool(requires_face),
                    out_of_scope=out_scope,
                    geofence_ok=geo_ok,
                    external_id=ext_id,
                    notes=reason or "",
                )
        except IntegrityError:
            ev = PunchEvent.objects.filter(device=device, external_id=ext_id).first()

        if (
            (reason == "face_required_no_match")
            or (out_scope and not settings.CAPTURE_BLOCK_OUT_OF_SCOPE)
            or (not geo_ok and not settings.CAPTURE_BLOCK_GEOFENCE)
        ):
            PunchException.objects.get_or_create(
                event=ev,
                defaults={"kind": reason or ("outside_scope" if out_scope else "geofence"), "details": {}},
            )

        payload = {
            "accepted": bool(accepted),
            "roster_date": ev.roster_date.isoformat() if ev.roster_date else None,
            "matched_employee": ev.matched_employee_id,
            "face_confidence": float(ev.face_confidence) if ev.face_confidence is not None else None,
            "requires_face": ev.requires_face,
            "out_of_scope": ev.out_of_scope,
            "geofence_ok": ev.geofence_ok,
            "notes": ev.notes,
            "event_id": ev.id,
        }
        status_code = 200 if accepted else 403
        return Response(payload, status=status_code)


# --------- Punch event listing (RBAC & scope) ---------


class PunchEventViewSet(CompanyScopedQuerysetMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated, IsCompanyMember, ActionRolePermission]
    serializer_class = PunchEventSerializer
    filter_backends = [DjangoFilterBackend, drf_filters.OrderingFilter, drf_filters.SearchFilter]
    filterset_class = PunchEventFilter
    ordering = ["-server_ts"]
    search_fields = ["employee__username", "device__name", "external_id"]

    def get_queryset(self):
        qs = PunchEvent.objects.select_related("device", "company", "employee", "matched_employee")
        company = self.get_company()
        qs = qs.filter(company=company)
        allowed_emp_ids = scope_queryset(Employee.objects.all(), self.request.user).values_list("id", flat=True)
        allowed_dev_ids = scope_queryset(AttendanceDevice.objects.all(), self.request.user).values_list("id", flat=True)
        return qs.filter(
            (Q(employee_id__in=allowed_emp_ids) | Q(matched_employee_id__in=allowed_emp_ids))
            | Q(device_id__in=allowed_dev_ids)
        )
