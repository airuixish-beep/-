from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from core import views as core_views
from support_chat import views as support_chat_views
from trade_cockpit import views as trade_cockpit_views

urlpatterns = [
    path("healthz/live", core_views.health_live, name="health_live"),
    path("healthz/ready", core_views.health_ready, name="health_ready"),
    path("admin/trade-cockpit/", admin.site.admin_view(trade_cockpit_views.dashboard_view), name="trade_cockpit_dashboard"),
    path("admin/analytics/", include("analytics_dashboard.urls")),
    path("admin/ai-command/", admin.site.admin_view(core_views.ai_command_view), name="ai_command_center"),
    path("admin/content-os/", admin.site.admin_view(core_views.content_os_view), name="content_os"),
    path("admin/orders/console/", admin.site.admin_view(core_views.order_console_view), name="order_console"),
    path("admin/products/console/", admin.site.admin_view(core_views.product_console_view), name="product_console"),
    path("admin/payments/console/", admin.site.admin_view(core_views.payment_console_view), name="payment_console"),
    path("admin/customers/", admin.site.admin_view(core_views.customers_view), name="backoffice_customers"),
    path("admin/settings/", admin.site.admin_view(core_views.settings_view), name="backoffice_settings"),
    path("admin/support-chat/", admin.site.admin_view(support_chat_views.operator_console_view), name="support_chat_console"),
    path("admin/support-chat/sessions/", admin.site.admin_view(support_chat_views.operator_sessions_view), name="support_chat_sessions"),
    path("admin/support-chat/messages/", admin.site.admin_view(support_chat_views.operator_messages_view), name="support_chat_messages"),
    path("admin/support-chat/reply/", admin.site.admin_view(support_chat_views.operator_reply_view), name="support_chat_reply"),
    path("admin/support-chat/draft/", admin.site.admin_view(support_chat_views.operator_draft_view), name="support_chat_draft"),
    path("admin/support-chat/close/", admin.site.admin_view(support_chat_views.operator_close_view), name="support_chat_close"),
    path("admin/support_chat/", admin.site.admin_view(RedirectView.as_view(pattern_name="support_chat_console", permanent=False))),
    path("admin/support_chat/chatsession/", admin.site.admin_view(RedirectView.as_view(pattern_name="support_chat_console", permanent=False))),
    path("admin/support_chat/chatmessage/", admin.site.admin_view(RedirectView.as_view(pattern_name="support_chat_console", permanent=False))),
    path("admin/", admin.site.urls),
    path("support-chat/", include(("support_chat.urls", "support_chat"), namespace="support_chat_public")),
    path("api/lobster/customer-service/", include(("support_chat.api_urls", "support_chat_api"), namespace="support_chat_api")),
    path("", include("pages.urls")),
    path("products/", include("products.urls")),
    path("orders/", include("orders.urls")),
    path("payments/", include("payments.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
