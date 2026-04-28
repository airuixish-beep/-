from django.contrib import admin

from .models import Payment, PaymentEvent


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "transaction",
        "provider",
        "status",
        "amount",
        "currency",
        "external_payment_id",
        "paid_at",
        "created_at",
    )
    list_filter = ("provider", "status", "currency", "created_at")
    search_fields = ("order__order_number", "external_payment_id", "checkout_token_or_session_id")
    readonly_fields = ("raw_payload", "created_at", "updated_at")


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "event_id", "event_type", "processed_at")
    list_filter = ("provider", "event_type", "processed_at")
    search_fields = ("event_id", "event_type")
    readonly_fields = ("payload", "processed_at")
