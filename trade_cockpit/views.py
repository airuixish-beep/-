from django.template.response import TemplateResponse
from django.urls import reverse

from core.views import build_admin_shell_context

from .services import CURRENCY_OPTIONS, RANGE_OPTIONS, TradeCockpitService, parse_trade_cockpit_filters


def dashboard_view(request):
    filters = parse_trade_cockpit_filters(request.GET)
    context = build_admin_shell_context(
        request,
        title="战情驾驶舱",
        subtitle=f"{filters.label} · {filters.currency_label}。统一查看订单、支付、账务、风控与异常处理流。",
        active_nav="trade_cockpit",
        kicker="交易战情中心",
        breadcrumbs=[
            {"label": "后台首页", "url": reverse("admin:index")},
            {"label": "战情驾驶舱"},
        ],
        topbar_actions=[
            {"label": "订单", "url": reverse("admin:orders_order_changelist")},
            {"label": "支付", "url": reverse("admin:payments_payment_changelist")},
            {"label": "退款", "url": reverse("admin:transactions_refund_changelist")},
            {"label": "风控", "url": reverse("admin:transactions_riskassessment_changelist"), "primary": True},
        ],
    )
    context.update(TradeCockpitService.get_dashboard_summary(filters))
    context.update(
        {
            "filters": filters,
            "range_options": RANGE_OPTIONS,
            "currency_options": CURRENCY_OPTIONS,
        }
    )
    return TemplateResponse(request, "admin/trade_cockpit/dashboard.html", context)
