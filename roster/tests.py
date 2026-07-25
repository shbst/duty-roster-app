from datetime import date

from django.test import TestCase
from django.urls import reverse

from .models import (
    DutyAssignment,
    DutySlotSetting,
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

    def test_skips_disabled_duty_slot(self):
        day = self.month.days.filter(is_holiday=False).first()
        DutySlotSetting.objects.create(
            roster_month=self.month,
            calendar_day=day,
            duty_type=DutyType.NIGHT,
            is_enabled=False,
        )

        generate_roster(self.month)

        self.assertFalse(
            self.month.assignments.filter(
                calendar_day=day,
                duty_type=DutyType.NIGHT,
            ).exists()
        )


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

    def test_roster_can_be_deleted_with_all_related_data(self):
        member = StaffMember.objects.create(name="削除確認")
        month = RosterMonth.objects.create(year=2026, month=12)
        ensure_calendar(month)
        day = month.days.first()
        DutyAssignment.objects.create(
            roster_month=month,
            calendar_day=day,
            staff_member=member,
            duty_type=DutyType.NIGHT,
        )
        UnavailableSlot.objects.create(
            roster_month=month,
            calendar_day=day,
            staff_member=member,
            duty_type=DutyType.DAY,
        )
        MonthlyStaffSetting.objects.create(
            roster_month=month,
            staff_member=member,
            target_count=1,
        )
        DutySlotSetting.objects.create(
            roster_month=month,
            calendar_day=day,
            duty_type=DutyType.NIGHT,
            is_enabled=True,
        )

        response = self.client.post(reverse("roster_delete", args=[month.pk]))

        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(RosterMonth.objects.filter(pk=month.pk).exists())
        self.assertFalse(DutyAssignment.objects.filter(roster_month_id=month.pk).exists())
        self.assertFalse(UnavailableSlot.objects.filter(roster_month_id=month.pk).exists())
        self.assertFalse(
            MonthlyStaffSetting.objects.filter(roster_month_id=month.pk).exists()
        )
        self.assertFalse(
            DutySlotSetting.objects.filter(roster_month_id=month.pk).exists()
        )

    def test_roster_delete_rejects_get(self):
        month = RosterMonth.objects.create(year=2027, month=1)

        response = self.client.get(reverse("roster_delete", args=[month.pk]))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(RosterMonth.objects.filter(pk=month.pk).exists())

    def test_delete_buttons_are_shown_on_dashboard_and_roster_detail(self):
        month = RosterMonth.objects.create(year=2027, month=2)

        dashboard_response = self.client.get(reverse("dashboard"))
        detail_response = self.client.get(reverse("roster_detail", args=[month.pk]))

        delete_url = reverse("roster_delete", args=[month.pk])
        self.assertContains(dashboard_response, delete_url)
        self.assertContains(detail_response, delete_url)

    def test_availability_is_monday_first_and_has_target_input(self):
        member = StaffMember.objects.create(name="佐藤")
        month = RosterMonth.objects.create(year=2026, month=8)
        ensure_calendar(month)
        response = self.client.get(reverse("availability", args=[month.pk]))
        self.assertContains(response, 'name="target_')
        self.assertContains(response, '<div class="weekday-header">', html=False)
        self.assertContains(response, "<span>月</span>", html=False)


    def test_assignment_can_be_changed_to_unassigned(self):
        member = StaffMember.objects.create(name="割当担当者")
        month = RosterMonth.objects.create(
            year=2026,
            month=9,
            status=RosterMonth.Status.CONFIRMED,
        )
        ensure_calendar(month)
        day = month.days.filter(is_holiday=False).first()
        DutyAssignment.objects.create(
            roster_month=month,
            calendar_day=day,
            staff_member=member,
            duty_type=DutyType.NIGHT,
        )

        response = self.client.post(
            reverse(
                "assignment_update",
                args=[month.pk, day.pk, DutyType.NIGHT],
            ),
            {"staff_member": ""},
        )

        self.assertRedirects(response, reverse("roster_detail", args=[month.pk]))
        self.assertFalse(
            DutyAssignment.objects.filter(
                calendar_day=day,
                duty_type=DutyType.NIGHT,
            ).exists()
        )
        month.refresh_from_db()
        self.assertEqual(month.status, RosterMonth.Status.GENERATED)
        self.assertIsNone(month.confirmed_at)

    def test_duty_day_settings_control_slots_and_hyphen_display(self):
        member = StaffMember.objects.create(name="担当者")
        month = RosterMonth.objects.create(year=2026, month=10)
        ensure_calendar(month)
        weekday = month.days.filter(is_holiday=False).first()

        response = self.client.post(
            reverse("duty_days", args=[month.pk]),
            {f"slot_{weekday.pk}_{DutyType.DAY}": "on"},
        )

        self.assertRedirects(response, reverse("duty_days", args=[month.pk]))
        self.assertTrue(
            month.duty_slot_settings.get(
                calendar_day=weekday,
                duty_type=DutyType.DAY,
            ).is_enabled
        )
        self.assertFalse(
            month.duty_slot_settings.get(
                calendar_day=weekday,
                duty_type=DutyType.NIGHT,
            ).is_enabled
        )

        generate_roster(month)
        self.assertTrue(
            month.assignments.filter(
                calendar_day=weekday,
                duty_type=DutyType.DAY,
                staff_member=member,
            ).exists()
        )
        response = self.client.get(reverse("roster_detail", args=[month.pk]))
        self.assertContains(response, '<span class="muted">-</span>', html=True)

    def test_duty_day_settings_uses_calendar_layout(self):
        month = RosterMonth.objects.create(year=2026, month=7)
        ensure_calendar(month)

        response = self.client.get(reverse("duty_days", args=[month.pk]))

        self.assertContains(response, 'class="duty-weekday-header"', html=False)
        self.assertContains(response, 'class="duty-day-card blank"', count=2)
        self.assertContains(response, ">日直</span>", html=False)
        self.assertContains(response, ">夜間当直</span>", html=False)
        self.assertContains(response, "css/app.css%3F", count=0)
        self.assertContains(response, "css/app.css?v=20260725-2")

    def test_disabled_duty_slot_rejects_manual_assignment(self):
        member = StaffMember.objects.create(name="担当者")
        month = RosterMonth.objects.create(year=2026, month=11)
        ensure_calendar(month)
        day = month.days.first()
        DutySlotSetting.objects.create(
            roster_month=month,
            calendar_day=day,
            duty_type=DutyType.NIGHT,
            is_enabled=False,
        )

        response = self.client.post(
            reverse(
                "assignment_update",
                args=[month.pk, day.pk, DutyType.NIGHT],
            ),
            {"staff_member": member.pk},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(month.assignments.exists())


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
