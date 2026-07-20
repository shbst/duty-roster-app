from datetime import date

from django.test import TestCase
from django.urls import reverse

from .models import (
    DutyType,
    MonthlyStaffSetting,
    RosterMonth,
    StaffMember,
    UnavailableSlot,
)
from .services import GenerationError, ensure_calendar, generate_roster


class CalendarTests(TestCase):
    def test_calendar_marks_weekends_and_holidays(self):
        month = RosterMonth.objects.create(year=2026, month=1)
        ensure_calendar(month)
        self.assertEqual(month.days.count(), 31)
        self.assertTrue(month.days.get(duty_date=date(2026, 1, 1)).is_holiday)
        self.assertFalse(month.days.get(duty_date=date(2026, 1, 5)).is_holiday)


class GenerationTests(TestCase):
    def setUp(self):
        self.month = RosterMonth.objects.create(year=2026, month=2)
        ensure_calendar(self.month)
        self.members = [
            StaffMember.objects.create(name=f"担当者{i}", display_order=i)
            for i in range(1, 11)
        ]

    def test_generates_every_slot_and_balances_holidays(self):
        generate_roster(self.month)
        expected = sum(2 if day.is_holiday else 1 for day in self.month.days.all())
        self.assertEqual(self.month.assignments.count(), expected)
        counts = []
        for member in self.members:
            counts.append(
                self.month.assignments.filter(
                    staff_member=member, calendar_day__is_holiday=True
                ).count()
            )
        self.assertLessEqual(max(counts) - min(counts), 1)

    def test_respects_unavailable_slot(self):
        day = self.month.days.filter(is_holiday=False).first()
        UnavailableSlot.objects.create(
            roster_month=self.month,
            calendar_day=day,
            staff_member=self.members[0],
            duty_type=DutyType.NIGHT,
        )
        generate_roster(self.month)
        self.assertFalse(
            self.month.assignments.filter(
                calendar_day=day,
                staff_member=self.members[0],
                duty_type=DutyType.NIGHT,
            ).exists()
        )

    def test_respects_monthly_target_count(self):
        MonthlyStaffSetting.objects.create(
            roster_month=self.month,
            staff_member=self.members[0],
            target_count=2,
        )
        generate_roster(self.month)
        self.assertEqual(
            self.month.assignments.filter(staff_member=self.members[0]).count(), 2
        )

    def test_rejects_invalid_total_target_count(self):
        for member in self.members:
            MonthlyStaffSetting.objects.create(
                roster_month=self.month,
                staff_member=member,
                target_count=1,
            )
        with self.assertRaises(GenerationError):
            generate_roster(self.month)


class ViewTests(TestCase):
    def test_dashboard_opens_month(self):
        response = self.client.post(
            reverse("dashboard"), {"year": 2026, "month": 7}
        )
        month = RosterMonth.objects.get(year=2026, month=7)
        self.assertRedirects(response, reverse("roster_detail", args=[month.pk]))

    def test_staff_can_be_added(self):
        response = self.client.post(
            reverse("staff_list"),
            {"name": "山田", "display_order": 1},
        )
        self.assertRedirects(response, reverse("staff_list"))
        self.assertTrue(StaffMember.objects.filter(name="山田").exists())

    def test_staff_is_soft_deleted(self):
        member = StaffMember.objects.create(name="削除対象")
        response = self.client.post(reverse("staff_delete", args=[member.pk]))
        self.assertRedirects(response, reverse("staff_list"))
        member.refresh_from_db()
        self.assertTrue(member.is_deleted)
        self.assertFalse(member.is_active)

    def test_availability_is_monday_first_and_has_target_input(self):
        member = StaffMember.objects.create(name="佐藤")
        month = RosterMonth.objects.create(year=2026, month=8)
        ensure_calendar(month)
        response = self.client.get(reverse("availability", args=[month.pk]))
        self.assertContains(response, 'name="target_')
        self.assertContains(response, '<div class="weekday-header">', html=False)
        self.assertContains(response, "<span>月</span>", html=False)


class PdfTests(TestCase):
    def setUp(self):
        self.month = RosterMonth.objects.create(year=2026, month=3)
        ensure_calendar(self.month)
        for index in range(1, 11):
            StaffMember.objects.create(name=f"担当者{index}", display_order=index)
        generate_roster(self.month)

    def test_pdf_requires_confirmation(self):
        response = self.client.get(reverse("roster_pdf", args=[self.month.pk]))
        self.assertEqual(response.status_code, 403)

    def test_confirmed_roster_downloads_as_pdf(self):
        self.month.status = RosterMonth.Status.CONFIRMED
        self.month.save(update_fields=["status"])
        response = self.client.get(reverse("roster_pdf", args=[self.month.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
