from django.contrib import admin
from django.template.response import TemplateResponse

from .services import CURRENCY_OPTIONS, RANGE_OPTIONS, build_dashboard_context, get_marketing_placeholders, parse_dashboard_filters


def dashboard_view(request):
    filters = parse_dashboard_filters(request.GET)
    context = {
        **admin.site.each_context(request),
        **build_dashboard_context(filters),
        "title": "数据看板",
        "subtitle": f"{filters.label} · {filters.currency_label}",
        "filters": filters,
        "range_options": RANGE_OPTIONS,
        "currency_options": CURRENCY_OPTIONS,
        "marketing_placeholders": get_marketing_placeholders(),
    }
    return TemplateResponse(request, "admin/analytics_dashboard/index.html", context)
