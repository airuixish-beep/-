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
        "order",
        "provider",
        "carrier_name",
        "status",
        "tracking_number",
        "shipped_at",
        "delivered_at",
        "created_at",
    )
    list_filter = ("provider", "status", "created_at")
    search_fields = ("order__order_number", "tracking_number", "external_shipment_id", "carrier_name")
    readonly_fields = ("raw_payload", "created_at", "updated_at")
    inlines = [ShipmentEventInline]
    actions = [mark_shipped, mark_delivered, mark_exception, cancel_shipment]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.order.sync_fulfillment_from_shipment_status(obj.status)


@admin.register(ShipmentEvent)
class ShipmentEventAdmin(admin.ModelAdmin):
    list_display = ("shipment", "status", "event_time", "created_at")
    list_filter = ("status", "event_time")
    search_fields = ("shipment__order__order_number", "message", "shipment__tracking_number")
    readonly_fields = ("payload", "created_at")
