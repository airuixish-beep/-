from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from support_chat import views as support_chat_views

urlpatterns = [
    path("admin/analytics/", include("analytics_dashboard.urls")),
    path("admin/support-chat/", admin.site.admin_view(support_chat_views.operator_console_view), name="support_chat_console"),
    path("admin/support-chat/sessions/", admin.site.admin_view(support_chat_views.operator_sessions_view), name="support_chat_sessions"),
    path("admin/support-chat/messages/", admin.site.admin_view(support_chat_views.operator_messages_view), name="support_chat_messages"),
    path("admin/support-chat/reply/", admin.site.admin_view(support_chat_views.operator_reply_view), name="support_chat_reply"),
    path("admin/support-chat/close/", admin.site.admin_view(support_chat_views.operator_close_view), name="support_chat_close"),
    path("admin/", admin.site.urls),
    path("support-chat/", include(("support_chat.urls", "support_chat"), namespace="support_chat_public")),
    path("", include("pages.urls")),
    path("products/", include("products.urls")),
    path("orders/", include("orders.urls")),
    path("payments/", include("payments.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
