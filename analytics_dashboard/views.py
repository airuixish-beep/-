from urllib.parse import urlencode

from django.contrib import admin
from django.template.response import TemplateResponse
from django.urls import reverse

from .services import CURRENCY_OPTIONS, RANGE_OPTIONS, build_dashboard_context, build_quiz_dashboard_context, get_marketing_placeholders, parse_dashboard_filters


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


def quiz_dashboard_view(request):
    filters = parse_dashboard_filters(request.GET)
    submissions_changelist_url = reverse("admin:pages_fiveelementsubmission_changelist")
    base_submission_query = {
        "created_at__date__gte": filters.start_date.isoformat(),
        "created_at__date__lte": filters.end_date.isoformat(),
    }
    context = {
        **admin.site.each_context(request),
        **build_quiz_dashboard_context(filters),
        "title": "五行测试提交统计",
        "subtitle": f"{filters.label} · {filters.currency_label}",
        "filters": filters,
        "range_options": RANGE_OPTIONS,
        "currency_options": CURRENCY_OPTIONS,
        "submission_changelist_url": submissions_changelist_url,
        "submission_all_url": f"{submissions_changelist_url}?{urlencode(base_submission_query)}",
        "submission_has_email_url": f"{submissions_changelist_url}?{urlencode({**base_submission_query, 'has_email': 'yes'})}",
        "submission_no_email_url": f"{submissions_changelist_url}?{urlencode({**base_submission_query, 'has_email': 'no'})}",
    }
    return TemplateResponse(request, "admin/analytics_dashboard/quiz_dashboard.html", context)
