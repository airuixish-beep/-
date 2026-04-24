from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/support-chat/visitor/(?P<public_token>[\w\-]+)/$", consumers.VisitorChatConsumer.as_asgi()),
    re_path(r"^ws/support-chat/operator/$", consumers.OperatorChatConsumer.as_asgi()),
]
