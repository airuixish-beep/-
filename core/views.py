from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.db import connection
from django.db.models import Count
from django.http import JsonResponse
from django.template.response import TemplateResponse
from django.urls import reverse

from analytics_dashboard.services import get_geo_summary, get_kpis, get_order_trends, get_shipping_summary, get_status_breakdowns
from after_sales.models import AfterSalesCase
from core.models import SiteConfig
from shipping.models import Shipment
from support_chat.models import ChatOfflineMessage, ChatSession
from trade_cockpit.services import CURRENCY_OPTIONS, RANGE_OPTIONS, TradeCockpitService, parse_trade_cockpit_filters
from transactions.models import Refund


def health_live(request):
    return JsonResponse({"ok": True, "service": "live"})


def health_ready(request):
    checks = {}

    try:
        connection.ensure_connection()
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        checks["database"] = "error"
    else:
        checks["database"] = "ok"

    cache_backend = settings.CACHES["default"]["BACKEND"]
    if cache_backend == "django.core.cache.backends.dummy.DummyCache":
        checks["cache"] = "skipped"
    else:
        try:
            cache.set("healthz:cache", "ok", 5)
            if cache.get("healthz:cache") != "ok":
                raise RuntimeError
            cache.delete("healthz:cache")
        except Exception:
            checks["cache"] = "error"
        else:
            checks["cache"] = "ok"

    if settings.CHAT_REALTIME_ENABLED:
        try:
            channel_layer = get_channel_layer()
            if channel_layer is None:
                raise RuntimeError
            channel_name = async_to_sync(channel_layer.new_channel)("healthz.")
            async_to_sync(channel_layer.send)(channel_name, {"type": "health.message", "value": "ok"})
            message = async_to_sync(channel_layer.receive)(channel_name)
            if message.get("value") != "ok":
                raise RuntimeError
        except Exception:
            checks["realtime"] = "error"
        else:
            checks["realtime"] = "ok"
    else:
        checks["realtime"] = "disabled"

    status = 200 if all(value in {"ok", "skipped", "disabled"} for value in checks.values()) else 503
    return JsonResponse({"ok": status == 200, "service": "ready", "checks": checks}, status=status)


def get_admin_nav_groups():
    return [
        {
            "title": "总览",
            "items": [
                {
                    "key": "home",
                    "label": "后台首页",
                    "description": "后台首页与全局运营入口",
                    "url": reverse("admin:index"),
                },
                {
                    "key": "trade_cockpit",
                    "label": "战情驾驶舱",
                    "description": "订单、支付、账务、风控与异常指挥舱",
                    "url": reverse("trade_cockpit_dashboard"),
                },
                {
                    "key": "ai_command",
                    "label": "AI 指挥",
                    "description": "AI 参谋建议、风险优先级与执行分流入口",
                    "url": reverse("ai_command_center"),
                },
                {
                    "key": "content_os",
                    "label": "内容中枢",
                    "description": "内容生产、素材资产、页面编排与复用调度面",
                    "url": reverse("content_os"),
                },
                {
                    "key": "analytics",
                    "label": "经营分析",
                    "description": "订单、支付、发货与地区经营指标",
                    "url": reverse("analytics_dashboard:index"),
                },
                {
                    "key": "traffic",
                    "label": "流量中枢",
                    "description": "来源、介质、活动与线索沉淀观察面",
                    "url": reverse("analytics_dashboard:traffic"),
                },
                {
                    "key": "quiz",
                    "label": "五行测试",
                    "description": "测试提交、结果分布与留资表现",
                    "url": reverse("analytics_dashboard:quiz"),
                },
                {
                    "key": "support",
                    "label": "客服控制台",
                    "description": "在线客服会话、草稿与关闭处理",
                    "url": reverse("support_chat_console"),
                },
            ],
        },
        {
            "title": "运营模块",
            "items": [
                {
                    "key": "orders",
                    "label": "订单",
                    "description": "订单主列表、履约负载与协同处理入口",
                    "url": reverse("order_console"),
                },
                {
                    "key": "payments",
                    "label": "支付",
                    "description": "支付记录、状态流转与渠道回调观察",
                    "url": reverse("payment_console"),
                },
                {
                    "key": "shipping",
                    "label": "发货",
                    "description": "运单状态、异常件与履约跟踪",
                    "url": reverse("admin:shipping_shipment_changelist"),
                },
                {
                    "key": "after_sales",
                    "label": "售后",
                    "description": "售后单、补发与退款协同",
                    "url": reverse("admin:after_sales_aftersalescase_changelist"),
                },
                {
                    "key": "refunds",
                    "label": "退款",
                    "description": "退款申请、提交与结果追踪",
                    "url": reverse("admin:transactions_refund_changelist"),
                },
                {
                    "key": "products",
                    "label": "商品",
                    "description": "商品资料、库存与上下架管理",
                    "url": reverse("product_console"),
                },
            ],
        },
        {
            "title": "工作台",
            "items": [
                {
                    "key": "customers",
                    "label": "客户",
                    "description": "客户线索、客服会话与测试留资聚合",
                    "url": reverse("backoffice_customers"),
                },
                {
                    "key": "settings",
                    "label": "设置",
                    "description": "站点配置与后台常用设置入口",
                    "url": reverse("backoffice_settings"),
                },
            ],
        },
    ]


def build_admin_shell_context(
    request,
    *,
    title,
    subtitle="",
    active_nav="home",
    kicker="XUANOR Command Center",
    breadcrumbs=None,
    topbar_actions=None,
    sidebar_note="以交易、履约、客服与分析统一调度为核心，构建后台战情中控台。",
):
    return {
        **admin.site.each_context(request),
        "title": title,
        "subtitle": subtitle,
        "x_admin_kicker": kicker,
        "x_admin_active_nav": active_nav,
        "x_admin_nav_groups": get_admin_nav_groups(),
        "x_admin_sidebar_note": sidebar_note,
        "x_admin_breadcrumbs": breadcrumbs
        or [
            {"label": "后台首页", "url": reverse("admin:index")},
            {"label": title},
        ],
        "x_admin_topbar_actions": topbar_actions or [],
    }


def customers_view(request):
    context = {
        **build_admin_shell_context(
            request,
            title="客户工作台",
            subtitle="把订单客户、在线客服会话与五行测试留资集中到一个客户工作台入口。",
            active_nav="customers",
            kicker="Customer Command Desk",
            breadcrumbs=[
                {"label": "后台首页", "url": reverse("admin:index")},
                {"label": "客户工作台"},
            ],
            topbar_actions=[
                {"label": "在线客服控制台", "url": reverse("support_chat_console"), "primary": True},
                {"label": "五行测试提交", "url": reverse("admin:pages_fiveelementsubmission_changelist")},
            ],
        ),
        "customer_sections": [
            {
                "title": "订单客户",
                "description": "从订单列表查看客户信息、付款状态、收货地址与履约进度。",
                "links": [
                    {"label": "订单管理", "url": reverse("admin:orders_order_changelist")},
                    {"label": "退款管理", "url": reverse("admin:transactions_refund_changelist")},
                    {"label": "售后管理", "url": reverse("admin:after_sales_aftersalescase_changelist")},
                ],
            },
            {
                "title": "客服会话",
                "description": "集中处理访客咨询、离线留言、订单问题与售后沟通。",
                "links": [
                    {"label": "进入客服控制台", "url": reverse("support_chat_console")},
                ],
            },
            {
                "title": "测试留资",
                "description": "查看五行测试提交、留资邮箱、来源 UTM 与结果分布。",
                "links": [
                    {"label": "五行测试统计", "url": reverse("analytics_dashboard:quiz")},
                    {"label": "提交后台", "url": reverse("admin:pages_fiveelementsubmission_changelist")},
                ],
            },
        ],
    }
    return TemplateResponse(request, "admin/customers.html", context)


def settings_view(request):
    context = {
        **build_admin_shell_context(
            request,
            title="设置中枢",
            subtitle="统一收纳站点内容设置、商品结构和后台常用配置入口，不直接暴露底层环境变量。",
            active_nav="settings",
            kicker="设置调度中枢",
            breadcrumbs=[
                {"label": "后台首页", "url": reverse("admin:index")},
                {"label": "设置中枢"},
            ],
            topbar_actions=[
                {"label": "站点配置", "url": reverse("admin:core_siteconfig_changelist"), "primary": True},
                {"label": "商品类目", "url": reverse("admin:products_category_changelist")},
            ],
        ),
        "setting_sections": [
            {
                "title": "站点与品牌",
                "description": "维护站点基础信息、联系邮箱和后台品牌内容。",
                "links": [
                    {"label": "站点配置", "url": reverse("admin:core_siteconfig_changelist")},
                ],
            },
            {
                "title": "商品结构",
                "description": "维护商品管理、商品类目、商品变体与库存记录。",
                "links": [
                    {"label": "商品管理", "url": reverse("admin:products_product_changelist")},
                    {"label": "商品类目", "url": reverse("admin:products_category_changelist")},
                    {"label": "商品变体", "url": reverse("admin:products_productvariant_changelist")},
                ],
            },
            {
                "title": "履约与交易",
                "description": "查看发货、退款、账务与风控配置对应的运营后台入口。",
                "links": [
                    {"label": "发货管理", "url": reverse("admin:shipping_shipment_changelist")},
                    {"label": "退款管理", "url": reverse("admin:transactions_refund_changelist")},
                    {"label": "风控观察", "url": reverse("admin:transactions_riskassessment_changelist")},
                ],
            },
        ],
    }
    return TemplateResponse(request, "admin/settings.html", context)


def _build_content_os_context_data():
    from pages.models import FiveElementProfile, FiveElementQuestion, FiveElementQuiz, FiveElementSubmission
    from products.models import Category, Product, ProductImage, ProductVariant

    site_config = SiteConfig.objects.first()
    quiz_count = FiveElementQuiz.objects.count()
    active_quiz_count = FiveElementQuiz.objects.filter(is_active=True).count()
    question_count = FiveElementQuestion.objects.count()
    profile_count = FiveElementProfile.objects.count()
    submission_count = FiveElementSubmission.objects.count()
    lead_count = FiveElementSubmission.objects.exclude(respondent_email="").count()
    source_count = FiveElementSubmission.objects.exclude(utm_source="").values("utm_source").distinct().count()
    campaign_count = FiveElementSubmission.objects.exclude(utm_campaign="").values("utm_campaign").distinct().count()
    lead_rate = round((lead_count / submission_count) * 100, 1) if submission_count else 0.0
    hero_asset_count = Product.objects.filter(hero_image__isnull=False).exclude(hero_image="").count()
    gallery_asset_count = ProductImage.objects.count()
    variant_asset_count = ProductVariant.objects.filter(image__isnull=False).exclude(image="").count()
    seo_ready_count = Product.objects.exclude(seo_title="").exclude(seo_description="").count()
    featured_product_count = Product.objects.filter(is_featured=True).count()
    category_count = Category.objects.count()
    branding_asset_count = int(bool(site_config and site_config.logo)) + int(bool(site_config and site_config.favicon))
    top_source = (
        FiveElementSubmission.objects.exclude(utm_source="")
        .values("utm_source")
        .annotate(total=Count("id"))
        .order_by("-total", "utm_source")
        .first()
    )
    top_result = (
        FiveElementSubmission.objects.exclude(primary_profile__isnull=True)
        .values("primary_profile__name")
        .annotate(total=Count("id"))
        .order_by("-total", "primary_profile__name")
        .first()
    )
    asset_total = hero_asset_count + gallery_asset_count + variant_asset_count + branding_asset_count
    top_source_label = top_source["utm_source"] if top_source else "暂无来源归因"
    top_source_count = top_source["total"] if top_source else 0
    top_result_label = top_result["primary_profile__name"] if top_result else "暂无结果沉淀"
    top_result_count = top_result["total"] if top_result else 0

    return {
        "content_os_metrics": [
            {
                "label": "内容生产",
                "value": str(active_quiz_count),
                "detail": f"启用测试 {active_quiz_count} / 题目 {question_count} / 结果画像 {profile_count}",
                "variant": "is-gmv",
            },
            {
                "label": "线索沉淀",
                "value": str(submission_count),
                "detail": f"留资 {lead_count} / 留资率 {lead_rate}% / 来源 {source_count}",
                "variant": "is-paid-rate",
            },
            {
                "label": "素材资产",
                "value": str(asset_total),
                "detail": f"主图 {hero_asset_count} / 图库 {gallery_asset_count} / SKU 图 {variant_asset_count}",
                "variant": "is-net",
            },
            {
                "label": "页面配置",
                "value": "1" if site_config else "0",
                "detail": f"品牌资源 {branding_asset_count} / SEO 完整商品 {seo_ready_count} / 类目 {category_count}",
                "variant": "is-alerts",
            },
        ],
        "content_os_overview": [
            {
                "variant": "is-cyan",
                "label": "Production",
                "title": f"启用内容 {active_quiz_count}",
                "detail": f"总测试 {quiz_count} / 问题 {question_count} / 结果 {profile_count}",
            },
            {
                "variant": "is-violet",
                "label": "Distribution",
                "title": top_source_label,
                "detail": f"高频来源 {top_source_count} 次 / 活动 {campaign_count} 个",
            },
            {
                "variant": "is-danger",
                "label": "Reuse",
                "title": top_result_label,
                "detail": f"高频结果 {top_result_count} 次 / 精选商品 {featured_product_count} 个",
            },
        ],
        "content_os_signals": [
            {
                "title": "当前内容生产面",
                "detail": f"AI 指挥 + 五行测试对象已可协同，当前启用测试 {active_quiz_count} 个。",
            },
            {
                "title": "当前素材面",
                "detail": f"商品主图、图库、SKU 图与品牌资源共 {asset_total} 个素材入口可被收口。",
            },
            {
                "title": "当前分发与复用面",
                "detail": f"来源 {source_count} 个 / 留资 {lead_count} 个，可先用流量与客户后台承接复用判断。",
            },
        ],
        "content_os_sections": [
            {
                "title": "内容生产（AI / 人工）",
                "stage": "当前可用",
                "description": "先用 AI 指挥生成方向，再回到五行测试、题目和结果对象做人工编辑与上线。",
                "summary": f"AI 指挥、测试 {quiz_count} 个、题目 {question_count} 道、结果画像 {profile_count} 个。",
                "links": [
                    {"label": "AI 指挥", "url": reverse("ai_command_center")},
                    {"label": "五行测试", "url": reverse("admin:pages_fiveelementquiz_changelist")},
                    {"label": "测试题目", "url": reverse("admin:pages_fiveelementquestion_changelist")},
                    {"label": "结果画像", "url": reverse("admin:pages_fiveelementprofile_changelist")},
                ],
            },
            {
                "title": "素材资产库（DAM）",
                "stage": "先收口现有素材",
                "description": "先把商品主图、SKU 图和品牌资源视作当前素材面，再决定是否升级为统一 DAM。",
                "summary": f"主图 {hero_asset_count} / 图库 {gallery_asset_count} / SKU 图 {variant_asset_count} / 品牌资源 {branding_asset_count}。",
                "links": [
                    {"label": "商品控制台", "url": reverse("product_console")},
                    {"label": "商品列表", "url": reverse("admin:products_product_changelist")},
                    {"label": "商品 SKU", "url": reverse("admin:products_productvariant_changelist")},
                    {"label": "站点配置", "url": reverse("admin:core_siteconfig_changelist")},
                ],
            },
            {
                "title": "页面管理（CMS）",
                "stage": "以现有对象代管",
                "description": "当前先用站点配置、五行测试内容和商品结构承担页面编排，不伪造一套新 CMS。",
                "summary": f"站点配置 {'已就位' if site_config else '待创建'} / 类目 {category_count} / SEO 完整商品 {seo_ready_count}。",
                "links": [
                    {"label": "站点配置", "url": reverse("admin:core_siteconfig_changelist")},
                    {"label": "商品类目", "url": reverse("admin:products_category_changelist")},
                    {"label": "商品列表", "url": reverse("admin:products_product_changelist")},
                    {"label": "五行测试", "url": reverse("admin:pages_fiveelementquiz_changelist")},
                ],
            },
            {
                "title": "渠道分发（广告 / 社媒）",
                "stage": "基于真实归因",
                "description": "先用五行测试提交携带的 UTM 归因做渠道观察与执行分流，不虚构广告平台能力。",
                "summary": f"来源 {source_count} / 活动 {campaign_count} / 提交 {submission_count} / 留资 {lead_count}。",
                "links": [
                    {"label": "流量中枢", "url": reverse("analytics_dashboard:traffic")},
                    {"label": "五行测试统计", "url": reverse("analytics_dashboard:quiz")},
                    {"label": "提交后台", "url": reverse("admin:pages_fiveelementsubmission_changelist")},
                    {"label": "客户工作台", "url": reverse("backoffice_customers")},
                ],
            },
            {
                "title": "数据分析（CTR / ROI）",
                "stage": "先用现有分析面",
                "description": "当前可落地的是经营分析、流量中枢和五行测试统计，后续再补 CTR / ROI 的真实投放模型。",
                "summary": f"留资率 {lead_rate}% / 高频来源 {top_source_label} / 高频结果 {top_result_label}。",
                "links": [
                    {"label": "经营分析", "url": reverse("analytics_dashboard:index")},
                    {"label": "流量中枢", "url": reverse("analytics_dashboard:traffic")},
                    {"label": "五行测试统计", "url": reverse("analytics_dashboard:quiz")},
                    {"label": "战情驾驶舱", "url": reverse("trade_cockpit_dashboard")},
                ],
            },
            {
                "title": "爆款资产沉淀（复用系统）",
                "stage": "第一阶段先做复盘入口",
                "description": "先根据高频来源、高频结果和精选商品做复盘，再决定是否沉淀成可复用打法对象。",
                "summary": f"高频来源 {top_source_label} / 高频结果 {top_result_label} / 精选商品 {featured_product_count}。",
                "links": [
                    {"label": "流量中枢", "url": reverse("analytics_dashboard:traffic")},
                    {"label": "客户工作台", "url": reverse("backoffice_customers")},
                    {"label": "商品控制台", "url": reverse("product_console")},
                    {"label": "AI 指挥", "url": reverse("ai_command_center")},
                ],
            },
        ],
        "content_os_roadmap": [
            {
                "title": "统一 ContentAsset 对象",
                "description": "把品牌资源、商品图、SKU 图和页面素材收口到统一素材实体。",
                "variant": "is-cyan",
            },
            {
                "title": "ManagedPage 页面模型",
                "description": "把站点配置与专题页编排升级成真正可管理的 CMS 页面对象。",
                "variant": "is-violet",
            },
            {
                "title": "DistributionRecord 投放记录",
                "description": "把渠道分发、素材版本、CTR、ROI 和复盘动作接进真实投放链路。",
                "variant": "is-danger",
            },
        ],
    }



def content_os_view(request):
    context = {
        **build_admin_shell_context(
            request,
            title="内容中枢",
            subtitle="把内容生产、素材资产、页面管理、渠道分发、数据分析和爆款复用先收口到一个统一后台入口。",
            active_nav="content_os",
            kicker="Content Operating System",
            breadcrumbs=[
                {"label": "后台首页", "url": reverse("admin:index")},
                {"label": "内容中枢"},
            ],
            topbar_actions=[
                {"label": "AI 指挥", "url": reverse("ai_command_center")},
                {"label": "流量中枢", "url": reverse("analytics_dashboard:traffic")},
                {"label": "站点配置", "url": reverse("admin:core_siteconfig_changelist")},
                {"label": "商品控制台", "url": reverse("product_console"), "primary": True},
            ],
            sidebar_note="以内容生产、素材资产、页面编排、渠道分发与数据复盘统一调度为核心，构建 Content OS 中枢。",
        ),
        **_build_content_os_context_data(),
    }
    return TemplateResponse(request, "admin/content_os.html", context)



def ai_command_view(request):
    filters = parse_trade_cockpit_filters(request.GET)
    summary = TradeCockpitService.get_dashboard_summary(filters)
    risk_summary = summary["risk_summary"]
    funds_flow = summary["funds_flow"]
    context = {
        **build_admin_shell_context(
            request,
            title="🦞 AI 指挥中心",
            subtitle=f"{filters.label} · {filters.currency_label}。让 AI 参谋先给出风险、支付与退款的优先处置序列。",
            active_nav="ai_command",
            kicker="AI Command Center",
            breadcrumbs=[
                {"label": "后台首页", "url": reverse("admin:index")},
                {"label": "🦞 AI 指挥中心"},
            ],
            topbar_actions=[
                {"label": "战情驾驶舱", "url": reverse("trade_cockpit_dashboard")},
                {"label": "支付控制台", "url": reverse("payment_console")},
                {"label": "风控", "url": reverse("admin:transactions_riskassessment_changelist"), "primary": True},
            ],
        ),
        "filters": filters,
        "range_options": RANGE_OPTIONS,
        "currency_options": CURRENCY_OPTIONS,
        "copilot_suggestions": summary["copilot_suggestions"],
        "alerts": summary["alerts"],
        "risk_summary": risk_summary,
        "funds_flow": funds_flow,
        "ai_command_metrics": [
            {
                "variant": "is-alerts",
                "label": "风险待处置",
                "value": str(risk_summary["review_count"] + risk_summary["block_count"]),
                "detail": f"Review {risk_summary['review_count']} / Block {risk_summary['block_count']}",
            },
            {
                "variant": "is-paid-rate",
                "label": "支付待观察",
                "value": str(summary["payment_summary"]["failed_count"] + summary["payment_summary"]["requires_action_count"]),
                "detail": f"失败 {summary['payment_summary']['failed_count']} / 待补操作 {summary['payment_summary']['requires_action_count']}",
            },
            {
                "variant": "is-net",
                "label": "退款与手续费",
                "value": f"{funds_flow['refund_amount']}",
                "detail": f"手续费 {funds_flow['fee_amount']}",
            },
        ],
        "ai_command_actions": [
            {"label": "风险分析", "url": reverse("admin:transactions_riskassessment_changelist")},
            {"label": "支付链路", "url": reverse("admin:payments_payment_changelist")},
            {"label": "退款处置", "url": reverse("admin:transactions_refund_changelist")},
            {"label": "账务流水", "url": reverse("admin:transactions_ledgertransaction_changelist")},
        ],
    }
    return TemplateResponse(request, "admin/ai_command.html", context)


def product_console_view(request):
    from .admin import _build_homepage_product_module

    product_module = _build_homepage_product_module()
    operations_sections = [
        {
            "title": "商品主档",
            "description": "进入商品主档维护商品资料、上下架状态、推荐位与售卖信息。",
            "links": [
                {"label": "商品列表", "url": reverse("admin:products_product_changelist")},
                {"label": "新增商品", "url": reverse("admin:products_product_add")},
            ],
        },
        {
            "title": "SKU 与库存",
            "description": "查看变体价格、库存数量、安全库存阈值与库存流水。",
            "links": [
                {"label": "商品 SKU", "url": reverse("admin:products_productvariant_changelist")},
                {"label": "库存流水", "url": reverse("admin:products_inventoryrecord_changelist")},
            ],
        },
        {
            "title": "类目结构",
            "description": "维护类目层级、启用状态与类目热区对应的商品结构。",
            "links": [
                {"label": "商品类目", "url": reverse("admin:products_category_changelist")},
                {"label": "新增商品类目", "url": reverse("admin:products_category_add")},
            ],
        },
    ]
    context = {
        **build_admin_shell_context(
            request,
            title="商品控制台",
            subtitle="统一查看商品主档、SKU、类目结构、可售状态与库存波动，再分流到原生商品后台执行。",
            active_nav="products",
            kicker="Product Mission Control",
            breadcrumbs=[
                {"label": "后台首页", "url": reverse("admin:index")},
                {"label": "商品控制台"},
            ],
            topbar_actions=[
                {"label": "商品列表", "url": reverse("admin:products_product_changelist")},
                {"label": "新增商品", "url": reverse("admin:products_product_add"), "primary": True},
                {"label": "商品变体", "url": reverse("admin:products_productvariant_changelist")},
                {"label": "库存流水", "url": reverse("admin:products_inventoryrecord_changelist")},
                {"label": "商品类目", "url": reverse("admin:products_category_changelist")},
            ],
        ),
        "product_console_metrics": product_module["command_metrics"],
        "product_warning_items": product_module["warning_items"],
        "product_focus_cards": product_module["focus_cards"],
        "product_operations_sections": operations_sections,
    }
    return TemplateResponse(request, "admin/products_console.html", context)


def order_console_view(request):
    filters = parse_trade_cockpit_filters(request.GET)
    summary = TradeCockpitService.get_dashboard_summary(filters)
    kpis = get_kpis(filters)
    order_trends = get_order_trends(filters)
    status_breakdowns = get_status_breakdowns(filters)
    shipping_summary = get_shipping_summary(filters)
    geo_summary = get_geo_summary(filters)

    currency = filters.currency.upper()
    order_filter = {} if filters.currency == "all" else {"order__currency": currency}
    refund_filter = {} if filters.currency == "all" else {"currency": currency}

    open_cases_queryset = AfterSalesCase.objects.filter(status__in=[AfterSalesCase.Status.OPEN, AfterSalesCase.Status.PROCESSING], **order_filter)
    open_cases = open_cases_queryset.count()
    active_sessions = ChatSession.objects.filter(status__in=[ChatSession.Status.OPEN, ChatSession.Status.WAITING_OPERATOR]).count()
    new_offline_messages = ChatOfflineMessage.objects.filter(status=ChatOfflineMessage.Status.NEW).count()
    pending_refunds = Refund.objects.filter(status__in=[Refund.Status.REQUESTED, Refund.Status.PROCESSING], **refund_filter)
    pending_shipments = Shipment.objects.filter(
        status__in=[Shipment.Status.PENDING, Shipment.Status.LABEL_PURCHASED, Shipment.Status.IN_TRANSIT], **order_filter
    )
    recent_orders = summary["recent_orders"]
    exception_shipments = shipping_summary["exception_shipments"]
    geo_countries = geo_summary["countries"]
    geo_cities = geo_summary["cities"]
    attention_orders = [
        order
        for order in recent_orders
        if order.payment_status != order.PaymentStatus.PAID or order.fulfillment_status != order.FulfillmentStatus.DELIVERED
    ]
    order_console_metrics = [
        {
            "variant": "is-gmv",
            "label": "订单总量",
            "value": str(kpis["order_count"]),
            "detail": f"已支付 {kpis['paid_order_count']} / 转化率 {kpis['payment_conversion_rate']}%",
        },
        {
            "variant": "is-paid-rate",
            "label": "待履约",
            "value": str(pending_shipments.count()),
            "detail": f"发货中 {kpis['shipping_in_progress_count']} / 已送达 {kpis['delivered_order_count']}",
        },
        {
            "variant": "is-alerts",
            "label": "退款 / 售后压力",
            "value": str(pending_refunds.count() + open_cases),
            "detail": f"退款 {pending_refunds.count()} / 售后 {open_cases}",
        },
        {
            "variant": "is-net",
            "label": "客户待协同",
            "value": str(active_sessions + new_offline_messages),
            "detail": f"会话 {active_sessions} / 离线留言 {new_offline_messages}",
        },
    ]
    order_operations_sections = [
        {
            "title": "订单执行面",
            "description": "进入订单主列表，处理支付状态、批量推进履约与关闭异常未支付订单。",
            "links": [
                {"label": "订单列表", "url": reverse("admin:orders_order_changelist")},
                {"label": "新增订单", "url": reverse("admin:orders_order_add")},
            ],
        },
        {
            "title": "履约与售后",
            "description": "查看发货状态、异常件、退款申请与售后协同单。",
            "links": [
                {"label": "发货管理", "url": reverse("admin:shipping_shipment_changelist")},
                {"label": "退款管理", "url": reverse("admin:transactions_refund_changelist")},
                {"label": "售后管理", "url": reverse("admin:after_sales_aftersalescase_changelist")},
            ],
        },
        {
            "title": "客户协同",
            "description": "进入客服控制台，处理订单咨询、离线留言与售后沟通。",
            "links": [
                {"label": "客服控制台", "url": reverse("support_chat_console")},
                {"label": "客户工作台", "url": reverse("backoffice_customers")},
            ],
        },
    ]
    context = {
        **build_admin_shell_context(
            request,
            title="订单控制台",
            subtitle=f"{filters.label} · {filters.currency_label}。统一查看订单转化、履约负载、退款售后与客户协同，再分流到原生后台执行。",
            active_nav="orders",
            kicker="Order Mission Control",
            breadcrumbs=[
                {"label": "后台首页", "url": reverse("admin:index")},
                {"label": "订单控制台"},
            ],
            topbar_actions=[
                {"label": "订单列表", "url": reverse("admin:orders_order_changelist")},
                {"label": "发货管理", "url": reverse("admin:shipping_shipment_changelist")},
                {"label": "退款管理", "url": reverse("admin:transactions_refund_changelist")},
                {"label": "售后管理", "url": reverse("admin:after_sales_aftersalescase_changelist")},
                {"label": "客服控制台", "url": reverse("support_chat_console"), "primary": True},
            ],
        ),
        "filters": filters,
        "range_options": RANGE_OPTIONS,
        "currency_options": CURRENCY_OPTIONS,
        "order_console_metrics": order_console_metrics,
        "order_console_overview": [
            {
                "variant": "is-cyan",
                "label": "GMV",
                "title": f"{summary['trade_radar']['gmv']}",
                "detail": f"已支付订单 {summary['trade_radar']['paid_order_count']} 单",
            },
            {
                "variant": "is-violet",
                "label": "Backlog",
                "title": str(len(attention_orders)),
                "detail": "最近订单流中待推进订单数",
            },
            {
                "variant": "is-danger",
                "label": "Exception",
                "title": str(len(exception_shipments)),
                "detail": "最近发货异常件需优先关注",
            },
        ],
        "order_kpis": kpis,
        "order_trends": order_trends,
        "order_status_breakdowns": status_breakdowns,
        "order_shipping_summary": shipping_summary,
        "order_geo_summary": geo_summary,
        "recent_orders": recent_orders,
        "attention_orders": attention_orders,
        "exception_shipments": exception_shipments,
        "geo_country_rows": geo_countries,
        "geo_city_rows": geo_cities,
        "order_operations_sections": order_operations_sections,
        "order_console_actions": [
            {
                "title": "订单批量推进",
                "detail": "在订单列表使用“标记为处理中”“创建 EasyPost 发货单”“创建手动发货单”“关闭未支付订单”等动作。",
            },
            {
                "title": "退款 / 售后联动",
                "detail": "先看退款申请与售后单，再决定是否回到订单详情修改状态与内部备注。",
            },
            {
                "title": "客户沟通闭环",
                "detail": "订单问题优先在客服控制台收敛，再回到订单、发货和售后后台执行变更。",
            },
        ],
        "order_status_sections": [
            {"title": "订单状态", "rows": status_breakdowns["orders"], "suffix": "单", "secondary": False},
            {"title": "支付状态", "rows": status_breakdowns["payments"], "suffix": "笔", "secondary": True},
            {"title": "履约状态", "rows": status_breakdowns["fulfillment"], "suffix": "单", "secondary": False},
        ],
        "order_shipping_cards": [
            {
                "label": "发货异常",
                "value": str(len(exception_shipments)),
                "detail": "优先处理物流异常和长时间未推进运单。",
            },
            {
                "label": "待创建 / 在途",
                "value": str(pending_shipments.count()),
                "detail": "待创建、已购面单与运输中订单负载。",
            },
            {
                "label": "热点国家",
                "value": geo_countries[0]["shipping_country"] if geo_countries else "-",
                "detail": f"{geo_countries[0]['order_count']} 单" if geo_countries else "当前范围暂无已支付地区数据。",
            },
            {
                "label": "热点城市",
                "value": geo_cities[0]["shipping_city"] if geo_cities else "-",
                "detail": f"{geo_cities[0]['order_count']} 单" if geo_cities else "当前范围暂无城市分布数据。",
            },
        ],
        "order_after_sales_breakdown": [
            {
                "label": dict(AfterSalesCase.CaseType.choices).get(row["case_type"], row["case_type"]),
                "count": row["count"],
            }
            for row in open_cases_queryset.values("case_type").annotate(count=Count("id")).order_by("-count", "case_type")[:4]
        ],
    }
    return TemplateResponse(request, "admin/orders_console.html", context)


def payment_console_view(request):
    filters = parse_trade_cockpit_filters(request.GET)
    summary = TradeCockpitService.get_dashboard_summary(filters)
    payment_summary = summary["payment_summary"]
    funds_flow = summary["funds_flow"]
    risk_summary = summary["risk_summary"]
    providers = payment_summary["providers"]
    payment_console_metrics = [
        {
            "variant": "is-gmv",
            "label": "支付成功",
            "value": f"{summary['trade_radar']['paid_rate']}%",
            "detail": f"{filters.label} {filters.currency_label}支付成功率",
        },
        {
            "variant": "is-paid-rate",
            "label": "需补操作",
            "value": str(payment_summary["requires_action_count"]),
            "detail": f"失败 {payment_summary['failed_count']} 笔",
        },
        {
            "variant": "is-alerts",
            "label": "退款规模",
            "value": f"{summary['trade_radar']['refund_total']}",
            "detail": f"已完成退款 {len(summary['alerts'])} 条风险预警需关注",
        },
        {
            "variant": "is-net",
            "label": "净资金",
            "value": f"{funds_flow['net_amount']}",
            "detail": f"手续费 {funds_flow['fee_amount']}",
        },
    ]
    provider_cards = [
        {
            "name": provider["provider"] or "未命名渠道",
            "total_count": provider["total_count"],
            "paid_count": provider["paid_count"],
            "failed_count": provider["failed_count"],
        }
        for provider in providers
    ]
    operations_sections = [
        {
            "title": "支付执行面",
            "description": "直接进入支付记录与回调事件，处理渠道结果与异常支付单。",
            "links": [
                {"label": "支付记录", "url": reverse("admin:payments_payment_changelist")},
                {"label": "支付事件", "url": reverse("admin:payments_paymentevent_changelist")},
                {"label": "交易列表", "url": reverse("admin:transactions_transaction_changelist")},
            ],
        },
        {
            "title": "退款与风控",
            "description": "查看退款进度、人工审核、阻断决策与风险上下文。",
            "links": [
                {"label": "退款管理", "url": reverse("admin:transactions_refund_changelist")},
                {"label": "风控观察", "url": reverse("admin:transactions_riskassessment_changelist")},
                {"label": "售后管理", "url": reverse("admin:after_sales_aftersalescase_changelist")},
            ],
        },
        {
            "title": "账务与对账",
            "description": "追踪账务流水、记账分录、结算记录与对账异常。",
            "links": [
                {"label": "账务流水", "url": reverse("admin:transactions_ledgertransaction_changelist")},
                {"label": "记账分录", "url": reverse("admin:transactions_ledgerentry_changelist")},
                {"label": "对账运行", "url": reverse("admin:transactions_reconciliationrun_changelist")},
                {"label": "对账异常", "url": reverse("admin:transactions_reconciliationitem_changelist")},
            ],
        },
    ]
    context = {
        **build_admin_shell_context(
            request,
            title="支付控制台",
            subtitle=f"{filters.label} · {filters.currency_label}。统一查看支付成功、退款压力、风控告警与账务流转。",
            active_nav="payments",
            kicker="Payment Mission Control",
            breadcrumbs=[
                {"label": "后台首页", "url": reverse("admin:index")},
                {"label": "支付控制台"},
            ],
            topbar_actions=[
                {"label": "支付记录", "url": reverse("admin:payments_payment_changelist")},
                {"label": "支付事件", "url": reverse("admin:payments_paymentevent_changelist")},
                {"label": "退款", "url": reverse("admin:transactions_refund_changelist")},
                {"label": "风控", "url": reverse("admin:transactions_riskassessment_changelist"), "primary": True},
            ],
        ),
        "filters": filters,
        "range_options": RANGE_OPTIONS,
        "currency_options": CURRENCY_OPTIONS,
        "payment_summary": payment_summary,
        "funds_flow": funds_flow,
        "risk_summary": risk_summary,
        "alerts": summary["alerts"],
        "payment_console_metrics": payment_console_metrics,
        "payment_provider_cards": provider_cards,
        "payment_operations_sections": operations_sections,
        "payment_console_overview": [
            {
                "variant": "is-cyan",
                "label": "Capture",
                "title": f"{summary['trade_radar']['gmv']}",
                "detail": f"已支付订单 {summary['trade_radar']['paid_order_count']} 单",
            },
            {
                "variant": "is-violet",
                "label": "Ledger",
                "title": str(funds_flow["ledger_transactions_count"]),
                "detail": "账务流水记录数",
            },
            {
                "variant": "is-danger",
                "label": "Risk",
                "title": f"Review {risk_summary['review_count']} / Block {risk_summary['block_count']}",
                "detail": "支付风险与人工审核负荷",
            },
        ],
    }
    return TemplateResponse(request, "admin/payments_console.html", context)
