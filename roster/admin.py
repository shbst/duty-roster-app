from django.contrib import admin
from .models import (
    CalendarDay,
    DutyAssignment,
    MonthlyStaffSetting,
    RosterMonth,
    StaffMember,
    UnavailableSlot,
)


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "is_deleted", "display_order")
    list_editable = ("is_active", "display_order")
    search_fields = ("name",)


@admin.register(RosterMonth)
class RosterMonthAdmin(admin.ModelAdmin):
    list_display = ("year", "month", "status", "generation_version", "confirmed_at")
    list_filter = ("status", "year")


admin.site.register(CalendarDay)
admin.site.register(UnavailableSlot)
admin.site.register(DutyAssignment)
admin.site.register(MonthlyStaffSetting)
