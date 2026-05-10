from urllib.parse import urlencode

from django.template.response import TemplateResponse
from django.urls import reverse

from core.views import build_admin_shell_context

from .services import (
    CURRENCY_OPTIONS,
    RANGE_OPTIONS,
    build_dashboard_context,
    build_quiz_dashboard_context,
    build_traffic_hub_context,
    get_marketing_placeholders,
    parse_dashboard_filters,
)


def dashboard_view(request):
    filters = parse_dashboard_filters(request.GET)
    context = {
        **build_admin_shell_context(
            request,
            title="Business Analytics",
            subtitle=f"{filters.label} · {filters.currency_label}。统一查看订单、支付、发货、商品和地区经营表现。",
            active_nav="analytics",
            kicker="Performance Dashboard",
            breadcrumbs=[
                {"label": "后台首页", "url": reverse("admin:index")},
                {"label": "Business Analytics"},
            ],
            topbar_actions=[
                {"label": "五行测试统计", "url": reverse("analytics_dashboard:quiz")},
                {"label": "订单管理", "url": reverse("admin:orders_order_changelist"), "primary": True},
            ],
        ),
        **build_dashboard_context(filters),
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
        **build_admin_shell_context(
            request,
            title="Five Elements Quiz Analytics",
            subtitle=f"{filters.label} · {filters.currency_label}。集中查看测试提交、结果分布、留资率与来源归因。",
            active_nav="quiz",
            kicker="Lead Generation Analytics",
            breadcrumbs=[
                {"label": "后台首页", "url": reverse("admin:index")},
                {"label": "Five Elements Quiz Analytics"},
            ],
            topbar_actions=[
                {"label": "经营分析", "url": reverse("analytics_dashboard:index")},
                {"label": "提交后台", "url": submissions_changelist_url, "primary": True},
            ],
        ),
        **build_quiz_dashboard_context(filters),
        "filters": filters,
        "range_options": RANGE_OPTIONS,
        "currency_options": CURRENCY_OPTIONS,
        "submission_changelist_url": submissions_changelist_url,
        "submission_all_url": f"{submissions_changelist_url}?{urlencode(base_submission_query)}",
        "submission_has_email_url": f"{submissions_changelist_url}?{urlencode({**base_submission_query, 'has_email': 'yes'})}",
        "submission_no_email_url": f"{submissions_changelist_url}?{urlencode({**base_submission_query, 'has_email': 'no'})}",
    }
    return TemplateResponse(request, "admin/analytics_dashboard/quiz_dashboard.html", context)


def traffic_hub_view(request):
    filters = parse_dashboard_filters(request.GET)
    submissions_changelist_url = reverse("admin:pages_fiveelementsubmission_changelist")
    base_submission_query = {
        "created_at__date__gte": filters.start_date.isoformat(),
        "created_at__date__lte": filters.end_date.isoformat(),
    }
    context = {
        **build_admin_shell_context(
            request,
            title="Traffic Hub",
            subtitle=f"{filters.label} · {filters.currency_label}。先看来源、介质、活动与线索沉淀，再决定是否进入经营分析、五行测试或客户工作台继续处理。",
            active_nav="traffic",
            kicker="Traffic Mission Control",
            breadcrumbs=[
                {"label": "后台首页", "url": reverse("admin:index")},
                {"label": "Traffic Hub"},
            ],
            topbar_actions=[
                {"label": "经营分析", "url": reverse("analytics_dashboard:index")},
                {"label": "五行测试", "url": reverse("analytics_dashboard:quiz")},
                {"label": "提交后台", "url": submissions_changelist_url, "primary": True},
            ],
        ),
        **build_traffic_hub_context(filters),
        "filters": filters,
        "range_options": RANGE_OPTIONS,
        "currency_options": CURRENCY_OPTIONS,
        "submission_changelist_url": submissions_changelist_url,
        "submission_all_url": f"{submissions_changelist_url}?{urlencode(base_submission_query)}",
        "submission_has_email_url": f"{submissions_changelist_url}?{urlencode({**base_submission_query, 'has_email': 'yes'})}",
        "submission_no_email_url": f"{submissions_changelist_url}?{urlencode({**base_submission_query, 'has_email': 'no'})}",
    }
    return TemplateResponse(request, "admin/analytics_dashboard/traffic_hub.html", context)
