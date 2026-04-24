from django.urls import path

from . import api_views

app_name = "support_chat_api"

urlpatterns = [
    path("sessions", api_views.api_session_create_view, name="sessions_create"),
    path("sessions/<str:public_token>", api_views.api_session_detail_view, name="session_detail"),
    path("sessions/<str:public_token>/messages", api_views.api_session_messages_view, name="session_messages"),
    path("sessions/<str:public_token>/messages/send", api_views.api_session_send_view, name="session_send"),
    path("sessions/<str:public_token>/read", api_views.api_session_read_view, name="session_read"),
    path("admin/sessions", api_views.api_admin_sessions_view, name="admin_sessions"),
    path("admin/sessions/<int:session_id>/messages", api_views.api_admin_session_messages_view, name="admin_session_messages"),
    path("admin/sessions/<int:session_id>/messages/send", api_views.api_admin_session_reply_view, name="admin_session_reply"),
    path("admin/sessions/<int:session_id>/close", api_views.api_admin_session_close_view, name="admin_session_close"),
]
