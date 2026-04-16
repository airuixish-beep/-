from django.contrib import admin

from .models import Shipment, ShipmentEvent


class ShipmentEventInline(admin.TabularInline):
    model = ShipmentEvent
    extra = 0
    readonly_fields = ("status", "message", "event_time", "payload", "created_at")
    can_delete = False


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ("order", "provider", "status", "tracking_number", "shipped_at", "delivered_at", "created_at")
    list_filter = ("provider", "status", "created_at")
    search_fields = ("order__order_number", "tracking_number", "external_shipment_id")
    readonly_fields = ("raw_payload", "created_at", "updated_at")
    inlines = [ShipmentEventInline]

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.order.sync_fulfillment_from_shipment_status(obj.status)


@admin.register(ShipmentEvent)
class ShipmentEventAdmin(admin.ModelAdmin):
    list_display = ("shipment", "status", "event_time", "created_at")
    list_filter = ("status", "event_time")
    search_fields = ("shipment__order__order_number", "message", "shipment__tracking_number")
    readonly_fields = ("payload", "created_at")
