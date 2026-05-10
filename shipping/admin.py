from django.contrib import admin, messages

from .models import Shipment, ShipmentEvent
from .services import ShipmentOpsService


class ShipmentEventInline(admin.TabularInline):
    model = ShipmentEvent
    extra = 0
    readonly_fields = ("status", "message", "event_time", "payload", "created_at")
    can_delete = False


@admin.action(description="标记为已发货")
def mark_shipped(modeladmin, request, queryset):
    updated = 0
    for shipment in queryset:
        try:
            ShipmentOpsService.mark_shipped(
                shipment,
                tracking_number=shipment.tracking_number,
                carrier_name=shipment.carrier_name or shipment.get_provider_display(),
            )
        except Exception as exc:
            modeladmin.message_user(request, f"{shipment}: {exc}", level=messages.ERROR)
        else:
            updated += 1
    if updated:
        modeladmin.message_user(request, f"已标记 {updated} 个发货单为已发货。", level=messages.SUCCESS)


@admin.action(description="标记为已送达")
def mark_delivered(modeladmin, request, queryset):
    updated = 0
    for shipment in queryset:
        try:
            ShipmentOpsService.mark_delivered(shipment)
        except Exception as exc:
            modeladmin.message_user(request, f"{shipment}: {exc}", level=messages.ERROR)
        else:
            updated += 1
    if updated:
        modeladmin.message_user(request, f"已标记 {updated} 个发货单为已送达。", level=messages.SUCCESS)


@admin.action(description="标记物流异常")
def mark_exception(modeladmin, request, queryset):
    updated = 0
    for shipment in queryset:
        try:
            ShipmentOpsService.mark_exception(shipment, exception_notes="admin marked exception")
        except Exception as exc:
            modeladmin.message_user(request, f"{shipment}: {exc}", level=messages.ERROR)
        else:
            updated += 1
    if updated:
        modeladmin.message_user(request, f"已标记 {updated} 个发货单为异常。", level=messages.WARNING)


@admin.action(description="取消发货单")
def cancel_shipment(modeladmin, request, queryset):
    updated = 0
    for shipment in queryset:
        try:
            ShipmentOpsService.cancel(shipment, operator_notes="admin cancelled shipment")
        except Exception as exc:
            modeladmin.message_user(request, f"{shipment}: {exc}", level=messages.ERROR)
        else:
            updated += 1
    if updated:
        modeladmin.message_user(request, f"已取消 {updated} 个发货单。", level=messages.SUCCESS)


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "destination_summary",
        "provider",
        "status",
        "carrier_name",
        "tracking_number",
        "shipped_at",
        "delivered_at",
        "created_at",
    )
    list_filter = ("provider", "status", "order__shipping_country", "created_at", "shipped_at", "delivered_at")
    search_fields = ("order__order_number", "tracking_number", "external_shipment_id", "carrier_name")
    readonly_fields = (
        "order_customer",
        "destination_summary",
        "external_shipment_id",
        "raw_payload",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("order",)
    inlines = [ShipmentEventInline]
    actions = [mark_shipped, mark_delivered, mark_exception, cancel_shipment]
    fieldsets = (
        ("发货单概览", {"fields": ("order", "order_customer", "provider", "status", "external_shipment_id")}),
        (
            "物流追踪",
            {
                "fields": (
                    "carrier_name",
                    "tracking_number",
                    "tracking_url",
                    "label_url",
                    "shipped_at",
                    "delivered_at",
                    "destination_summary",
                )
            },
        ),
        ("运营备注", {"fields": ("operator_notes", "exception_notes")}),
        (
            "原始数据与审计",
            {
                "classes": ("collapse",),
                "fields": ("raw_payload", "created_at", "updated_at"),
            },
        ),
    )
    list_select_related = ("order",)
    date_hierarchy = "created_at"
    save_on_top = True

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(
            request,
            extra_context={
                **(extra_context or {}),
                "title": "Shipping",
                "subtitle": "查看发货单、跟踪状态、异常件与送达进度。",
            },
        )

    def add_view(self, request, form_url="", extra_context=None):
        return super().add_view(
            request,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "新增发货单",
                "subtitle": "录入运单信息、物流渠道和履约状态。",
            },
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "编辑发货单",
                "subtitle": "维护运单信息、物流状态和履约事件。",
            },
        )

    @admin.display(description="订单号", ordering="order__order_number")
    def order_number(self, obj):
        return obj.order.order_number

    @admin.display(description="客户")
    def order_customer(self, obj):
        if not obj or not getattr(obj, "order", None):
            return "-"
        return f"{obj.order.customer_name} / {obj.order.customer_email}"

    @admin.display(description="目的地")
    def destination_summary(self, obj):
        if not obj or not getattr(obj, "order", None):
            return "-"
        return obj.order.shipping_address

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.order.sync_fulfillment_from_shipment_status(obj.status)


@admin.register(ShipmentEvent)
class ShipmentEventAdmin(admin.ModelAdmin):
    list_display = ("shipment", "status", "event_time", "created_at")
    list_filter = ("status", "event_time")
    search_fields = ("shipment__order__order_number", "message", "shipment__tracking_number")
    readonly_fields = ("payload", "created_at")
