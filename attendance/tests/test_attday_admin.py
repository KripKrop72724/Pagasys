from attendance.admin import AttDayAdmin


def test_attday_admin_includes_date_filter():
    assert "date" in AttDayAdmin.list_filter
    assert AttDayAdmin.date_hierarchy == "date"
