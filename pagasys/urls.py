from django.urls import path
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
    WorkCalendarViewSet,
    HolidayViewSet,
    ShiftTemplateViewSet,
    ShiftRuleViewSet,
    RosterEntryViewSet,
    LeaveTypeViewSet,
)

router = routers.DefaultRouter()
router.register(r'companies', CompanyViewSet)
router.register(r'branches', BranchViewSet)
router.register(r'designations', DesignationViewSet)
router.register(r'licenses', TradeLicenseViewSet)
router.register(r'departments', DepartmentViewSet)
router.register(r'projects', ProjectViewSet)
router.register(r'employees', EmployeeViewSet)
router.register(r'calendars', WorkCalendarViewSet)
router.register(r'holidays', HolidayViewSet)
router.register(r'shift-templates', ShiftTemplateViewSet)
router.register(r'shift-rules', ShiftRuleViewSet)
router.register(r'roster-entries', RosterEntryViewSet)
router.register(r'leave-types', LeaveTypeViewSet)

urlpatterns = [
    *router.urls,
    path('token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]
