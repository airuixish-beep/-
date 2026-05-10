from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Count, Max, OuterRef, Q, Subquery, Sum
from django.db.models.functions import TruncDate
from django.urls import reverse
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


def build_traffic_hub_context(filters):
    quiz_context = build_quiz_dashboard_context(filters)
    traffic_summary = quiz_context["quiz_summary"]
    traffic_attribution = quiz_context["quiz_attribution"]
    traffic_sources = traffic_attribution["sources"]
    traffic_mediums = traffic_attribution["mediums"]
    traffic_campaigns = traffic_attribution["campaigns"]
    traffic_trends = get_traffic_trends(filters)
    traffic_situation = get_traffic_situation_panel(filters, traffic_summary, traffic_sources, traffic_mediums, traffic_campaigns, traffic_trends)
    recent_submissions = traffic_summary["recent_submissions"]
    top_leads = traffic_summary["lead_rows"][:5]
    traffic_attribution_matrix = get_traffic_attribution_matrix(traffic_sources, traffic_mediums, traffic_campaigns)
    traffic_intelligence = get_traffic_intelligence_panel(traffic_summary, top_leads, recent_submissions)
    traffic_result_zone = get_traffic_result_zone(traffic_summary)
    traffic_conversion_routes = get_traffic_conversion_routes()
    action_sections = get_traffic_action_sections()
    traffic_placeholders = get_marketing_placeholders()
    traffic_terminal_zone = get_traffic_terminal_zone(traffic_placeholders, action_sections)

    return {
        "traffic_summary": traffic_summary,
        "traffic_attribution": traffic_attribution,
        "traffic_sources": traffic_sources,
        "traffic_mediums": traffic_mediums,
        "traffic_campaigns": traffic_campaigns,
        "traffic_placeholders": traffic_placeholders,
        "traffic_semantics": {
            "scope": "当前流量口径基于五行测试提交记录携带的 UTM 来源，不代表全站会话、广告花费或真实流量平台报表。",
            "submissions": "按测试提交时间统计来源与线索沉淀。",
            "attribution": "按提交记录携带的 source / medium / campaign 聚合。",
            "leads": "按提交记录里的留资邮箱统计线索沉淀。",
        },
        "traffic_situation": traffic_situation,
        "traffic_command_metrics": [
            {
                "variant": "is-gmv",
                "label": "来源数",
                "value": str(len(traffic_sources)),
                "detail": "当前范围内出现过的 source 数量",
            },
            {
                "variant": "is-paid-rate",
                "label": "介质数",
                "value": str(len(traffic_mediums)),
                "detail": "当前范围内出现过的 medium 数量",
            },
            {
                "variant": "is-alerts",
                "label": "活动数",
                "value": str(len(traffic_campaigns)),
                "detail": "当前范围内出现过的 campaign 数量",
            },
            {
                "variant": "is-net",
                "label": "测试提交",
                "value": str(traffic_summary["total_submissions"]),
                "detail": f"留资 {traffic_summary['lead_count']} / 留资率 {traffic_summary['lead_rate']}%",
            },
        ],
        "traffic_overview": [
            {
                "variant": "is-cyan",
                "label": "Top Source",
                "title": traffic_sources[0]["label"] if traffic_sources else "直接访问",
                "detail": f"{traffic_sources[0]['count']} 次提交" if traffic_sources else "当前范围暂无来源数据",
            },
            {
                "variant": "is-violet",
                "label": "Top Medium",
                "title": traffic_mediums[0]["label"] if traffic_mediums else "未标记 medium",
                "detail": f"{traffic_mediums[0]['count']} 次提交" if traffic_mediums else "当前范围暂无介质数据",
            },
            {
                "variant": "is-danger",
                "label": "Top Campaign",
                "title": traffic_campaigns[0]["label"] if traffic_campaigns else "未标记 campaign",
                "detail": f"{traffic_campaigns[0]['count']} 次提交" if traffic_campaigns else "当前范围暂无活动数据",
            },
        ],
        "traffic_trends": traffic_trends,
        "traffic_attribution_matrix": traffic_attribution_matrix,
        "traffic_intelligence": traffic_intelligence,
        "traffic_result_zone": traffic_result_zone,
        "traffic_conversion_routes": traffic_conversion_routes,
        "traffic_terminal_zone": traffic_terminal_zone,
        "traffic_submission_cards": [
            {
                "label": "测试提交",
                "value": str(traffic_summary["total_submissions"]),
                "detail": "当前范围内的总测试提交数。",
            },
            {
                "label": "留资数量",
                "value": str(traffic_summary["lead_count"]),
                "detail": "已留下邮箱的线索数量。",
            },
            {
                "label": "留资率",
                "value": f"{traffic_summary['lead_rate']}%",
                "detail": "留资邮箱 / 测试提交数。",
            },
            {
                "label": "结果类型",
                "value": str(len(traffic_summary["result_counts"])),
                "detail": "当前范围内出现的主导结果数。",
            },
        ],
        "traffic_top_result_rows": [
            {
                "label": label,
                "count": count,
            }
            for label, count in list(traffic_summary["result_counts"].items())[:5]
        ],
        "traffic_recent_submissions": recent_submissions[:5],
        "traffic_top_leads": top_leads,
        "traffic_action_sections": action_sections,
    }


def get_traffic_trends(filters):
    submissions = _quiz_submissions(filters)
    submission_counts = {
        row["day"]: row["submission_count"]
        for row in submissions.annotate(day=TruncDate("created_at")).values("day").annotate(submission_count=Count("id")).order_by("day")
    }
    lead_counts = {
        row["day"]: row["lead_count"]
        for row in submissions.exclude(respondent_email="")
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(lead_count=Count("id"))
        .order_by("day")
    }

    days = list(_date_range(filters.start_date, filters.end_date))
    max_submission_count = max(submission_counts.values(), default=0)
    max_lead_count = max(lead_counts.values(), default=0)
    rows = []

    for day in days:
        submission_count = submission_counts.get(day, 0)
        lead_count = lead_counts.get(day, 0)
        rows.append(
            {
                "date": day,
                "date_label": day.strftime("%m-%d"),
                "submission_count": submission_count,
                "lead_count": lead_count,
                "submission_width": _width(submission_count, max_submission_count),
                "lead_width": _width(lead_count, max_lead_count),
            }
        )

    return {
        "rows": rows,
        "days": days,
        "max_submission_count": max_submission_count,
        "max_lead_count": max_lead_count,
    }


def get_traffic_attribution_matrix(traffic_sources, traffic_mediums, traffic_campaigns):
    lanes = [
        {
            "label": "Source",
            "headline": traffic_sources[0]["label"] if traffic_sources else "直接访问",
            "detail": f"{traffic_sources[0]['count']} 次提交" if traffic_sources else "当前范围暂无来源数据",
            "variant": "is-cyan",
            "rows": traffic_sources[:4],
            "empty_label": "当前时间范围暂无来源数据。",
        },
        {
            "label": "Medium",
            "headline": traffic_mediums[0]["label"] if traffic_mediums else "未标记 medium",
            "detail": f"{traffic_mediums[0]['count']} 次提交" if traffic_mediums else "当前范围暂无介质数据",
            "variant": "is-violet",
            "rows": traffic_mediums[:4],
            "empty_label": "当前时间范围暂无 medium 数据。",
        },
        {
            "label": "Campaign",
            "headline": traffic_campaigns[0]["label"] if traffic_campaigns else "未标记 campaign",
            "detail": f"{traffic_campaigns[0]['count']} 次提交" if traffic_campaigns else "当前范围暂无活动数据",
            "variant": "is-amber",
            "rows": traffic_campaigns[:4],
            "empty_label": "当前时间范围暂无 campaign 数据。",
        },
    ]

    return {
        "lanes": lanes,
        "headline_cards": [
            {
                "label": lane["label"],
                "value": lane["headline"],
                "detail": lane["detail"],
                "variant": lane["variant"],
            }
            for lane in lanes
        ],
    }


def get_traffic_intelligence_panel(traffic_summary, top_leads, recent_submissions):
    lead_count = traffic_summary["lead_count"]
    total_submissions = traffic_summary["total_submissions"]
    missing_email_count = max(total_submissions - lead_count, 0)
    lead_rate = traffic_summary["lead_rate"]
    result_counts = list(traffic_summary["result_counts"].items())
    top_result_label, top_result_count = result_counts[0] if result_counts else ("暂无结果", 0)

    triage_cards = [
        {
            "label": "高频留资",
            "value": str(len(top_leads)),
            "detail": "当前窗口内可优先跟进的邮箱线索",
            "variant": "is-cyan",
        },
        {
            "label": "未留资提交",
            "value": str(missing_email_count),
            "detail": f"留资率 {lead_rate}%",
            "variant": "is-danger",
        },
        {
            "label": "主导热点",
            "value": top_result_label,
            "detail": f"{top_result_count} 次主导结果",
            "variant": "is-violet",
        },
    ]

    lead_rows = [
        {
            "title": row["respondent_email"],
            "subtitle": "高频留资邮箱",
            "metric": row["count"],
        }
        for row in top_leads[:4]
    ]

    dispatch_rows = [
        {
            "title": submission.respondent_email or "未留资",
            "subtitle": f"{submission.created_at.strftime('%m-%d %H:%M')} / {submission.primary_profile.name if submission.primary_profile else '-'}",
            "metric": "线索" if submission.respondent_email else "观察",
        }
        for submission in recent_submissions[:4]
    ]

    return {
        "triage_cards": triage_cards,
        "lead_rows": lead_rows,
        "dispatch_rows": dispatch_rows,
    }


def get_traffic_result_zone(traffic_summary):
    result_rows = [
        {
            "label": label,
            "count": count,
            "detail": "主导结果热区",
            "variant": variant,
        }
        for (label, count), variant in zip(
            list(traffic_summary["result_counts"].items())[:5],
            ["is-cyan", "is-violet", "is-danger", "is-cyan", "is-violet"],
        )
    ]

    return {
        "summary_cards": [
            {
                "label": "测试提交",
                "value": str(traffic_summary["total_submissions"]),
                "detail": "当前范围内的总测试提交数。",
                "variant": "is-cyan",
            },
            {
                "label": "留资数量",
                "value": str(traffic_summary["lead_count"]),
                "detail": "已留下邮箱的线索数量。",
                "variant": "is-violet",
            },
            {
                "label": "留资率",
                "value": f"{traffic_summary['lead_rate']}%",
                "detail": "留资邮箱 / 测试提交数。",
                "variant": "is-danger",
            },
            {
                "label": "结果类型",
                "value": str(len(traffic_summary["result_counts"])),
                "detail": "当前范围内出现的主导结果数。",
                "variant": "is-cyan",
            },
        ],
        "result_rows": result_rows,
    }


def get_traffic_conversion_routes():
    return {
        "title": "转化分流",
        "description": "把这波流量直接分流到提交后台和客户协同面，继续处理线索沉淀。",
        "routes": [
            {
                "label": "全部提交",
                "detail": "当前时间范围的所有测试提交。",
                "variant": "is-cyan",
            },
            {
                "label": "有留资提交",
                "detail": "仅查看留下邮箱的线索。",
                "variant": "is-violet",
            },
            {
                "label": "未留资提交",
                "detail": "定位只完成测试但没有沉淀邮箱的记录。",
                "variant": "is-danger",
            },
        ],
    }


def get_traffic_action_sections():
    return [
        {
            "title": "继续分析",
            "description": "先看流量归因，再切换到经营分析或五行测试继续深入判断。",
            "links": [
                {"label": "经营分析", "url": reverse("analytics_dashboard:index"), "variant": "is-cyan"},
                {"label": "五行测试统计", "url": reverse("analytics_dashboard:quiz"), "variant": "is-violet"},
            ],
        },
        {
            "title": "继续执行",
            "description": "进入提交后台和客户工作台，继续处理留资、线索跟进和转化协同。",
            "links": [
                {"label": "提交后台", "url": reverse("admin:pages_fiveelementsubmission_changelist"), "variant": "is-cyan"},
                {"label": "客户工作台", "url": reverse("backoffice_customers"), "variant": "is-danger"},
            ],
        },
    ]


def get_traffic_terminal_zone(placeholders, action_sections):
    action_cards = []
    for section in action_sections:
        for link in section["links"]:
            action_cards.append(
                {
                    "section_title": section["title"],
                    "section_description": section["description"],
                    "label": link["label"],
                    "url": link["url"],
                    "variant": link.get("variant", "is-cyan"),
                }
            )

    roadmap_cards = [
        {
            "title": item["title"],
            "description": item["description"],
            "variant": variant,
        }
        for item, variant in zip(placeholders, ["is-cyan", "is-violet", "is-danger", "is-cyan"])
    ]

    return {
        "title": "终端行动区",
        "description": "上层先做当前线索分流，下层标记待接入的数据能力，保持观察与执行在同一块甲板上。",
        "action_cards": action_cards,
        "roadmap_cards": roadmap_cards,
    }


def get_traffic_situation_panel(filters, traffic_summary, traffic_sources, traffic_mediums, traffic_campaigns, traffic_trends):
    rows = traffic_trends["rows"]
    total_submissions = traffic_summary["total_submissions"]
    lead_count = traffic_summary["lead_count"]
    lead_rate = traffic_summary["lead_rate"]
    source_count = len(traffic_sources)
    medium_count = len(traffic_mediums)
    campaign_count = len(traffic_campaigns)
    max_submission_count = traffic_trends["max_submission_count"]
    max_lead_count = traffic_trends["max_lead_count"]

    chart_width = 760
    chart_height = 260
    chart_padding_x = 44
    chart_padding_top = 26
    chart_padding_bottom = 38
    plot_width = chart_width - (chart_padding_x * 2)
    plot_height = chart_height - chart_padding_top - chart_padding_bottom
    point_count = max(len(rows), 1)
    step_x = plot_width / max(point_count - 1, 1)

    submission_line_points = []
    lead_line_points = []
    chart_points = []

    for index, row in enumerate(rows):
        x = chart_padding_x + (index * step_x)
        submission_ratio = 0 if max_submission_count == 0 else row["submission_count"] / max_submission_count
        lead_ratio = 0 if max_lead_count == 0 else row["lead_count"] / max_lead_count
        submission_y = chart_padding_top + (plot_height * (1 - submission_ratio))
        lead_y = chart_padding_top + (plot_height * (1 - lead_ratio))
        chart_points.append(
            {
                **row,
                "x": round(x, 1),
                "submission_y": round(submission_y, 1),
                "lead_y": round(lead_y, 1),
            }
        )
        submission_line_points.append((x, submission_y))
        lead_line_points.append((x, lead_y))

    peak_submission_row = max(rows, key=lambda row: row["submission_count"], default=None)
    peak_lead_row = max(rows, key=lambda row: row["lead_count"], default=None)
    latest_row = rows[-1] if rows else None

    pressure_bars = [
        {
            "label": "提交压力",
            "count": total_submissions,
            "hint": "当前范围总提交",
            "width": _width(total_submissions, max(total_submissions, lead_count, 1)),
            "variant": "is-cyan",
        },
        {
            "label": "留资沉淀",
            "count": lead_count,
            "hint": f"留资率 {lead_rate}%",
            "width": _width(lead_count, max(total_submissions, lead_count, 1)),
            "variant": "is-violet",
        },
        {
            "label": "来源分散度",
            "count": source_count,
            "hint": f"介质 {medium_count} / 活动 {campaign_count}",
            "width": _width(source_count, max(source_count, medium_count, campaign_count, 1)),
            "variant": "is-amber",
        },
    ]

    intel_cards = [
        {
            "label": "峰值提交日",
            "value": peak_submission_row["date_label"] if peak_submission_row else "--",
            "detail": f"{peak_submission_row['submission_count']} 次提交" if peak_submission_row else "当前范围暂无提交节奏",
        },
        {
            "label": "峰值留资日",
            "value": peak_lead_row["date_label"] if peak_lead_row else "--",
            "detail": f"{peak_lead_row['lead_count']} 个留资" if peak_lead_row else "当前范围暂无留资沉淀",
        },
        {
            "label": "当前窗口",
            "value": latest_row["date_label"] if latest_row else "--",
            "detail": (
                f"提交 {latest_row['submission_count']} / 留资 {latest_row['lead_count']}"
                if latest_row
                else "当前范围暂无最新窗口数据"
            ),
        },
    ]

    axis_labels = []
    if rows:
        axis_indexes = sorted({0, len(rows) // 2, len(rows) - 1})
        axis_labels = [{"x": chart_points[index]["x"], "label": rows[index]["date_label"]} for index in axis_indexes]

    return {
        "title": "提交流量态势主屏",
        "subtitle": "把提交节奏、留资沉淀和来源分散度压到同一块主屏里，先判断当前这波流量是否值得继续追踪。",
        "window_label": f"{filters.label} · {filters.currency_label}",
        "summary_metrics": [
            {"label": "测试提交", "value": str(total_submissions), "detail": "当前观察窗口总提交"},
            {"label": "留资沉淀", "value": str(lead_count), "detail": f"留资率 {lead_rate}%"},
            {"label": "来源分层", "value": str(source_count), "detail": f"介质 {medium_count} / 活动 {campaign_count}"},
        ],
        "svg": {
            "width": chart_width,
            "height": chart_height,
            "plot_bottom": chart_padding_top + plot_height,
            "submission_path": _build_svg_path(submission_line_points),
            "lead_path": _build_svg_path(lead_line_points),
            "points": chart_points,
            "axis_labels": axis_labels,
        },
        "overlay": {
            "peak_label": (
                f"峰值提交 {peak_submission_row['submission_count']} / {peak_submission_row['date_label']}"
                if peak_submission_row
                else "当前范围暂无提交峰值"
            ),
            "current_label": (
                f"当前窗口 提交 {latest_row['submission_count']} · 留资 {latest_row['lead_count']}"
                if latest_row
                else "当前窗口暂无数据"
            ),
        },
        "pressure_bars": pressure_bars,
        "intel_cards": intel_cards,
        "legend": [
            {"label": "提交主线", "variant": "is-cyan"},
            {"label": "留资副线", "variant": "is-violet"},
            {"label": "右侧态势条", "variant": "is-amber"},
        ],
    }


def get_kpis(filters):
    orders = _filter_by_date(Order.objects.filter(**_currency_filter("currency", filters.currency)), "created_at", filters)
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
        for row in _filter_by_date(Order.objects.filter(**_currency_filter("currency", filters.currency)), "created_at", filters)
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
    orders = _filter_by_date(Order.objects.filter(**_currency_filter("currency", filters.currency)), "created_at", filters)
    payments = _filter_by_date(Payment.objects.filter(**_currency_filter("currency", filters.currency)), "created_at", filters)

    return {
        "orders": _status_rows(orders, "status", Order.Status.choices),
        "payments": _status_rows(payments, "status", Payment.Status.choices),
        "fulfillment": _status_rows(orders, "fulfillment_status", Order.FulfillmentStatus.choices),
    }


def get_payment_summary(filters):
    payments = _filter_by_date(Payment.objects.filter(**_currency_filter("currency", filters.currency)), "created_at", filters)
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
            **_currency_filter("order__currency", filters.currency),
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
                **_currency_filter("currency", filters.currency),
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
            **_currency_filter("currency", filters.currency),
            payment_status=Order.PaymentStatus.PAID,
            paid_at__isnull=False,
        ),
        "paid_at",
        filters,
    )


def _paid_transactions(filters):
    return _filter_by_date(
        Transaction.objects.filter(
            **_currency_filter("currency", filters.currency),
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
        Refund.objects.filter(status=Refund.Status.SUCCEEDED, **_currency_filter("currency", filters.currency)),
        "created_at",
        filters,
    )


def _ledger_entries(filters):
    return _filter_by_date(
        LedgerEntry.objects.filter(**_currency_filter("currency", filters.currency)),
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


def _currency_filter(field_name, currency):
    if currency == "all":
        return {}
    return {field_name: currency.upper()}


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


def _build_svg_path(points):
    if not points:
        return ""
    start_x, start_y = points[0]
    segments = [f"M {start_x:.1f} {start_y:.1f}"]
    for x, y in points[1:]:
        segments.append(f"L {x:.1f} {y:.1f}")
    return " ".join(segments)


def _width(value, maximum):
    if not maximum:
        return 0
    return round(float(value / maximum) * 100, 1)
