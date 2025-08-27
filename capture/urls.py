from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    AttendanceDeviceViewSet,
    FaceEnrollmentViewSet,
    EnrollmentSubmitView,
    CapturePunchView,
    PunchEventViewSet,
)

router = DefaultRouter()
router.register(r"companies/(?P<company_id>\d+)/devices", AttendanceDeviceViewSet, basename="devices")
router.register(r"companies/(?P<company_id>\d+)/manage", FaceEnrollmentViewSet, basename="face-manage")
router.register(r"companies/(?P<company_id>\d+)/punch-events", PunchEventViewSet, basename="punch-events")

urlpatterns = [
    path("", include(router.urls)),
    path("face/enroll/<str:token>", EnrollmentSubmitView.as_view(), name="face-enroll-submit"),
    path("capture/punch", CapturePunchView.as_view(), name="capture-punch"),
]
