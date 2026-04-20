from django.contrib import admin, messages
from django.utils import timezone

from shipping.models import Shipment
from shipping.services import EasyPostService, ShippingConfigurationError

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "product_name_snapshot", "sku_snapshot", "unit_price", "quantity", "line_total")
    can_delete = False


@admin.action(description="为已支付订单创建 EasyPost 发货单")
def create_easypost_shipment(modeladmin, request, queryset):
    created_count = 0
    for order in queryset.filter(payment_status=Order.PaymentStatus.PAID):
        shipment, was_created = Shipment.objects.get_or_create(order=order)
        if not was_created and shipment.external_shipment_id:
            continue
        try:
            EasyPostService.create_shipment(shipment)
        except ShippingConfigurationError as exc:
            modeladmin.message_user(request, f"{order.order_number}: {exc}", level=messages.ERROR)
        except Exception as exc:
            modeladmin.message_user(request, f"{order.order_number}: 创建发货单失败 - {exc}", level=messages.ERROR)
        else:
            created_count += 1
    if created_count:
        modeladmin.message_user(request, f"已创建 {created_count} 个发货单。")


@admin.action(description="将订单标记为处理中")
def mark_processing(modeladmin, request, queryset):
    updated = queryset.update(status=Order.Status.PROCESSING, fulfillment_status=Order.FulfillmentStatus.PROCESSING, updated_at=timezone.now())
    modeladmin.message_user(request, f"已更新 {updated} 个订单。")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "customer_name",
        "customer_email",
        "status",
        "payment_status",
        "fulfillment_status",
        "total_amount",
        "currency",
        "created_at",
    )
    list_filter = ("status", "payment_status", "fulfillment_status", "currency", "shipping_country", "created_at")
    search_fields = ("order_number", "customer_name", "customer_email", "customer_phone")
    readonly_fields = (
        "order_number",
        "public_token",
        "subtotal_amount",
        "total_amount",
        "paid_at",
        "created_at",
        "updated_at",
    )
    inlines = [OrderItemInline]
    actions = [mark_processing, create_easypost_shipment]
    fieldsets = (
        ("订单状态", {"fields": ("order_number", "public_token", "status", "payment_status", "fulfillment_status", "paid_at")}),
        ("客户信息", {"fields": ("customer_name", "customer_email", "customer_phone")}),
        ("收货地址", {"fields": ("shipping_country", "shipping_state", "shipping_city", "shipping_postal_code", "shipping_address_line1", "shipping_address_line2")}),
        ("金额信息", {"fields": ("subtotal_amount", "shipping_amount", "total_amount", "currency")}),
        ("其他", {"fields": ("notes", "created_at", "updated_at")}),
    )
