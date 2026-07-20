from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class StaffMember(models.Model):
    name = models.CharField("氏名", max_length=100)
    is_active = models.BooleanField("有効", default=True)
    is_deleted = models.BooleanField("削除済み", default=False)
    display_order = models.PositiveIntegerField("表示順", default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "id"]
        verbose_name = "担当者"
        verbose_name_plural = "担当者"

    def __str__(self):
        return self.name


class RosterMonth(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "準備中"
        GENERATED = "generated", "生成済み"
        CONFIRMED = "confirmed", "確定"

    year = models.PositiveIntegerField(
        "年", validators=[MinValueValidator(2000), MaxValueValidator(2100)]
    )
    month = models.PositiveSmallIntegerField(
        "月", validators=[MinValueValidator(1), MaxValueValidator(12)]
    )
    status = models.CharField(
        "状態", max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    generation_version = models.PositiveIntegerField("生成バージョン", default=0)
    confirmed_at = models.DateTimeField("確定日時", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["year", "month"], name="unique_roster_month")
        ]
        ordering = ["-year", "-month"]
        verbose_name = "月別当直表"
        verbose_name_plural = "月別当直表"

    def __str__(self):
        return f"{self.year}年{self.month}月"


class CalendarDay(models.Model):
    class HolidaySource(models.TextChoices):
        WEEKEND = "weekend", "土日"
        NATIONAL = "national", "祝日"
        CUSTOM = "custom", "独自休日"
        OVERRIDE = "override", "手動設定"
        WEEKDAY = "weekday", "平日"

    roster_month = models.ForeignKey(
        RosterMonth, on_delete=models.CASCADE, related_name="days"
    )
    duty_date = models.DateField("日付")
    is_holiday = models.BooleanField("休日・祝日", default=False)
    holiday_name = models.CharField("休日名", max_length=100, blank=True)
    holiday_source = models.CharField(
        "休日区分",
        max_length=20,
        choices=HolidaySource.choices,
        default=HolidaySource.WEEKDAY,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["roster_month", "duty_date"], name="unique_calendar_day"
            )
        ]
        ordering = ["duty_date"]
        verbose_name = "カレンダー日"
        verbose_name_plural = "カレンダー日"

    def __str__(self):
        return self.duty_date.strftime("%Y-%m-%d")


class DutyType(models.TextChoices):
    DAY = "day", "日直"
    NIGHT = "night", "夜間当直"


class MonthlyStaffSetting(models.Model):
    roster_month = models.ForeignKey(
        RosterMonth, on_delete=models.CASCADE, related_name="staff_settings"
    )
    staff_member = models.ForeignKey(
        StaffMember, on_delete=models.CASCADE, related_name="monthly_settings"
    )
    target_count = models.PositiveSmallIntegerField("月間担当回数", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["roster_month", "staff_member"],
                name="unique_monthly_staff_setting",
            )
        ]
        verbose_name = "月間担当回数設定"
        verbose_name_plural = "月間担当回数設定"


class UnavailableSlot(models.Model):
    roster_month = models.ForeignKey(
        RosterMonth, on_delete=models.CASCADE, related_name="unavailable_slots"
    )
    calendar_day = models.ForeignKey(
        CalendarDay, on_delete=models.CASCADE, related_name="unavailable_slots"
    )
    staff_member = models.ForeignKey(
        StaffMember, on_delete=models.PROTECT, related_name="unavailable_slots"
    )
    duty_type = models.CharField("当直種別", max_length=20, choices=DutyType.choices)
    note = models.CharField("備考", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["calendar_day", "staff_member", "duty_type"],
                name="unique_unavailable_slot",
            )
        ]
        verbose_name = "希望しない当直枠"
        verbose_name_plural = "希望しない当直枠"


class DutyAssignment(models.Model):
    roster_month = models.ForeignKey(
        RosterMonth, on_delete=models.CASCADE, related_name="assignments"
    )
    calendar_day = models.ForeignKey(
        CalendarDay, on_delete=models.CASCADE, related_name="assignments"
    )
    staff_member = models.ForeignKey(
        StaffMember, on_delete=models.PROTECT, related_name="assignments"
    )
    duty_type = models.CharField("当直種別", max_length=20, choices=DutyType.choices)
    is_manual = models.BooleanField("手動変更", default=False)
    generation_version = models.PositiveIntegerField("生成バージョン", default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["calendar_day", "duty_type"], name="unique_duty_assignment"
            )
        ]
        ordering = ["calendar_day__duty_date", "duty_type"]
        verbose_name = "当直割り当て"
        verbose_name_plural = "当直割り当て"
