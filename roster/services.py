import calendar
from collections import defaultdict
from datetime import date, timedelta

import jpholiday
from django.db import transaction
from ortools.sat.python import cp_model

from .models import CalendarDay, DutyAssignment, DutyType, StaffMember


def ensure_calendar(roster_month):
    _, last_day = calendar.monthrange(roster_month.year, roster_month.month)
    existing = {day.duty_date: day for day in roster_month.days.all()}
    for day_number in range(1, last_day + 1):
        target = date(roster_month.year, roster_month.month, day_number)
        if target in existing:
            continue
        holiday_name = jpholiday.is_holiday_name(target) or ""
        if holiday_name:
            is_holiday = True
            source = CalendarDay.HolidaySource.NATIONAL
        elif target.weekday() >= 5:
            is_holiday = True
            source = CalendarDay.HolidaySource.WEEKEND
        else:
            is_holiday = False
            source = CalendarDay.HolidaySource.WEEKDAY
        CalendarDay.objects.create(
            roster_month=roster_month,
            duty_date=target,
            is_holiday=is_holiday,
            holiday_name=holiday_name,
            holiday_source=source,
        )
    return roster_month.days.all()


class GenerationError(Exception):
    pass


def slots_for(roster_month):
    settings = {
        (setting.calendar_day_id, setting.duty_type): setting.is_enabled
        for setting in roster_month.duty_slot_settings.all()
    }
    slots = []
    for day in roster_month.days.all():
        if settings.get((day.id, DutyType.DAY), day.is_holiday):
            slots.append((day, DutyType.DAY))
        if settings.get((day.id, DutyType.NIGHT), True):
            slots.append((day, DutyType.NIGHT))
    return slots


@transaction.atomic
def generate_roster(roster_month):
    ensure_calendar(roster_month)
    members = list(
        StaffMember.objects.filter(is_active=True, is_deleted=False)
    )
    if not members:
        raise GenerationError("有効な担当者が登録されていません。")

    slots = slots_for(roster_month)
    blocked = set(
        roster_month.unavailable_slots.values_list(
            "calendar_day_id", "staff_member_id", "duty_type"
        )
    )
    model = cp_model.CpModel()
    assigned = {}

    for slot_index, (day, duty_type) in enumerate(slots):
        candidates = []
        for member_index, member in enumerate(members):
            variable = model.new_bool_var(f"x_{slot_index}_{member_index}")
            assigned[(slot_index, member_index)] = variable
            if (day.id, member.id, duty_type) in blocked:
                model.add(variable == 0)
            candidates.append(variable)
        model.add_exactly_one(candidates)

    slots_by_day = defaultdict(list)
    for slot_index, (day, _duty_type) in enumerate(slots):
        slots_by_day[day.id].append(slot_index)
    for day_slots in slots_by_day.values():
        for member_index in range(len(members)):
            model.add(
                sum(assigned[(index, member_index)] for index in day_slots) <= 1
            )

    holiday_indexes = [
        index for index, (day, _duty_type) in enumerate(slots) if day.is_holiday
    ]
    day_indexes = [
        index for index, (_day, duty_type) in enumerate(slots)
        if duty_type == DutyType.DAY
    ]
    night_indexes = [
        index for index, (_day, duty_type) in enumerate(slots)
        if duty_type == DutyType.NIGHT
    ]
    holiday_counts = []
    total_counts = []
    day_counts = []
    night_counts = []
    for member_index in range(len(members)):
        holiday_count = model.new_int_var(
            0, len(holiday_indexes), f"holiday_{member_index}"
        )
        model.add(
            holiday_count
            == sum(assigned[(index, member_index)] for index in holiday_indexes)
        )
        holiday_counts.append(holiday_count)

        total_count = model.new_int_var(0, len(slots), f"total_{member_index}")
        model.add(
            total_count
            == sum(assigned[(index, member_index)] for index in range(len(slots)))
        )
        total_counts.append(total_count)

        day_count = model.new_int_var(0, len(day_indexes), f"day_{member_index}")
        night_count = model.new_int_var(
            0, len(night_indexes), f"night_{member_index}"
        )
        model.add(
            day_count
            == sum(assigned[(index, member_index)] for index in day_indexes)
        )
        model.add(
            night_count
            == sum(assigned[(index, member_index)] for index in night_indexes)
        )
        day_counts.append(day_count)
        night_counts.append(night_count)

    target_counts = {
        setting.staff_member_id: setting.target_count
        for setting in roster_month.staff_settings.exclude(target_count__isnull=True)
        if setting.staff_member_id in {member.id for member in members}
    }
    specified_total = sum(target_counts.values())
    if len(target_counts) == len(members) and specified_total != len(slots):
        raise GenerationError(
            f"全員の月間担当回数の合計は{specified_total}回ですが、"
            f"必要な当直枠は{len(slots)}回です。"
        )
    if specified_total > len(slots):
        raise GenerationError(
            f"指定した月間担当回数の合計が、必要な{len(slots)}枠を超えています。"
        )
    for member_index, member in enumerate(members):
        if member.id in target_counts:
            model.add(total_counts[member_index] == target_counts[member.id])

    holiday_max = model.new_int_var(0, len(holiday_indexes), "holiday_max")
    holiday_min = model.new_int_var(0, len(holiday_indexes), "holiday_min")
    model.add_max_equality(holiday_max, holiday_counts)
    model.add_min_equality(holiday_min, holiday_counts)
    model.add(holiday_max - holiday_min <= 1)

    spread_terms = []
    for label, counts, upper in [
        ("total", total_counts, len(slots)),
        ("day", day_counts, len(day_indexes)),
        ("night", night_counts, len(night_indexes)),
    ]:
        maximum = model.new_int_var(0, upper, f"{label}_max")
        minimum = model.new_int_var(0, upper, f"{label}_min")
        model.add_max_equality(maximum, counts)
        model.add_min_equality(minimum, counts)
        spread_terms.append(maximum - minimum)

    consecutive_penalties = []
    days = list(roster_month.days.all())
    day_slot_map = {
        day.id: [
            index
            for index, (slot_day, _duty_type) in enumerate(slots)
            if slot_day.id == day.id
        ]
        for day in days
    }
    for previous, current in zip(days, days[1:]):
        if current.duty_date - previous.duty_date != timedelta(days=1):
            continue
        for member_index in range(len(members)):
            penalty = model.new_bool_var(
                f"consecutive_{previous.id}_{current.id}_{member_index}"
            )
            previous_work = sum(
                assigned[(index, member_index)]
                for index in day_slot_map[previous.id]
            )
            current_work = sum(
                assigned[(index, member_index)]
                for index in day_slot_map[current.id]
            )
            model.add(penalty >= previous_work + current_work - 1)
            consecutive_penalties.append(penalty)

    model.minimize(
        100 * sum(spread_terms)
        + 10 * sum(consecutive_penalties)
        + holiday_max
    )
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 15
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise GenerationError(
            "希望しない日、月間担当回数、休日担当の公平条件を"
            "同時に満たせません。設定を見直してください。"
        )

    new_version = roster_month.generation_version + 1
    roster_month.assignments.all().delete()
    records = []
    for slot_index, (day, duty_type) in enumerate(slots):
        for member_index, member in enumerate(members):
            if solver.value(assigned[(slot_index, member_index)]):
                records.append(
                    DutyAssignment(
                        roster_month=roster_month,
                        calendar_day=day,
                        staff_member=member,
                        duty_type=duty_type,
                        generation_version=new_version,
                    )
                )
                break
    DutyAssignment.objects.bulk_create(records)
    roster_month.generation_version = new_version
    roster_month.status = roster_month.Status.GENERATED
    roster_month.confirmed_at = None
    roster_month.save(
        update_fields=["generation_version", "status", "confirmed_at", "updated_at"]
    )
    return records
