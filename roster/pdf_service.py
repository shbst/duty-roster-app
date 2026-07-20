from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .models import DutyType, StaffMember


def build_roster_pdf(roster_month):
    pdfmetrics.registerFont(UnicodeCIDFont("HeiseiKakuGo-W5"))
    font_name = "HeiseiKakuGo-W5"
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=f"{roster_month} 当直表",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "JapaneseTitle",
        parent=styles["Title"],
        fontName=font_name,
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#173b57"),
    )
    heading_style = ParagraphStyle(
        "JapaneseHeading",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=9,
        textColor=colors.HexColor("#173b57"),
    )
    story = [
        Paragraph(f"{roster_month} 当直表", title_style),
        Spacer(1, 4 * mm),
    ]
    assignment_map = {
        (assignment.calendar_day_id, assignment.duty_type):
        assignment.staff_member.name
        for assignment in roster_month.assignments.select_related("staff_member")
    }
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    table_data = [["日付", "曜日・区分", "日直", "夜間当直"]]
    for day in roster_month.days.all():
        kind = day.holiday_name or ("休日" if day.is_holiday else "平日")
        table_data.append(
            [
                day.duty_date.strftime("%m/%d"),
                f"{weekdays[day.duty_date.weekday()]}・{kind}",
                assignment_map.get((day.id, DutyType.DAY), "-"),
                assignment_map.get((day.id, DutyType.NIGHT), "-"),
            ]
        )
    schedule_table = Table(
        table_data,
        colWidths=[22 * mm, 42 * mm, 48 * mm, 48 * mm],
        repeatRows=1,
    )
    schedule_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#173b57")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (0, -1), "CENTER"),
                ("ALIGN", (2, 1), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b9c6cc")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#f5f8f8")],
                ),
                ("TOPPADDING", (0, 0), (-1, -1), 1.3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.3),
            ]
        )
    )

    summary_data = [["担当者", "合計", "日直", "夜間", "休日"]]
    for member in StaffMember.objects.filter(is_deleted=False):
        assignments = roster_month.assignments.filter(staff_member=member)
        if assignments.exists():
            summary_data.append(
                [
                    member.name,
                    assignments.count(),
                    assignments.filter(duty_type=DutyType.DAY).count(),
                    assignments.filter(duty_type=DutyType.NIGHT).count(),
                    assignments.filter(calendar_day__is_holiday=True).count(),
                ]
            )
    summary = Table(
        summary_data,
        colWidths=[24 * mm, 10 * mm, 10 * mm, 10 * mm, 10 * mm],
        repeatRows=1,
    )
    summary.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dfeeea")),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#173b57")),
                ("ALIGN", (1, 0), (-1, -1), "CENTER"),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#b9c6cc")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]
        )
    )
    content = Table(
        [
            [
                schedule_table,
                [Paragraph("担当回数", heading_style), Spacer(1, 2 * mm), summary],
            ]
        ],
        colWidths=[166 * mm, 70 * mm],
    )
    content.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 6 * mm),
                ("LEFTPADDING", (1, 0), (1, 0), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.append(content)
    document.build(story)
    return buffer.getvalue()
