from django.contrib import admin
from django.urls import path

from . import views

app_name = "analytics_dashboard"

urlpatterns = [
    path("", admin.site.admin_view(views.dashboard_view), name="index"),
]
