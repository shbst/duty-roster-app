from django.urls import path
from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/<int:pk>/toggle/", views.staff_toggle, name="staff_toggle"),
    path("staff/<int:pk>/delete/", views.staff_delete, name="staff_delete"),
    path("rosters/<int:pk>/", views.roster_detail, name="roster_detail"),
    path("rosters/<int:pk>/availability/", views.availability, name="availability"),
    path("rosters/<int:pk>/holidays/", views.holidays, name="holidays"),
    path("rosters/<int:pk>/generate/", views.roster_generate, name="roster_generate"),
    path("rosters/<int:pk>/confirm/", views.roster_confirm, name="roster_confirm"),
    path("rosters/<int:pk>/pdf/", views.roster_pdf, name="roster_pdf"),
    path(
        "rosters/<int:pk>/assignments/<int:day_id>/<str:duty_type>/",
        views.assignment_update,
        name="assignment_update",
    ),
]
