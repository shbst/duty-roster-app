from collections import defaultdict
from datetime import date

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import MonthForm, StaffMemberForm
from .models import (
    DutyAssignment,
    DutySlotSetting,
    DutyType,
    MonthlyStaffSetting,
    RosterMonth,
    StaffMember,
    UnavailableSlot,
)
from .pdf_service import build_roster_pdf
from .services import GenerationError, ensure_calendar, generate_roster, slots_for


def dashboard(request):
    today = date.today()
    form = MonthForm(
        request.POST or None, initial={"year": today.year, "month": today.month}
    )
    if request.method == "POST" and form.is_valid():
        roster_month, _ = RosterMonth.objects.get_or_create(**form.cleaned_data)
        ensure_calendar(roster_month)
        return redirect("roster_detail", pk=roster_month.pk)

    cumulative = []
    for member in StaffMember.objects.filter(is_deleted=False):
        assignments = member.assignments.all()
        cumulative.append(
            {
                "member": member,
                "total": assignments.count(),
                "day": assignments.filter(duty_type=DutyType.DAY).count(),
                "night": assignments.filter(duty_type=DutyType.NIGHT).count(),
                "holiday": assignments.filter(calendar_day__is_holiday=True).count(),
            }
        )
    return render(
        request,
        "roster/dashboard.html",
        {
            "form": form,
            "roster_months": RosterMonth.objects.all()[:18],
            "cumulative": cumulative,
        },
    )


def staff_list(request):
    form = StaffMemberForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "担当者を追加しました。")
        return redirect("staff_list")
    return render(
        request,
        "roster/staff_list.html",
        {"form": form, "members": StaffMember.objects.filter(is_deleted=False)},
    )


@require_POST
def staff_toggle(request, pk):
    member = get_object_or_404(StaffMember, pk=pk, is_deleted=False)
    member.is_active = not member.is_active
    member.save(update_fields=["is_active", "updated_at"])
    messages.success(request, f"{member.name}の状態を変更しました。")
    return redirect("staff_list")


@require_POST
def staff_delete(request, pk):
    member = get_object_or_404(StaffMember, pk=pk, is_deleted=False)
    member.is_active = False
    member.is_deleted = True
    member.save(update_fields=["is_active", "is_deleted", "updated_at"])
    messages.success(request, f"{member.name}を削除しました。過去の実績は保持されます。")
    return redirect("staff_list")


def _get_month(pk):
    roster_month = get_object_or_404(RosterMonth, pk=pk)
    ensure_calendar(roster_month)
    return roster_month


@require_POST
def roster_delete(request, pk):
    roster_month = get_object_or_404(RosterMonth, pk=pk)
    month_label = str(roster_month)
    roster_month.delete()
    messages.success(request, f"{month_label}の当直表を削除しました。")
    return redirect("dashboard")


def roster_detail(request, pk):
    roster_month = _get_month(pk)
    enabled_slots = {
        (day.id, duty_type) for day, duty_type in slots_for(roster_month)
    }
    assignments = {
        (assignment.calendar_day_id, assignment.duty_type): assignment
        for assignment in roster_month.assignments.select_related("staff_member")
    }
    rows = [
        {
            "day": day,
            "day_assignment": assignments.get((day.id, DutyType.DAY)),
            "night_assignment": assignments.get((day.id, DutyType.NIGHT)),
            "day_enabled": (day.id, DutyType.DAY) in enabled_slots,
            "night_enabled": (day.id, DutyType.NIGHT) in enabled_slots,
        }
        for day in roster_month.days.all()
    ]
    counts = defaultdict(lambda: {"day": 0, "night": 0, "holiday": 0, "total": 0})
    for assignment in roster_month.assignments.select_related(
        "staff_member", "calendar_day"
    ):
        item = counts[assignment.staff_member]
        item[assignment.duty_type] += 1
        item["total"] += 1
        if assignment.calendar_day.is_holiday:
            item["holiday"] += 1
    members = StaffMember.objects.filter(is_active=True, is_deleted=False)
    summary = [{"member": member, **counts[member]} for member in members]
    return render(
        request,
        "roster/roster_detail.html",
        {
            "roster_month": roster_month,
            "rows": rows,
            "summary": summary,
            "members": members,
        },
    )


def availability(request, pk):
    roster_month = _get_month(pk)
    members = list(
        StaffMember.objects.filter(is_active=True, is_deleted=False)
    )
    days = list(roster_month.days.all())
    if request.method == "POST":
        with transaction.atomic():
            roster_month.unavailable_slots.all().delete()
            roster_month.staff_settings.all().delete()
            unavailable_records = []
            setting_records = []
            for member in members:
                raw_target = request.POST.get(f"target_{member.id}", "").strip()
                if raw_target:
                    try:
                        target = int(raw_target)
                        if target < 0:
                            raise ValueError
                    except ValueError:
                        messages.error(
                            request,
                            f"{member.name}の担当回数は0以上の整数で入力してください。",
                        )
                        return redirect("availability", pk=pk)
                    setting_records.append(
                        MonthlyStaffSetting(
                            roster_month=roster_month,
                            staff_member=member,
                            target_count=target,
                        )
                    )
                for day in days:
                    duty_types = [DutyType.NIGHT]
                    if day.is_holiday:
                        duty_types.insert(0, DutyType.DAY)
                    for duty_type in duty_types:
                        if request.POST.get(
                            f"slot_{member.id}_{day.id}_{duty_type}"
                        ):
                            unavailable_records.append(
                                UnavailableSlot(
                                    roster_month=roster_month,
                                    calendar_day=day,
                                    staff_member=member,
                                    duty_type=duty_type,
                                )
                            )
            UnavailableSlot.objects.bulk_create(unavailable_records)
            MonthlyStaffSetting.objects.bulk_create(setting_records)
        messages.success(request, "希望しない日と月間担当回数を保存しました。")
        return redirect("availability", pk=pk)

    blocked = set(
        roster_month.unavailable_slots.values_list(
            "staff_member_id", "calendar_day_id", "duty_type"
        )
    )
    settings = {
        setting.staff_member_id: setting.target_count
        for setting in roster_month.staff_settings.all()
    }
    matrix = []
    for member in members:
        cells = []
        for day in days:
            cells.append(
                {
                    "day": day,
                    "day_key": f"slot_{member.id}_{day.id}_{DutyType.DAY}",
                    "night_key": f"slot_{member.id}_{day.id}_{DutyType.NIGHT}",
                    "day_blocked": (member.id, day.id, DutyType.DAY) in blocked,
                    "night_blocked": (member.id, day.id, DutyType.NIGHT) in blocked,
                }
            )
        matrix.append(
            {
                "member": member,
                "cells": cells,
                "leading_blanks": range(days[0].duty_date.weekday()) if days else [],
                "target_count": settings.get(member.id),
            }
        )
    return render(
        request,
        "roster/availability.html",
        {"roster_month": roster_month, "days": days, "matrix": matrix},
    )


def duty_days(request, pk):
    roster_month = _get_month(pk)
    days = list(roster_month.days.all())
    if request.method == "POST":
        settings = []
        enabled_slots = set()
        for day in days:
            for duty_type in DutyType.values:
                is_enabled = bool(
                    request.POST.get(f"slot_{day.id}_{duty_type}")
                )
                settings.append(
                    DutySlotSetting(
                        roster_month=roster_month,
                        calendar_day=day,
                        duty_type=duty_type,
                        is_enabled=is_enabled,
                    )
                )
                if is_enabled:
                    enabled_slots.add((day.id, duty_type))
        with transaction.atomic():
            roster_month.duty_slot_settings.all().delete()
            DutySlotSetting.objects.bulk_create(settings)
            for day in days:
                for duty_type in DutyType.values:
                    if (day.id, duty_type) not in enabled_slots:
                        DutyAssignment.objects.filter(
                            roster_month=roster_month,
                            calendar_day=day,
                            duty_type=duty_type,
                        ).delete()
            roster_month.status = RosterMonth.Status.DRAFT
            roster_month.confirmed_at = None
            roster_month.save(
                update_fields=["status", "confirmed_at", "updated_at"]
            )
        messages.success(request, "担当日設定を保存しました。")
        return redirect("duty_days", pk=pk)

    enabled_slots = {
        (day.id, duty_type) for day, duty_type in slots_for(roster_month)
    }
    rows = [
        {
            "day": day,
            "day_enabled": (day.id, DutyType.DAY) in enabled_slots,
            "night_enabled": (day.id, DutyType.NIGHT) in enabled_slots,
        }
        for day in days
    ]
    return render(
        request,
        "roster/duty_days.html",
        {
            "roster_month": roster_month,
            "rows": rows,
            "leading_blanks": range(days[0].duty_date.weekday()) if days else [],
        },
    )


@require_POST
def roster_generate(request, pk):
    roster_month = _get_month(pk)
    try:
        generate_roster(roster_month)
        messages.success(request, "当直表を生成しました。")
    except GenerationError as error:
        messages.error(request, str(error))
    return redirect("roster_detail", pk=pk)


@require_POST
def assignment_update(request, pk, day_id, duty_type):
    roster_month = _get_month(pk)
    day = get_object_or_404(roster_month.days, pk=day_id)
    if duty_type not in DutyType.values:
        return HttpResponseBadRequest("不正な当直種別です。")
    enabled_slots = {
        (slot_day.id, slot_type)
        for slot_day, slot_type in slots_for(roster_month)
    }
    if (day.id, duty_type) not in enabled_slots:
        return HttpResponseBadRequest("割り当てなしの枠には担当者を設定できません。")
    member_id = request.POST.get("staff_member")
    if not member_id:
        DutyAssignment.objects.filter(
            calendar_day=day,
            duty_type=duty_type,
        ).delete()
        roster_month.status = RosterMonth.Status.GENERATED
        roster_month.confirmed_at = None
        roster_month.save(update_fields=["status", "confirmed_at", "updated_at"])
        messages.success(request, "未割り当てに変更しました。")
        return redirect("roster_detail", pk=pk)
    member = get_object_or_404(
        StaffMember,
        pk=member_id,
        is_active=True,
        is_deleted=False,
    )
    other_type = DutyType.NIGHT if duty_type == DutyType.DAY else DutyType.DAY
    if DutyAssignment.objects.filter(
        calendar_day=day, duty_type=other_type, staff_member=member
    ).exists():
        messages.error(
            request, "同じ人を同じ日の日直と夜間当直に設定できません。"
        )
        return redirect("roster_detail", pk=pk)
    DutyAssignment.objects.update_or_create(
        calendar_day=day,
        duty_type=duty_type,
        defaults={
            "roster_month": roster_month,
            "staff_member": member,
            "is_manual": True,
            "generation_version": max(roster_month.generation_version, 1),
        },
    )
    roster_month.status = RosterMonth.Status.GENERATED
    roster_month.confirmed_at = None
    roster_month.save(update_fields=["status", "confirmed_at", "updated_at"])
    messages.success(request, "担当者を変更しました。公平性の集計を確認してください。")
    return redirect("roster_detail", pk=pk)


@require_POST
def roster_confirm(request, pk):
    roster_month = _get_month(pk)
    expected = len(slots_for(roster_month))
    if roster_month.assignments.count() != expected:
        messages.error(request, "未割り当ての枠があるため確定できません。")
        return redirect("roster_detail", pk=pk)
    members = list(
        StaffMember.objects.filter(is_active=True, is_deleted=False)
    )
    holiday_counts = defaultdict(int)
    for assignment in roster_month.assignments.filter(
        calendar_day__is_holiday=True
    ):
        holiday_counts[assignment.staff_member_id] += 1
    values = [holiday_counts[member.id] for member in members]
    if values and max(values) - min(values) > 1:
        messages.error(
            request, "休日担当回数の差が1回を超えるため確定できません。"
        )
        return redirect("roster_detail", pk=pk)
    roster_month.status = RosterMonth.Status.CONFIRMED
    roster_month.confirmed_at = timezone.now()
    roster_month.save(update_fields=["status", "confirmed_at", "updated_at"])
    messages.success(request, "当直表を確定しました。")
    return redirect("roster_detail", pk=pk)


def roster_pdf(request, pk):
    roster_month = _get_month(pk)
    if roster_month.status != RosterMonth.Status.CONFIRMED:
        return HttpResponseForbidden("確定済みの当直表だけPDF出力できます。")
    response = HttpResponse(
        build_roster_pdf(roster_month), content_type="application/pdf"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="duty-roster-'
        f'{roster_month.year}-{roster_month.month:02d}.pdf"'
    )
    return response
