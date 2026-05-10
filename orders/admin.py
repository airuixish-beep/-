from django.contrib import admin, messages

from after_sales.models import AfterSalesCase
from shipping.models import Shipment
from shipping.services import EasyPostService, ShipmentOpsService, ShippingConfigurationError
from transactions.models import Refund

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
    updated = 0
    for order in queryset:
        try:
            order.mark_processing()
        except ValueError as exc:
            modeladmin.message_user(request, f"{order.order_number}: {exc}", level=messages.ERROR)
        else:
            updated += 1
    if updated:
        modeladmin.message_user(request, f"已更新 {updated} 个订单。")


@admin.action(description="关闭未支付订单")
def close_unpaid_orders(modeladmin, request, queryset):
    updated = 0
    for order in queryset:
        try:
            order.close()
        except ValueError as exc:
            modeladmin.message_user(request, f"{order.order_number}: {exc}", level=messages.ERROR)
        else:
            updated += 1
    if updated:
        modeladmin.message_user(request, f"已关闭 {updated} 个未支付订单。", level=messages.SUCCESS)


@admin.action(description="创建手动发货单")
def create_manual_shipment(modeladmin, request, queryset):
    created = 0
    for order in queryset:
        try:
            ShipmentOpsService.create_manual_shipment(order, operator_notes="created from order admin")
        except Exception as exc:
            modeladmin.message_user(request, f"{order.order_number}: {exc}", level=messages.ERROR)
        else:
            created += 1
    if created:
        modeladmin.message_user(request, f"已创建 {created} 个手动发货单。", level=messages.SUCCESS)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "customer_summary",
        "status",
        "payment_status",
        "fulfillment_status",
        "destination_summary",
        "latest_shipment_status",
        "refund_summary",
        "after_sales_count",
        "total_amount",
        "currency",
        "created_at",
    )
    list_filter = ("status", "payment_status", "fulfillment_status", "currency", "shipping_country", "paid_at", "created_at")
    search_fields = ("order_number", "customer_name", "customer_email", "customer_phone")
    readonly_fields = (
        "order_number",
        "public_token",
        "shipping_address",
        "latest_shipment_status",
        "refund_summary",
        "after_sales_count",
        "subtotal_amount",
        "total_amount",
        "paid_at",
        "closed_at",
        "created_at",
        "updated_at",
    )
    inlines = [OrderItemInline]
    actions = [mark_processing, create_easypost_shipment, create_manual_shipment, close_unpaid_orders]
    fieldsets = (
        (
            "指挥概览",
            {
                "fields": (
                    "order_number",
                    "public_token",
                    "status",
                    "payment_status",
                    "fulfillment_status",
                    "latest_shipment_status",
                    "refund_summary",
                    "after_sales_count",
                )
            },
        ),
        ("客户信息", {"fields": ("customer_name", "customer_email", "customer_phone")}),
        (
            "收货地址",
            {
                "fields": (
                    "shipping_country",
                    "shipping_state",
                    "shipping_city",
                    "shipping_postal_code",
                    "shipping_address_line1",
                    "shipping_address_line2",
                    "shipping_address",
                )
            },
        ),
        ("金额信息", {"fields": ("subtotal_amount", "shipping_amount", "total_amount", "currency")}),
        ("运营备注", {"fields": ("notes", "internal_notes")}),
        (
            "时间与审计",
            {
                "classes": ("collapse",),
                "fields": ("paid_at", "closed_at", "created_at", "updated_at"),
            },
        ),
    )
    date_hierarchy = "created_at"
    list_per_page = 25
    save_on_top = True

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.prefetch_related("shipments", "after_sales_cases", "transactions__refunds")

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(
            request,
            extra_context={
                **(extra_context or {}),
                "title": "Orders",
                "subtitle": "查看订单、支付状态、客户信息与履约进度。",
            },
        )

    def add_view(self, request, form_url="", extra_context=None):
        return super().add_view(
            request,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "新增订单",
                "subtitle": "录入客户信息、收货地址和订单金额。",
            },
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "编辑订单",
                "subtitle": "维护订单状态、支付状态和履约相关字段。",
            },
        )

    @admin.display(description="客户")
    def customer_summary(self, obj):
        return f"{obj.customer_name} / {obj.customer_email}"

    @admin.display(description="目的地")
    def destination_summary(self, obj):
        return f"{obj.shipping_city}, {obj.shipping_country}"

    @admin.display(description="最新发货状态")
    def latest_shipment_status(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "-"
        shipments = list(obj.shipments.all())
        shipment = shipments[0] if shipments else None
        return shipment.get_status_display() if shipment else "-"

    @admin.display(description="退款摘要")
    def refund_summary(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "无"
        refunds = [refund for transaction in obj.transactions.all() for refund in transaction.refunds.all()]
        if not refunds:
            return "无"
        succeeded = sum(1 for refund in refunds if refund.status == Refund.Status.SUCCEEDED)
        processing = sum(1 for refund in refunds if refund.status == Refund.Status.PROCESSING)
        requested = sum(1 for refund in refunds if refund.status == Refund.Status.REQUESTED)
        return f"成功{succeeded}/处理中{processing}/申请{requested}"

    @admin.display(description="售后单数")
    def after_sales_count(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return 0
        related = getattr(obj, "after_sales_cases", None)
        if related is None:
            return 0
        return len(related.all())
