from django.urls import path

from . import views

app_name = "support_chat"

urlpatterns = [
    path("session/", views.session_view, name="session"),
    path("messages/", views.messages_view, name="messages"),
    path("send/", views.visitor_send_view, name="send"),
    path("read/", views.mark_read_view, name="read"),
    path("offline/", views.offline_message_view, name="offline"),
]
