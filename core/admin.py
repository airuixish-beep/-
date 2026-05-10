from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, F, Q, Sum
from django.urls import reverse
from django.utils import timezone

from .models import SiteConfig
from .views import get_admin_nav_groups

admin.site.site_header = "XUANOR Command Center"
admin.site.site_title = "XUANOR Backoffice"
admin.site.index_title = "交易履约管理后台"

_original_each_context = admin.site.each_context


def _detect_active_nav(path):
    if path.startswith("/admin/trade-cockpit/"):
        return "trade_cockpit"
    if path.startswith("/admin/ai-command/"):
        return "ai_command"
    if path.startswith("/admin/content-os/"):
        return "content_os"
    if path.startswith("/admin/analytics/quiz"):
        return "quiz"
    if path.startswith("/admin/analytics/traffic"):
        return "traffic"
    if path.startswith("/admin/analytics/"):
        return "analytics"
    if path.startswith("/admin/support-chat/") or path.startswith("/admin/support_chat/"):
        return "support"
    if path.startswith("/admin/orders/"):
        return "orders"
    if path.startswith("/admin/payments/console/") or path.startswith("/admin/payments/"):
        return "payments"
    if path.startswith("/admin/shipping/"):
        return "shipping"
    if path.startswith("/admin/after_sales/"):
        return "after_sales"
    if path.startswith("/admin/transactions/refund/"):
        return "refunds"
    if path.startswith("/admin/products/"):
        return "products"
    if path.startswith("/admin/customers/"):
        return "customers"
    if path.startswith("/admin/settings/"):
        return "settings"
    return "home"


def _build_admin_page_meta(request):
    path = request.path
    if path.startswith("/admin/orders/order/"):
        is_add = path.rstrip("/").endswith("add")
        is_change = path.rstrip("/").split("/")[-1].isdigit()
        return {
            "title": "订单中心",
            "subtitle": "查看订单、支付状态、客户信息与履约进度。" if not (is_add or is_change) else "维护订单信息、支付状态与履约相关字段。",
            "x_admin_kicker": "Order Operations",
            "x_admin_topbar_actions": [
                {"label": "订单列表", "url": "/admin/orders/order/"},
                {"label": "发货管理", "url": "/admin/shipping/shipment/"},
                {"label": "退款管理", "url": "/admin/transactions/refund/", "primary": True},
            ],
            "x_admin_breadcrumbs": [
                {"label": "后台首页", "url": "/admin/"},
                {"label": "订单中心", "url": "/admin/orders/order/"},
            ],
        }
    if path.startswith("/admin/products/product/"):
        is_add = path.rstrip("/").endswith("add")
        is_change = path.rstrip("/").split("/")[-1].isdigit()
        return {
            "title": "商品中心",
            "subtitle": "维护商品资料、上下架状态、库存与商品结构。" if not (is_add or is_change) else "维护商品详情、价格、库存、图片和变体信息。",
            "x_admin_kicker": "Catalog Operations",
            "x_admin_topbar_actions": [
                {"label": "商品列表", "url": "/admin/products/product/"},
                {"label": "商品分类", "url": "/admin/products/category/"},
                {"label": "商品变体", "url": "/admin/products/productvariant/", "primary": True},
            ],
            "x_admin_breadcrumbs": [
                {"label": "后台首页", "url": "/admin/"},
                {"label": "商品中心", "url": "/admin/products/product/"},
            ],
        }
    if path.startswith("/admin/shipping/shipment/"):
        is_add = path.rstrip("/").endswith("add")
        is_change = path.rstrip("/").split("/")[-1].isdigit()
        return {
            "title": "发货中心",
            "subtitle": "查看发货单、跟踪状态、异常件与送达进度。" if not (is_add or is_change) else "维护运单信息、物流状态和履约事件。",
            "x_admin_kicker": "Fulfillment Operations",
            "x_admin_topbar_actions": [
                {"label": "发货列表", "url": "/admin/shipping/shipment/"},
                {"label": "订单管理", "url": "/admin/orders/order/"},
                {"label": "售后管理", "url": "/admin/after_sales/aftersalescase/", "primary": True},
            ],
            "x_admin_breadcrumbs": [
                {"label": "后台首页", "url": "/admin/"},
                {"label": "发货中心", "url": "/admin/shipping/shipment/"},
            ],
        }
    if path.startswith("/admin/after_sales/aftersalescase/"):
        is_add = path.rstrip("/").endswith("add")
        is_change = path.rstrip("/").split("/")[-1].isdigit()
        return {
            "title": "售后中心",
            "subtitle": "处理售后单、补发协作与退款联动。" if not (is_add or is_change) else "维护售后状态、客户诉求、退款与补发信息。",
            "x_admin_kicker": "售后协同中心",
            "x_admin_topbar_actions": [
                {"label": "售后列表", "url": "/admin/after_sales/aftersalescase/"},
                {"label": "发货管理", "url": "/admin/shipping/shipment/"},
                {"label": "退款管理", "url": "/admin/transactions/refund/", "primary": True},
            ],
            "x_admin_breadcrumbs": [
                {"label": "后台首页", "url": "/admin/"},
                {"label": "售后中心", "url": "/admin/after_sales/aftersalescase/"},
            ],
        }
    if path.startswith("/admin/transactions/refund/"):
        is_add = path.rstrip("/").endswith("add")
        is_change = path.rstrip("/").split("/")[-1].isdigit()
        return {
            "title": "退款中心",
            "subtitle": "查看退款申请、处理状态、失败原因与完成结果。" if not (is_add or is_change) else "维护退款金额、状态、失败原因和完成信息。",
            "x_admin_kicker": "Refund Operations",
            "x_admin_topbar_actions": [
                {"label": "退款列表", "url": "/admin/transactions/refund/"},
                {"label": "订单管理", "url": "/admin/orders/order/"},
                {"label": "售后管理", "url": "/admin/after_sales/aftersalescase/", "primary": True},
            ],
            "x_admin_breadcrumbs": [
                {"label": "后台首页", "url": "/admin/"},
                {"label": "退款中心", "url": "/admin/transactions/refund/"},
            ],
        }
    return {}


def _build_homepage_product_module():
    from products.models import Category, InventoryRecord, Product, ProductVariant

    total_products = Product.objects.count()
    active_products = Product.objects.filter(is_active=True).count()
    purchasable_products = Product.objects.filter(is_active=True, is_purchasable=True).count()
    total_variants = ProductVariant.objects.count()
    active_variants = ProductVariant.objects.filter(is_active=True).count()
    low_stock_variants = ProductVariant.objects.filter(is_active=True, stock_quantity__lte=F("safety_stock")).count()
    out_of_stock_variants = ProductVariant.objects.filter(is_active=True, stock_quantity=0).count()
    inventory_events_7d = InventoryRecord.objects.filter(created_at__gte=timezone.now() - timedelta(days=7)).count()
    category_count = Category.objects.count()
    root_category_count = Category.objects.filter(parent__isnull=True).count()

    top_categories = list(
        Category.objects.annotate(product_total=Count("products"))
        .order_by("-product_total", "sort_order", "id")[:2]
    )
    warning_items = []
    if low_stock_variants:
        warning_items.append(
            {
                "tone": "danger",
                "label": "低库存预警",
                "value": str(low_stock_variants),
                "detail": "SKU 库存已触达或低于安全库存阈值。",
            }
        )
    if out_of_stock_variants:
        warning_items.append(
            {
                "tone": "violet",
                "label": "缺货 SKU",
                "value": str(out_of_stock_variants),
                "detail": "当前启用 SKU 中已无可售库存的数量。",
            }
        )
    if inventory_events_7d:
        warning_items.append(
            {
                "tone": "cyan",
                "label": "7天库存动作",
                "value": str(inventory_events_7d),
                "detail": "近 7 天库存调整、扣减与回补流水。",
            }
        )
    if not warning_items:
        warning_items.append(
            {
                "tone": "cyan",
                "label": "库存稳定",
                "value": "OK",
                "detail": "当前没有触发低库存或缺货告警。",
            }
        )

    focus_cards = [
        {
            "title": "商品状态",
            "detail": f"上架 {active_products} / 可售 {purchasable_products} / 总商品 {total_products}",
        },
        {
            "title": "SKU 覆盖",
            "detail": f"启用 SKU {active_variants} 个，低库存 {low_stock_variants} 个。",
        },
        {
            "title": "类目结构",
            "detail": f"类目 {category_count} 个，其中一级类目 {root_category_count} 个。",
        },
    ]
    if top_categories:
        focus_cards.append(
            {
                "title": "类目热区",
                "detail": " / ".join(f"{category.name} {category.product_total} 商品" for category in top_categories),
            }
        )

    return {
        "command_metrics": [
            {
                "label": "商品总量",
                "value": str(total_products),
                "detail": f"上架 {active_products} / 可售 {purchasable_products}",
                "variant": "is-gmv",
            },
            {
                "label": "SKU 总量",
                "value": str(total_variants),
                "detail": f"启用 {active_variants} / 低库存 {low_stock_variants}",
                "variant": "is-paid-rate",
            },
            {
                "label": "类目结构",
                "value": str(category_count),
                "detail": f"一级类目 {root_category_count} 个",
                "variant": "is-net",
            },
            {
                "label": "7天库存流水",
                "value": str(inventory_events_7d),
                "detail": "最近 7 天库存变更记录",
                "variant": "is-alerts",
            },
        ],
        "warning_items": warning_items,
        "focus_cards": focus_cards,
    }


def _build_homepage_metrics():
    from after_sales.models import AfterSalesCase
    from orders.models import Order
    from shipping.models import Shipment
    from support_chat.models import ChatOfflineMessage, ChatSession
    from transactions.models import Refund

    paid_orders = Order.objects.filter(payment_status=Order.PaymentStatus.PAID)
    open_cases = AfterSalesCase.objects.filter(status__in=[AfterSalesCase.Status.OPEN, AfterSalesCase.Status.PROCESSING])
    active_sessions = ChatSession.objects.filter(status__in=[ChatSession.Status.OPEN, ChatSession.Status.WAITING_OPERATOR])
    pending_shipments = Shipment.objects.filter(
        status__in=[Shipment.Status.PENDING, Shipment.Status.LABEL_PURCHASED, Shipment.Status.IN_TRANSIT]
    )
    pending_refunds = Refund.objects.filter(status__in=[Refund.Status.REQUESTED, Refund.Status.PROCESSING])
    new_offline_messages = ChatOfflineMessage.objects.filter(status=ChatOfflineMessage.Status.NEW)
    weekly_gmv = paid_orders.aggregate(total=Sum("total_amount")).get("total") or 0
    product_module = _build_homepage_product_module()

    return {
        "hero_metrics": [
            {
                "label": "7天 GMV",
                "value": f"{weekly_gmv}",
                "detail": f"{paid_orders.count()} 笔已支付订单",
                "tone": "cyan",
            },
            {
                "label": "待履约",
                "value": str(pending_shipments.count()),
                "detail": "待创建 / 已购面单 / 运输中",
                "tone": "violet",
            },
            {
                "label": "待客服",
                "value": str(active_sessions.count()),
                "detail": f"含 {new_offline_messages.count()} 条离线留言",
                "tone": "danger",
            },
        ],
        "command_metrics": [
            {
                "label": "已支付订单",
                "value": str(paid_orders.count()),
                "detail": "交易已完成支付确认",
                "variant": "is-gmv",
                "url": "/admin/orders/order/?payment_status=paid",
            },
            {
                "label": "待履约",
                "value": str(pending_shipments.count()),
                "detail": "待发货与在途单据总量",
                "variant": "is-paid-rate",
                "url": "/admin/shipping/shipment/",
            },
            {
                "label": "待售后 / 退款",
                "value": str(open_cases.count() + pending_refunds.count()),
                "detail": f"售后 {open_cases.count()} / 退款 {pending_refunds.count()}",
                "variant": "is-alerts",
                "url": "/admin/after_sales/aftersalescase/",
            },
            {
                "label": "客户待处理",
                "value": str(active_sessions.count() + new_offline_messages.count()),
                "detail": "客服会话与离线留言待处理量",
                "variant": "is-net",
                "url": reverse("support_chat_console"),
            },
        ],
        "priority_metrics": [
            {
                "label": "Priority 01",
                "title": "订单 / 发货",
                "detail": f"待履约 {pending_shipments.count()} 单，优先推进支付后履约链路。",
            },
            {
                "label": "Priority 02",
                "title": "售后 / 退款",
                "detail": f"售后 {open_cases.count()} 单，退款 {pending_refunds.count()} 单待继续处理。",
            },
        ],
        "product_module": product_module,
    }


def _xuanor_each_context(request):
    context = _original_each_context(request)
    context.setdefault("x_admin_nav_groups", get_admin_nav_groups())
    context.setdefault("x_admin_sidebar_note", "以交易、履约、客服与分析统一调度为核心，构建后台战情中控台。")
    context.setdefault("x_admin_kicker", "XUANOR Command Center")
    context.setdefault("x_admin_active_nav", _detect_active_nav(request.path))
    context.setdefault("x_admin_topbar_actions", [])
    for key, value in _build_admin_page_meta(request).items():
        context.setdefault(key, value)
    if request.path == "/admin/":
        for key, value in _build_homepage_metrics().items():
            context.setdefault(key, value)
    return context


admin.site.each_context = _xuanor_each_context


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ("site_name", "contact_email", "updated_at")
