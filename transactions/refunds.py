from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from payments.services import PaymentGatewayError, PayPalService, StripeService

from .engine import TransactionEngine
from .models import Refund, TransactionEvent


class RefundCenter:
    @staticmethod
    @transaction.atomic
    def create_request(transaction_obj, *, payment=None, amount, currency, reason=""):
        transaction_obj = transaction_obj.__class__.objects.select_for_update().get(pk=transaction_obj.pk)
        amount = Decimal(str(amount))
        if amount <= Decimal("0.00"):
            raise ValueError("退款金额必须大于 0")
        if transaction_obj.status not in {transaction_obj.Status.PAID, transaction_obj.Status.PARTIALLY_REFUNDED}:
            raise ValueError("当前交易不支持退款")

        paid_payment = payment or transaction_obj.payment_attempts.filter(status="paid").order_by("-paid_at", "-id").first()
        if paid_payment is None:
            raise ValueError("未找到可退款的支付记录")

        refunded_amount = transaction_obj.refunds.filter(status__in=[Refund.Status.REQUESTED, Refund.Status.PROCESSING, Refund.Status.SUCCEEDED]).aggregate(total=models.Sum("amount"))["total"] or Decimal("0.00")
        if refunded_amount + amount > transaction_obj.amount:
            raise ValueError("退款金额超过可退余额")

        refund = Refund.objects.create(
            transaction=transaction_obj,
            payment=paid_payment,
            amount=amount,
            currency=currency,
            reason=reason,
        )
        TransactionEngine.record_event(
            transaction_obj,
            event_type=TransactionEvent.Type.REFUND_REQUESTED,
            source="refund.request",
            idempotency_key=f"refund-request:{refund.id}",
            payment=paid_payment,
            payload={"refund_id": refund.id, "amount": str(refund.amount)},
        )
        return refund

    @staticmethod
    def submit(refund):
        payment = refund.payment
        if payment.provider == payment.Provider.STRIPE:
            return StripeService.create_refund(refund)
        if payment.provider == payment.Provider.PAYPAL:
            return PayPalService.create_refund(refund)
        raise PaymentGatewayError(f"不支持的退款方式：{payment.provider}")

    @staticmethod
    @transaction.atomic
    def mark_processing(refund, *, payload=None, operator_notes=""):
        refund = Refund.objects.select_for_update().get(pk=refund.pk)
        if refund.status == Refund.Status.SUCCEEDED:
            return refund
        refund.status = Refund.Status.PROCESSING
        refund.submitted_at = refund.submitted_at or timezone.now()
        refund.operator_notes = operator_notes or refund.operator_notes
        if payload is not None:
            refund.raw_payload = payload
        refund.save(update_fields=["status", "submitted_at", "operator_notes", "raw_payload", "updated_at"])
        return refund

    @staticmethod
    @transaction.atomic
    def mark_succeeded(refund, *, payload=None, provider_refund_id="manual", source="refund.manual_success"):
        payload = payload or {"manual": True}
        refund = Refund.objects.select_related("transaction", "payment").get(pk=refund.pk)
        updated_refund, _ = TransactionEngine.mark_refund_succeeded(
            refund,
            source=source,
            idempotency_key=f"manual-refund-success:{refund.id}:{provider_refund_id or 'manual'}",
            provider_refund_id=provider_refund_id or f"manual-{refund.id}",
            payload=payload,
        )
        updated_refund.completed_at = timezone.now()
        updated_refund.operator_notes = updated_refund.operator_notes
        updated_refund.save(update_fields=["completed_at", "updated_at"])
        return updated_refund

    @staticmethod
    @transaction.atomic
    def mark_failed(refund, *, payload, failure_reason=""):
        refund = Refund.objects.select_for_update().get(pk=refund.pk)
        refund.status = Refund.Status.FAILED
        refund.failure_reason = failure_reason
        refund.raw_payload = payload
        refund.completed_at = timezone.now()
        refund.save(update_fields=["status", "failure_reason", "raw_payload", "completed_at", "updated_at"])
        TransactionEngine.record_event(
            refund.transaction,
            event_type=TransactionEvent.Type.REFUND_FAILED,
            source="refund.failure",
            idempotency_key=f"refund-failed:{refund.id}",
            payment=refund.payment,
            payload=payload,
        )
        return refund
