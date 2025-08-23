from rest_framework import routers
from .views import (
    WorkCalendarViewSet,
    HolidayViewSet,
    ShiftTemplateViewSet,
    ShiftRuleViewSet,
    RosterViewSet,
    LeaveTypeViewSet,
)

router = routers.DefaultRouter()
router.register(r'companies/(?P<company_id>\d+)/work-calendars', WorkCalendarViewSet, basename='work-calendar')
router.register(r'companies/(?P<company_id>\d+)/holidays', HolidayViewSet, basename='holiday')
router.register(r'companies/(?P<company_id>\d+)/shift-templates', ShiftTemplateViewSet, basename='shift-template')
router.register(r'companies/(?P<company_id>\d+)/shift-rules', ShiftRuleViewSet, basename='shift-rule')
router.register(r'companies/(?P<company_id>\d+)/roster', RosterViewSet, basename='roster')
router.register(r'companies/(?P<company_id>\d+)/leave-types', LeaveTypeViewSet, basename='leave-type')

urlpatterns = router.urls
