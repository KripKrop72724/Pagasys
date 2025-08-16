from django.urls import path, include
from rest_framework import routers
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .views import (
    CompanyViewSet,
    BranchViewSet,
    DesignationViewSet,
    TradeLicenseViewSet,
    DepartmentViewSet,
    ProjectViewSet,
    EmployeeViewSet,
)
from .views_attendance import (
    DeviceViewSet,
    AttEventViewSet,
    WorkCalendarViewSet,
    HolidayViewSet,
    ShiftTemplateViewSet,
    ShiftRuleViewSet,
    RosterEntryViewSet,
    AttPairViewSet,
    AttDayViewSet,
    LeaveTypeViewSet,
    LeaveRequestViewSet,
    LeaveDayViewSet,
    AttEventIngestView,
)

router = routers.DefaultRouter()
router.register(r'companies', CompanyViewSet)
router.register(r'branches', BranchViewSet)
router.register(r'designations', DesignationViewSet)
router.register(r'licenses', TradeLicenseViewSet)
router.register(r'departments', DepartmentViewSet)
router.register(r'projects', ProjectViewSet)
router.register(r'employees', EmployeeViewSet)

attendance_router = routers.DefaultRouter()
attendance_router.register(r'devices', DeviceViewSet)
attendance_router.register(r'events', AttEventViewSet)
attendance_router.register(r'calendars', WorkCalendarViewSet)
attendance_router.register(r'holidays', HolidayViewSet)
attendance_router.register(r'shift-templates', ShiftTemplateViewSet)
attendance_router.register(r'shift-rules', ShiftRuleViewSet)
attendance_router.register(r'roster-entries', RosterEntryViewSet)
attendance_router.register(r'pairs', AttPairViewSet)
attendance_router.register(r'days', AttDayViewSet)
attendance_router.register(r'leave-types', LeaveTypeViewSet)
attendance_router.register(r'leave-requests', LeaveRequestViewSet)
attendance_router.register(r'leave-days', LeaveDayViewSet)

urlpatterns = [
    *router.urls,
    path('attendance/events/ingest/', AttEventIngestView.as_view(), name='att-event-ingest'),
    path('attendance/', include(attendance_router.urls)),
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]
