from django.conf import settings

from .models import SiteConfig


def site_config(request):
    return {
        "site_config": SiteConfig.get_solo(),
        "CHAT_WIDGET_ENABLED": settings.CHAT_WIDGET_ENABLED,
        "CHAT_POLL_INTERVAL_MS": settings.CHAT_POLL_INTERVAL_MS,
    }
