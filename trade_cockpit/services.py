from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils.safestring import mark_safe

from orders.models import Order
from payments.models import Payment
from transactions.models import LedgerEntry, LedgerTransaction, Refund, RiskAssessment

ZERO = Decimal("0.00")
RANGE_OPTIONS = [
    ("today", "今天"),
    ("7d", "近7天"),
    ("30d", "近30天"),
    ("month", "本月"),
    ("custom", "自定义"),
]
RANGE_LABELS = dict(RANGE_OPTIONS)
CURRENCY_OPTIONS = [("all", "全部币种"), ("usd", "美元"), ("cny", "人民币"), ("eur", "欧元")]
CURRENCY_LABELS = dict(CURRENCY_OPTIONS)


@dataclass(frozen=True)
class TradeCockpitFilters:
    range_key: str
    start_date: date
    end_date: date
    label: str
    currency: str
    currency_label: str


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _build_daily_rows(filters, paid_orders, payments, refunds):
    rows = []
    current = filters.start_date
    while current <= filters.end_date:
        day_orders = paid_orders.filter(paid_at__date=current)
        day_payments = payments.filter(created_at__date=current)
        day_refunds = refunds.filter(completed_at__date=current)
        day_payment_total = day_payments.count()
        day_paid_count = day_payments.filter(status=Payment.Status.PAID).count()
        gmv = day_orders.aggregate(total=Sum("total_amount"))["total"] or ZERO
        refund_total = day_refunds.aggregate(total=Sum("amount"))["total"] or ZERO
        rows.append(
            {
                "date": current,
                "label": current.strftime("%m-%d"),
                "gmv": gmv,
                "gmv_value": float(gmv),
                "orders": day_orders.count(),
                "refund_total": refund_total,
                "refund_value": float(refund_total),
                "paid_rate": round((day_paid_count / day_payment_total) * 100, 1) if day_payment_total else 0,
            }
        )
        current += timedelta(days=1)
    return rows


def _build_svg_path(points):
    if not points:
        return ""
    start_x, start_y = points[0]
    segments = [f"M {start_x:.1f} {start_y:.1f}"]
    for x, y in points[1:]:
        segments.append(f"L {x:.1f} {y:.1f}")
    return " ".join(segments)


def parse_trade_cockpit_filters(params):
    today = date.today()
    range_key = params.get("range", "7d")
    start_date = today - timedelta(days=6)
    end_date = today

    if range_key == "today":
        start_date = end_date = today
    elif range_key == "7d":
        start_date = today - timedelta(days=6)
    elif range_key == "30d":
        start_date = today - timedelta(days=29)
    elif range_key == "month":
        start_date = today.replace(day=1)
    elif range_key == "custom":
        custom_start = _parse_date(params.get("start_date"))
        custom_end = _parse_date(params.get("end_date"))
        if custom_start and custom_end:
            start_date, end_date = sorted((custom_start, custom_end))
        elif custom_start:
            start_date, end_date = custom_start, today
        elif custom_end:
            start_date = custom_end - timedelta(days=29)
            end_date = custom_end
        else:
            range_key = "7d"
    else:
        range_key = "7d"

    currency = params.get("currency", "all").upper()
    if currency != "ALL" and currency not in {"USD", "CNY", "EUR"}:
        currency = "ALL"

    currency_key = currency.lower()
    return TradeCockpitFilters(
        range_key=range_key,
        start_date=start_date,
        end_date=end_date,
        label=RANGE_LABELS[range_key],
        currency=currency_key,
        currency_label=CURRENCY_LABELS[currency_key],
    )


def _filter_by_date(queryset, field_name, filters):
    return queryset.filter(
        **{
            f"{field_name}__date__gte": filters.start_date,
            f"{field_name}__date__lte": filters.end_date,
        }
    )


def _apply_currency_filter(filters, orders, paid_orders, payments, refunds, ledger_entries, ledger_transactions, risk_assessments):
    if filters.currency == "all":
        return orders, paid_orders, payments, refunds, ledger_entries, ledger_transactions, risk_assessments

    currency = filters.currency.upper()
    orders = orders.filter(currency=currency)
    paid_orders = paid_orders.filter(currency=currency)
    payments = payments.filter(currency=currency)
    refunds = refunds.filter(currency=currency)
    ledger_entries = ledger_entries.filter(currency=currency)
    ledger_transactions = ledger_transactions.filter(currency=currency)
    risk_assessments = risk_assessments.filter(transaction__currency=currency)
    return orders, paid_orders, payments, refunds, ledger_entries, ledger_transactions, risk_assessments


class TradeCockpitService:
    @staticmethod
    def get_dashboard_summary(filters):
        orders = _filter_by_date(Order.objects.all(), "created_at", filters)
        paid_orders = _filter_by_date(Order.objects.filter(payment_status=Order.PaymentStatus.PAID), "paid_at", filters)
        payments = _filter_by_date(Payment.objects.select_related("order"), "created_at", filters)
        refunds = _filter_by_date(
            Refund.objects.filter(status=Refund.Status.SUCCEEDED).select_related("transaction", "transaction__order"),
            "completed_at",
            filters,
        )
        ledger_entries = _filter_by_date(LedgerEntry.objects.select_related("account"), "created_at", filters)
        ledger_transactions = _filter_by_date(
            LedgerTransaction.objects.select_related("order", "payment", "refund"),
            "occurred_at",
            filters,
        )
        risk_assessments = _filter_by_date(
            RiskAssessment.objects.select_related("transaction", "transaction__order"),
            "created_at",
            filters,
        )
        orders, paid_orders, payments, refunds, ledger_entries, ledger_transactions, risk_assessments = _apply_currency_filter(
            filters,
            orders,
            paid_orders,
            payments,
            refunds,
            ledger_entries,
            ledger_transactions,
            risk_assessments,
        )
        alerts = list(risk_assessments.exclude(decision=RiskAssessment.Decision.ALLOW).order_by("-created_at")[:6])

        gmv = paid_orders.aggregate(total=Sum("total_amount"))["total"] or ZERO
        refund_total = refunds.aggregate(total=Sum("amount"))["total"] or ZERO
        fee_total = (
            ledger_entries.filter(account__code="payment_fees", direction=LedgerEntry.Direction.DEBIT).aggregate(total=Sum("amount"))["total"]
            or ZERO
        )
        net_amount = gmv - refund_total - fee_total
        order_count = orders.count()
        paid_count = paid_orders.count()
        payment_total = payments.count()
        paid_payment_count = payments.filter(status=Payment.Status.PAID).count()
        failed_payment_count = payments.filter(status=Payment.Status.FAILED).count()
        paid_rate = round((paid_payment_count / payment_total) * 100, 1) if payment_total else 0
        daily_rows = _build_daily_rows(filters, paid_orders, payments, refunds)
        max_gmv_value = max((row["gmv_value"] for row in daily_rows), default=0)
        max_refund_value = max((row["refund_value"] for row in daily_rows), default=0)
        max_paid_rate_value = max((row["paid_rate"] for row in daily_rows), default=0)
        chart_width = 720
        chart_height = 240
        chart_padding_x = 44
        chart_padding_top = 20
        chart_padding_bottom = 34
        plot_width = chart_width - (chart_padding_x * 2)
        plot_height = chart_height - chart_padding_top - chart_padding_bottom
        point_count = max(len(daily_rows), 1)
        step_x = plot_width / max(point_count - 1, 1)
        trend_points = []
        gmv_line_points = []
        rate_line_points = []
        for index, row in enumerate(daily_rows):
            x = chart_padding_x + (index * step_x)
            gmv_ratio = 0 if max_gmv_value == 0 else row["gmv_value"] / max_gmv_value
            refund_ratio = 0 if max_refund_value == 0 else row["refund_value"] / max_refund_value
            rate_ratio = 0 if max_paid_rate_value == 0 else row["paid_rate"] / max_paid_rate_value
            gmv_y = chart_padding_top + (plot_height * (1 - gmv_ratio))
            rate_y = chart_padding_top + (plot_height * (1 - rate_ratio))
            refund_height = 0 if refund_ratio == 0 else max(8, round(plot_height * refund_ratio))
            refund_y = chart_padding_top + plot_height - refund_height
            trend_points.append(
                {
                    **row,
                    "x": round(x, 1),
                    "gmv_y": round(gmv_y, 1),
                    "refund_y": round(refund_y, 1),
                    "refund_height": refund_height,
                    "rate_y": round(rate_y, 1),
                }
            )
            gmv_line_points.append((x, gmv_y))
            rate_line_points.append((x, rate_y))

        chart = {
            "width": chart_width,
            "height": chart_height,
            "plot_bottom": chart_padding_top + plot_height,
            "gmv_path": mark_safe(_build_svg_path(gmv_line_points)),
            "rate_path": mark_safe(_build_svg_path(rate_line_points)),
            "points": trend_points,
        }

        return {
            "kpi_cards": [
                {"label": "GMV", "value": f"{gmv}", "hint": f"{filters.label} {filters.currency_label}已支付订单总额"},
                {"label": "订单", "value": str(order_count), "hint": f"已支付 {paid_count} 单"},
                {"label": "支付成功率", "value": f"{paid_rate}%", "hint": f"失败 {failed_payment_count} 笔"},
                {"label": "风险预警", "value": str(len(alerts)), "hint": "review / block"},
                {"label": "退款", "value": f"{refund_total}", "hint": f"成功退款 {refunds.count()} 笔"},
                {"label": "净资金", "value": f"{net_amount}", "hint": "GMV - 退款 - 手续费"},
            ],
            "trade_radar": {
                "gmv": gmv,
                "paid_rate": paid_rate,
                "refund_total": refund_total,
                "net_amount": net_amount,
                "order_count": order_count,
                "paid_order_count": paid_count,
                "payment_totals": list(
                    payments.values("provider")
                    .annotate(total_count=Count("id"), paid_count=Count("id", filter=Q(status=Payment.Status.PAID)))
                    .order_by("provider")
                ),
                "chart": chart,
                "trend_peak_gmv": max_gmv_value,
                "trend_peak_refund": max_refund_value,
            },
            "recent_orders": orders.order_by("-created_at")[:8],
            "payment_summary": {
                "providers": list(
                    payments.values("provider")
                    .annotate(
                        total_count=Count("id"),
                        paid_count=Count("id", filter=Q(status=Payment.Status.PAID)),
                        failed_count=Count("id", filter=Q(status=Payment.Status.FAILED)),
                    )
                    .order_by("provider")
                ),
                "failed_count": failed_payment_count,
                "requires_action_count": payments.filter(status=Payment.Status.REQUIRES_ACTION).count(),
            },
            "funds_flow": {
                "capture_amount": gmv,
                "refund_amount": refund_total,
                "fee_amount": fee_total,
                "net_amount": net_amount,
                "ledger_transactions_count": ledger_transactions.count(),
                "recent_ledger_transactions": ledger_transactions.order_by("-occurred_at")[:6],
            },
            "risk_summary": {
                "review_count": risk_assessments.filter(decision=RiskAssessment.Decision.REVIEW).count(),
                "block_count": risk_assessments.filter(decision=RiskAssessment.Decision.BLOCK).count(),
                "latest_assessments": alerts,
            },
            "alerts": alerts,
            "copilot_suggestions": [
                {
                    "title": "优先处理风险审核单",
                    "description": "建议先查看 review / block 交易，避免已支付订单继续进入履约。",
                },
                {
                    "title": "关注退款与手续费变化",
                    "description": "当退款率上升时，同时检查支付失败与售后原因分布。",
                },
                {
                    "title": "补齐账务快照任务",
                    "description": "二期下一步建议增加余额快照与结算任务，让驾驶舱展示不依赖实时全表聚合。",
                },
            ],
        }
