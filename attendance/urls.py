from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    AttDayViewSet,
    AttPairViewSet,
    AttAdjustmentViewSet,
    AttendanceCalendarViewSet,
)

router = DefaultRouter()
router.register(r"companies/(?P<company_id>\d+)/att-days", AttDayViewSet, basename="att-day")
router.register(r"companies/(?P<company_id>\d+)/att-pairs", AttPairViewSet, basename="att-pair")
router.register(
    r"companies/(?P<company_id>\d+)/att-adjustments",
    AttAdjustmentViewSet,
    basename="att-adjustment",
)
router.register(
    r"companies/(?P<company_id>\d+)/attendance-calendar",
    AttendanceCalendarViewSet,
    basename="attendance-calendar",
)

urlpatterns = [path("", include(router.urls))]
