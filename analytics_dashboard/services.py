from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Max, OuterRef, Q, Subquery, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from orders.models import Order, OrderItem
from pages.models import FiveElementProfile, FiveElementQuiz, FiveElementSubmission
from payments.models import Payment
from products.models import Product
from shipping.models import Shipment
from transactions.models import LedgerEntry, Refund, Transaction

ZERO_DECIMAL = Decimal("0.00")
LOW_STOCK_THRESHOLD = 5
RANGE_OPTIONS = [
    ("today", "今天"),
    ("7d", "近7天"),
    ("30d", "近30天"),
    ("month", "本月"),
    ("custom", "自定义"),
]
RANGE_LABELS = dict(RANGE_OPTIONS)
CURRENCY_OPTIONS = list(Product.Currency.choices)
CURRENCY_LABELS = dict(CURRENCY_OPTIONS)


@dataclass(frozen=True)
class DashboardFilters:
    range_key: str
    start_date: date
    end_date: date
    label: str
    currency: str
    currency_label: str


def parse_dashboard_filters(params):
    today = timezone.localdate()
    default_currency = settings.DEFAULT_CURRENCY if settings.DEFAULT_CURRENCY in CURRENCY_LABELS else Product.Currency.USD
    requested_currency = params.get("currency", default_currency)
    currency = requested_currency if requested_currency in CURRENCY_LABELS else default_currency

    range_key = params.get("range", "30d")
    start_date = today - timedelta(days=29)
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
            range_key = "30d"
    else:
        range_key = "30d"

    return DashboardFilters(
        range_key=range_key,
        start_date=start_date,
        end_date=end_date,
        label=RANGE_LABELS[range_key],
        currency=currency,
        currency_label=CURRENCY_LABELS[currency],
    )


def build_dashboard_context(filters):
    quiz_summary = get_quiz_summary(filters)
    return {
        "kpis": get_kpis(filters),
        "order_trends": get_order_trends(filters),
        "status_breakdowns": get_status_breakdowns(filters),
        "payment_summary": get_payment_summary(filters),
        "financial_summary": get_financial_summary(filters),
        "shipping_summary": get_shipping_summary(filters),
        "product_summary": get_product_leaderboards(filters),
        "geo_summary": get_geo_summary(filters),
        "quiz_summary": quiz_summary,
        "semantics": {
            "order_created": "按订单创建时间统计",
            "paid_orders": "按订单支付完成时间统计",
            "payments": "按支付记录创建时间统计",
            "transactions": "按交易支付完成时间或退款创建时间统计",
            "ledger": "按账务分录创建时间统计净收入与资金流",
            "shipping": "基于所选范围内已支付订单展示当前发货状态",
            "quiz_submissions": "按测试提交时间统计",
            "quiz_results": "按主导结果统计",
            "quiz_leads": "按留资邮箱统计",
        },
    }


def build_quiz_dashboard_context(filters):
    return {
        "quiz_summary": get_quiz_summary(filters),
        "quiz_attribution": get_quiz_attribution_summary(filters),
        "semantics": {
            "quiz_submissions": "按测试提交时间统计",
            "quiz_results": "按主导结果统计",
            "quiz_leads": "按留资邮箱统计",
            "quiz_attribution": "按提交记录携带的 UTM 来源统计",
        },
    }


def get_kpis(filters):
    orders = _filter_by_date(Order.objects.filter(currency=filters.currency), "created_at", filters)
    paid_orders = _paid_orders(filters)
    paid_transactions = _paid_transactions(filters)
    succeeded_refunds = _succeeded_refunds(filters)
    net_revenue = _net_revenue(filters)
    current_shipments = _current_shipments_for_paid_orders(filters)

    sales_total = paid_transactions.aggregate(total=Sum("amount"))["total"] or ZERO_DECIMAL
    refund_total = succeeded_refunds.aggregate(total=Sum("amount"))["total"] or ZERO_DECIMAL
    paid_order_count = paid_orders.count()
    shipping_in_progress_count = current_shipments.filter(
        status__in=[Shipment.Status.LABEL_PURCHASED, Shipment.Status.SHIPPED, Shipment.Status.IN_TRANSIT]
    ).count()
    delivered_order_count = current_shipments.filter(status=Shipment.Status.DELIVERED).count()

    return {
        "order_count": orders.count(),
        "paid_order_count": paid_order_count,
        "gmv": sales_total,
        "refund_total": refund_total,
        "net_revenue": net_revenue,
        "average_order_value": (sales_total / paid_order_count) if paid_order_count else ZERO_DECIMAL,
        "payment_conversion_rate": round((paid_order_count / orders.count()) * 100, 1) if orders.count() else 0,
        "refund_rate": round((refund_total / sales_total) * 100, 1) if sales_total else 0,
        "shipping_in_progress_count": shipping_in_progress_count,
        "delivered_order_count": delivered_order_count,
    }


def get_order_trends(filters):
    order_counts = {
        row["day"]: row["order_count"]
        for row in _filter_by_date(Order.objects.filter(currency=filters.currency), "created_at", filters)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(order_count=Count("id"))
        .order_by("day")
    }
    paid_amounts = {
        row["day"]: row["paid_amount"] or ZERO_DECIMAL
        for row in _paid_orders(filters)
        .annotate(day=TruncDate("paid_at"))
        .values("day")
        .annotate(paid_amount=Sum("total_amount"))
        .order_by("day")
    }
    paid_counts = {
        row["day"]: row["paid_count"]
        for row in _paid_orders(filters)
        .annotate(day=TruncDate("paid_at"))
        .values("day")
        .annotate(paid_count=Count("id"))
        .order_by("day")
    }

    days = _date_range(filters.start_date, filters.end_date)
    max_order_count = max(order_counts.values(), default=0)
    max_paid_amount = max(paid_amounts.values(), default=ZERO_DECIMAL)
    rows = []

    for day in days:
        order_count = order_counts.get(day, 0)
        paid_amount = paid_amounts.get(day, ZERO_DECIMAL)
        paid_count = paid_counts.get(day, 0)
        rows.append(
            {
                "date": day,
                "date_label": day.strftime("%m-%d"),
                "order_count": order_count,
                "paid_count": paid_count,
                "paid_amount": paid_amount,
                "order_width": _width(order_count, max_order_count),
                "paid_width": _width(paid_amount, max_paid_amount),
            }
        )

    return {
        "rows": rows,
        "max_order_count": max_order_count,
        "max_paid_amount": max_paid_amount,
    }


def get_status_breakdowns(filters):
    orders = _filter_by_date(Order.objects.filter(currency=filters.currency), "created_at", filters)
    payments = _filter_by_date(Payment.objects.filter(currency=filters.currency), "created_at", filters)

    return {
        "orders": _status_rows(orders, "status", Order.Status.choices),
        "payments": _status_rows(payments, "status", Payment.Status.choices),
        "fulfillment": _status_rows(orders, "fulfillment_status", Order.FulfillmentStatus.choices),
    }


def get_payment_summary(filters):
    payments = _filter_by_date(Payment.objects.filter(currency=filters.currency), "created_at", filters)
    rows = []

    for row in (
        payments.values("provider")
        .annotate(
            total_count=Count("id"),
            paid_count=Count("id", filter=Q(status=Payment.Status.PAID)),
            paid_amount=Sum("amount", filter=Q(status=Payment.Status.PAID)),
        )
        .order_by("provider")
    ):
        total_count = row["total_count"]
        paid_count = row["paid_count"]
        rows.append(
            {
                "provider": row["provider"],
                "provider_label": dict(Payment.Provider.choices).get(row["provider"], row["provider"]),
                "total_count": total_count,
                "paid_count": paid_count,
                "paid_amount": row["paid_amount"] or ZERO_DECIMAL,
                "success_rate": round((paid_count / total_count) * 100, 1) if total_count else 0,
            }
        )

    return {
        "providers": rows,
        "failed_count": payments.filter(status=Payment.Status.FAILED).count(),
        "recent_failures": list(payments.filter(status=Payment.Status.FAILED).select_related("order").order_by("-created_at")[:5]),
    }


def get_financial_summary(filters):
    paid_transactions = _paid_transactions(filters)
    refunds = _succeeded_refunds(filters)
    ledger_entries = _ledger_entries(filters)

    refund_total = refunds.aggregate(total=Sum("amount"))["total"] or ZERO_DECIMAL
    fee_total = ledger_entries.filter(account__code="payment_fees", direction=LedgerEntry.Direction.DEBIT).aggregate(total=Sum("amount"))["total"] or ZERO_DECIMAL
    gross_total = paid_transactions.aggregate(total=Sum("amount"))["total"] or ZERO_DECIMAL
    net_revenue = _net_revenue(filters)

    return {
        "gross_total": gross_total,
        "refund_total": refund_total,
        "fee_total": fee_total,
        "net_revenue": net_revenue,
        "refund_count": refunds.count(),
        "paid_transaction_count": paid_transactions.count(),
    }


def get_shipping_summary(filters):
    current_shipments = _current_shipments_for_paid_orders(filters)
    rows = _status_rows(current_shipments, "status", Shipment.Status.choices)

    return {
        "rows": rows,
        "exception_shipments": list(
            current_shipments.filter(status=Shipment.Status.EXCEPTION).select_related("order").order_by("-updated_at", "-created_at")[:5]
        ),
    }


def get_product_leaderboards(filters):
    paid_items = _filter_by_date(
        OrderItem.objects.filter(
            order__currency=filters.currency,
            order__payment_status=Order.PaymentStatus.PAID,
            order__paid_at__isnull=False,
        ),
        "order__paid_at",
        filters,
    )

    base_values = ("product_id", "product_name_snapshot", "sku_snapshot")
    annotated_items = paid_items.values(*base_values).annotate(total_quantity=Sum("quantity"), total_sales=Sum("line_total"))

    return {
        "top_by_quantity": list(annotated_items.order_by("-total_quantity", "-total_sales")[:5]),
        "top_by_sales": list(annotated_items.order_by("-total_sales", "-total_quantity")[:5]),
        "low_stock_products": list(
            Product.objects.filter(
                currency=filters.currency,
                is_active=True,
                is_purchasable=True,
                stock_quantity__lte=LOW_STOCK_THRESHOLD,
            )
            .order_by("stock_quantity", "name")[:5]
        ),
    }


def get_quiz_summary(filters):
    submissions = _quiz_submissions(filters)
    total_submissions = submissions.count()
    lead_count = submissions.exclude(respondent_email="").count()
    result_rows = list(
        submissions.exclude(primary_profile__isnull=True)
        .values("primary_profile__name", "primary_profile__sort_order", "primary_profile__id")
        .annotate(count=Count("id"))
        .order_by("-count", "primary_profile__sort_order", "primary_profile__id")
    )
    result_counts = {row["primary_profile__name"]: row["count"] for row in result_rows}
    lead_rows = list(
        submissions.exclude(respondent_email="")
        .values("respondent_email")
        .annotate(count=Count("id"), last_created_at=Max("created_at"))
        .order_by("-last_created_at", "respondent_email")[:10]
    )
    return {
        "quiz": submissions.first().quiz if submissions else FiveElementQuiz.objects.filter(is_active=True).order_by("sort_order", "id").first(),
        "total_submissions": total_submissions,
        "lead_count": lead_count,
        "lead_rate": round((lead_count / total_submissions) * 100, 1) if total_submissions else 0,
        "result_counts": result_counts,
        "lead_rows": lead_rows,
        "recent_submissions": list(submissions.select_related("primary_profile", "secondary_profile").order_by("-created_at")[:10]),
    }


def get_quiz_attribution_summary(filters):
    submissions = _quiz_submissions(filters)
    return {
        "sources": _quiz_attribution_rows(submissions, "utm_source", default_label="直接访问"),
        "mediums": _quiz_attribution_rows(submissions, "utm_medium", default_label="未标记 medium"),
        "campaigns": _quiz_attribution_rows(submissions, "utm_campaign", default_label="未标记 campaign"),
    }


def get_geo_summary(filters):
    paid_orders = _paid_orders(filters)

    countries = list(
        paid_orders.exclude(shipping_country="")
        .values("shipping_country")
        .annotate(order_count=Count("id"), sales_total=Sum("total_amount"))
        .order_by("-order_count", "shipping_country")[:6]
    )
    cities = list(
        paid_orders.exclude(shipping_city="")
        .values("shipping_city", "shipping_country")
        .annotate(order_count=Count("id"), sales_total=Sum("total_amount"))
        .order_by("-order_count", "shipping_country", "shipping_city")[:6]
    )

    for row in countries:
        row["sales_total"] = row["sales_total"] or ZERO_DECIMAL
    for row in cities:
        row["sales_total"] = row["sales_total"] or ZERO_DECIMAL

    return {
        "countries": countries,
        "cities": cities,
    }


def get_marketing_placeholders():
    return [
        {"title": "广告花费", "description": "待接入 Google / Meta / TikTok 广告平台数据"},
        {"title": "流量来源", "description": "待接入 GA4 渠道与会话数据"},
        {"title": "加购与结账漏斗", "description": "待接入 add_to_cart / begin_checkout 埋点"},
        {"title": "投产归因", "description": "待接入 CAC、ROAS、MER 与归因模型"},
    ]


def _quiz_submissions(filters):
    quiz = FiveElementQuiz.objects.filter(is_active=True).order_by("sort_order", "id").first()
    if not quiz:
        return FiveElementSubmission.objects.none()
    return _filter_by_date(quiz.submissions.select_related("quiz", "primary_profile", "secondary_profile"), "created_at", filters)


def _paid_orders(filters):
    return _filter_by_date(
        Order.objects.filter(
            currency=filters.currency,
            payment_status=Order.PaymentStatus.PAID,
            paid_at__isnull=False,
        ),
        "paid_at",
        filters,
    )


def _paid_transactions(filters):
    return _filter_by_date(
        Transaction.objects.filter(
            currency=filters.currency,
            status__in=[
                Transaction.Status.PAID,
                Transaction.Status.PARTIALLY_REFUNDED,
                Transaction.Status.REFUNDED,
            ],
            paid_at__isnull=False,
        ),
        "paid_at",
        filters,
    )


def _current_shipments_for_paid_orders(filters):
    paid_orders = _paid_orders(filters)
    latest_shipment_ids = (
        Shipment.objects.filter(order_id=OuterRef("pk"))
        .order_by("-created_at", "-id")
        .values("id")[:1]
    )
    return Shipment.objects.filter(id__in=Subquery(paid_orders.annotate(latest_shipment_id=Subquery(latest_shipment_ids)).values("latest_shipment_id"))).select_related("order")


def _succeeded_refunds(filters):
    return _filter_by_date(
        Refund.objects.filter(currency=filters.currency, status=Refund.Status.SUCCEEDED),
        "created_at",
        filters,
    )


def _ledger_entries(filters):
    return _filter_by_date(
        LedgerEntry.objects.filter(currency=filters.currency),
        "created_at",
        filters,
    )


def _net_revenue(filters):
    ledger_entries = _ledger_entries(filters)
    gross_total = ledger_entries.filter(account__code="customer_receipts", direction=LedgerEntry.Direction.CREDIT).aggregate(total=Sum("amount"))["total"] or ZERO_DECIMAL
    refund_total = ledger_entries.filter(account__code="refunds", direction=LedgerEntry.Direction.DEBIT).aggregate(total=Sum("amount"))["total"] or ZERO_DECIMAL
    fee_total = ledger_entries.filter(account__code="payment_fees", direction=LedgerEntry.Direction.DEBIT).aggregate(total=Sum("amount"))["total"] or ZERO_DECIMAL
    return gross_total - refund_total - fee_total


def _filter_by_date(queryset, field_name, filters):
    return queryset.filter(
        **{
            f"{field_name}__date__gte": filters.start_date,
            f"{field_name}__date__lte": filters.end_date,
        }
    )


def _status_rows(queryset, field_name, choices):
    counts = {
        row[field_name]: row["count"]
        for row in queryset.values(field_name).annotate(count=Count("id"))
    }
    total_count = sum(counts.values())
    rows = []

    for value, label in choices:
        count = counts.get(value, 0)
        rows.append(
            {
                "value": value,
                "label": label,
                "count": count,
                "ratio": round((count / total_count) * 100, 1) if total_count else 0,
                "width": _width(count, total_count),
            }
        )

    return rows


def _quiz_attribution_rows(submissions, field_name, *, default_label):
    rows = []
    for row in submissions.values(field_name).annotate(count=Count("id")):
        value = row[field_name] or ""
        rows.append(
            {
                "value": value,
                "label": value or default_label,
                "count": row["count"],
            }
        )
    rows.sort(key=lambda row: (-row["count"], row["value"] == "", row["label"]))
    return rows[:10]


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _date_range(start_date, end_date):
    current = start_date
    while current <= end_date:
        yield current
        current += timedelta(days=1)


def _width(value, maximum):
    if not maximum:
        return 0
    return round(float(value / maximum) * 100, 1)
