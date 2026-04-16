from django.contrib import admin

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "product_name_snapshot", "sku_snapshot", "unit_price", "quantity", "line_total")
    can_delete = False


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
    fieldsets = (
        ("订单状态", {"fields": ("order_number", "public_token", "status", "payment_status", "fulfillment_status", "paid_at")}),
        ("客户信息", {"fields": ("customer_name", "customer_email", "customer_phone")}),
        ("收货地址", {"fields": ("shipping_country", "shipping_state", "shipping_city", "shipping_postal_code", "shipping_address_line1", "shipping_address_line2")}),
        ("金额信息", {"fields": ("subtotal_amount", "shipping_amount", "total_amount", "currency")}),
        ("其他", {"fields": ("notes", "created_at", "updated_at")}),
    )
