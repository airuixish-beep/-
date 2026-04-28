from django.contrib import admin

from orders.models import Order
from transactions.engine import TransactionEngine
from transactions.services import get_or_create_purchase_transaction

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

    def save_model(self, request, obj, form, change):
        previous = None
        if change:
            previous = Payment.objects.select_related("order", "transaction").get(pk=obj.pk)

        super().save_model(request, obj, form, change)

        obj = Payment.objects.select_related("order", "transaction").get(pk=obj.pk)
        transaction_obj = obj.transaction or get_or_create_purchase_transaction(obj.order, obj)

        if obj.status == Payment.Status.PAID and obj.paid_at:
            if obj.order.payment_status != Order.PaymentStatus.PAID or obj.order.paid_at != obj.paid_at:
                obj.order.mark_paid(obj.paid_at)
            transaction_updates = []
            if transaction_obj.status != transaction_obj.Status.PAID:
                transaction_obj.status = transaction_obj.Status.PAID
                transaction_updates.append("status")
            if transaction_obj.paid_at != obj.paid_at:
                transaction_obj.paid_at = obj.paid_at
                transaction_updates.append("paid_at")
            if transaction_obj.provider != obj.provider:
                transaction_obj.provider = obj.provider
                transaction_updates.append("provider")
            if transaction_obj.amount != obj.amount:
                transaction_obj.amount = obj.amount
                transaction_updates.append("amount")
            if transaction_obj.currency != obj.currency:
                transaction_obj.currency = obj.currency
                transaction_updates.append("currency")
            if transaction_updates:
                transaction_obj.save(update_fields=[*transaction_updates, "updated_at"])
            if previous is None or previous.status != Payment.Status.PAID:
                if not obj.ledger_entries.filter(entry_type="payment_capture").exists():
                    TransactionEngine.post_payment_ledger_entries(transaction_obj, obj)
        elif obj.status == Payment.Status.FAILED and obj.order.payment_status != Order.PaymentStatus.PAID:
            obj.order.mark_payment_failed()
            if transaction_obj.status != transaction_obj.Status.FAILED:
                transaction_obj.status = transaction_obj.Status.FAILED
                transaction_obj.save(update_fields=["status", "updated_at"])
        elif obj.status == Payment.Status.CANCELLED and obj.order.payment_status != Order.PaymentStatus.PAID:
            obj.order.mark_payment_cancelled()
            if transaction_obj.status != transaction_obj.Status.CANCELLED:
                transaction_obj.status = transaction_obj.Status.CANCELLED
                transaction_obj.save(update_fields=["status", "updated_at"])
        elif obj.status in {Payment.Status.PENDING, Payment.Status.REQUIRES_ACTION} and obj.order.payment_status != Order.PaymentStatus.PAID:
            obj.order.mark_payment_pending()
            next_status = transaction_obj.Status.REQUIRES_ACTION if obj.status == Payment.Status.REQUIRES_ACTION else transaction_obj.Status.PENDING
            if transaction_obj.status != next_status:
                transaction_obj.status = next_status
                transaction_obj.save(update_fields=["status", "updated_at"])


@admin.register(PaymentEvent)
class PaymentEventAdmin(admin.ModelAdmin):
    list_display = ("provider", "event_id", "event_type", "processed_at")
    list_filter = ("provider", "event_type", "processed_at")
    search_fields = ("event_id", "event_type")
    readonly_fields = ("payload", "processed_at")
