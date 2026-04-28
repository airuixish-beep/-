from django.db import IntegrityError, models, transaction
from django.utils import timezone

from decimal import Decimal

from payments.models import Payment

from .models import LedgerAccount, LedgerEntry, Refund, Transaction, TransactionEvent
from .risk import RiskService

LEDGER_ACCOUNT_DEFINITIONS = (
    ("provider_clearing_stripe", "Stripe 在途资金"),
    ("provider_clearing_paypal", "PayPal 在途资金"),
    ("customer_receipts", "客户收款"),
    ("payment_fees", "支付手续费"),
    ("refunds", "退款"),
    ("net_revenue", "净收入"),
)


class TransactionEngine:
    @staticmethod
    def ensure_ledger_accounts():
        for code, name in LEDGER_ACCOUNT_DEFINITIONS:
            LedgerAccount.objects.get_or_create(code=code, defaults={"name": name})

    @staticmethod
    @transaction.atomic
    def start_checkout_transaction(order, payment):
        tx = Transaction.objects.create(
            order=order,
            kind=Transaction.Kind.PURCHASE,
            provider=payment.provider,
            status=Transaction.Status.INITIATED,
            amount=payment.amount,
            currency=payment.currency,
        )
        payment.transaction = tx
        payment.save(update_fields=["transaction", "updated_at"])
        TransactionEngine.record_event(
            tx,
            event_type=TransactionEvent.Type.INITIATED,
            source="checkout",
            idempotency_key=f"checkout:{order.id}:{payment.id}",
            payment=payment,
            payload={"order_id": order.id, "payment_id": payment.id},
        )
        return tx

    @staticmethod
    @transaction.atomic
    def attach_payment_attempt(transaction_obj, payment, *, source):
        if payment.transaction_id == transaction_obj.id:
            return payment
        payment.transaction = transaction_obj
        payment.save(update_fields=["transaction", "updated_at"])
        TransactionEngine.record_event(
            transaction_obj,
            event_type=TransactionEvent.Type.INITIATED,
            source=source,
            idempotency_key=f"attach:{payment.id}",
            payment=payment,
            payload={"payment_id": payment.id},
        )
        return payment

    @staticmethod
    @transaction.atomic
    def mark_payment_pending(payment, *, source, payload=None):
        payment = Payment.objects.select_related("order", "transaction").select_for_update().get(pk=payment.pk)
        tx = payment.transaction
        if tx is None:
            tx = TransactionEngine.start_checkout_transaction(payment.order, payment)
            payment.refresh_from_db(fields=["transaction"])
            tx = payment.transaction
        tx.provider = payment.provider
        tx.status = Transaction.Status.PENDING
        tx.amount = payment.amount
        tx.currency = payment.currency
        tx.save(update_fields=["provider", "status", "amount", "currency", "updated_at"])
        payment.order.mark_payment_pending()
        TransactionEngine.record_event(
            tx,
            event_type=TransactionEvent.Type.PAYMENT_PENDING,
            source=source,
            idempotency_key=f"pending:{payment.id}:{payment.status}",
            payment=payment,
            payload=payload or {},
        )
        return tx

    @staticmethod
    @transaction.atomic
    def mark_payment_requires_action(payment, *, source, payload=None):
        payment = Payment.objects.select_related("order", "transaction").select_for_update().get(pk=payment.pk)
        tx = payment.transaction
        if tx is None:
            tx = TransactionEngine.start_checkout_transaction(payment.order, payment)
            payment.refresh_from_db(fields=["transaction"])
            tx = payment.transaction
        tx.provider = payment.provider
        tx.status = Transaction.Status.REQUIRES_ACTION
        tx.save(update_fields=["provider", "status", "updated_at"])
        TransactionEngine.record_event(
            tx,
            event_type=TransactionEvent.Type.PAYMENT_REQUIRES_ACTION,
            source=source,
            idempotency_key=f"requires_action:{payment.id}:{payment.checkout_token_or_session_id}",
            payment=payment,
            payload=payload or {},
        )
        return tx

    @staticmethod
    @transaction.atomic
    def confirm_payment_succeeded(payment, *, source, idempotency_key, external_payment_id, payload, paid_at=None):
        payment = Payment.objects.select_related("order", "transaction").select_for_update().get(pk=payment.pk)
        tx = payment.transaction
        if tx is None:
            tx = TransactionEngine.start_checkout_transaction(payment.order, payment)
            payment.refresh_from_db(fields=["transaction"])
            tx = payment.transaction
        tx = Transaction.objects.select_for_update().get(pk=tx.pk)

        created = TransactionEngine.record_event(
            tx,
            event_type=TransactionEvent.Type.PAYMENT_PAID,
            source=source,
            idempotency_key=idempotency_key,
            payment=payment,
            payload=payload,
        )
        if not created:
            return tx, False

        if payment.status != Payment.Status.PAID:
            payment.status = Payment.Status.PAID
            payment.external_payment_id = external_payment_id
            payment.paid_at = paid_at or timezone.now()
            payment.raw_payload = payload
            payment.save(update_fields=["status", "external_payment_id", "paid_at", "raw_payload", "updated_at"])

        tx.provider = payment.provider
        tx.status = Transaction.Status.PAID
        tx.amount = payment.amount
        tx.currency = payment.currency
        tx.paid_at = payment.paid_at
        tx.metadata = {**(tx.metadata or {}), "external_payment_id": external_payment_id}
        tx.save(update_fields=["provider", "status", "amount", "currency", "paid_at", "metadata", "updated_at"])

        payment.order.mark_paid(payment.paid_at)
        TransactionEngine.post_payment_ledger_entries(tx, payment)
        try:
            RiskService.observe(
                tx,
                score=0,
                decision=Transaction.RiskStatus.ALLOW,
                triggered_rules=[],
                payload={
                    "phase": "post_payment_success",
                    "source": source,
                    "provider": payment.provider,
                    "transaction_id": tx.id,
                    "payment_id": payment.id,
                    "order_id": payment.order_id,
                    "external_payment_id": external_payment_id,
                    "amount": str(payment.amount),
                    "currency": payment.currency,
                    "provider_payload": payload,
                },
            )
            if tx.risk_status != Transaction.RiskStatus.ALLOW:
                tx.risk_status = Transaction.RiskStatus.ALLOW
                tx.save(update_fields=["risk_status", "updated_at"])
        except Exception:
            pass
        return tx, True

    @staticmethod
    @transaction.atomic
    def mark_payment_failed(payment, *, source, idempotency_key, payload=None):
        payment = Payment.objects.select_related("order", "transaction").select_for_update().get(pk=payment.pk)
        tx = payment.transaction
        if tx is None:
            tx = TransactionEngine.start_checkout_transaction(payment.order, payment)
            payment.refresh_from_db(fields=["transaction"])
            tx = payment.transaction
        tx = Transaction.objects.select_for_update().get(pk=tx.pk)

        created = TransactionEngine.record_event(
            tx,
            event_type=TransactionEvent.Type.PAYMENT_FAILED,
            source=source,
            idempotency_key=idempotency_key,
            payment=payment,
            payload=payload or {},
        )
        if not created:
            return tx, False

        if payment.status != Payment.Status.PAID:
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=["status", "updated_at"])
            payment.order.mark_payment_failed()

        tx.provider = payment.provider
        tx.status = Transaction.Status.FAILED
        tx.save(update_fields=["provider", "status", "updated_at"])
        return tx, True

    @staticmethod
    @transaction.atomic
    def cancel_payment_attempt(payment, *, source, idempotency_key, payload=None):
        payment = Payment.objects.select_related("order", "transaction").select_for_update().get(pk=payment.pk)
        tx = payment.transaction
        if tx is None:
            tx = TransactionEngine.start_checkout_transaction(payment.order, payment)
            payment.refresh_from_db(fields=["transaction"])
            tx = payment.transaction
        tx = Transaction.objects.select_for_update().get(pk=tx.pk)

        created = TransactionEngine.record_event(
            tx,
            event_type=TransactionEvent.Type.PAYMENT_CANCELLED,
            source=source,
            idempotency_key=idempotency_key,
            payment=payment,
            payload=payload or {},
        )
        if not created:
            return tx, False

        if payment.status != Payment.Status.PAID:
            payment.status = Payment.Status.CANCELLED
            payment.save(update_fields=["status", "updated_at"])
            payment.order.mark_payment_cancelled()

        tx.provider = payment.provider
        tx.status = Transaction.Status.CANCELLED
        tx.save(update_fields=["provider", "status", "updated_at"])
        return tx, True

    @staticmethod
    def record_event(transaction_obj, *, event_type, source, idempotency_key, payment=None, payload=None):
        try:
            TransactionEvent.objects.create(
                transaction=transaction_obj,
                payment=payment,
                event_type=event_type,
                source=source,
                idempotency_key=idempotency_key,
                payload=payload or {},
            )
        except IntegrityError:
            return False
        return True

    @staticmethod
    def post_payment_ledger_entries(transaction_obj, payment):
        TransactionEngine.ensure_ledger_accounts()
        if LedgerEntry.objects.filter(transaction=transaction_obj, entry_type="payment_capture").exists():
            return

        clearing_code = f"provider_clearing_{payment.provider}"
        clearing_account = LedgerAccount.objects.get(code=clearing_code)
        receipt_account = LedgerAccount.objects.get(code="customer_receipts")

        LedgerEntry.objects.bulk_create(
            [
                LedgerEntry(
                    transaction=transaction_obj,
                    payment=payment,
                    account=clearing_account,
                    direction=LedgerEntry.Direction.DEBIT,
                    amount=payment.amount,
                    currency=payment.currency,
                    entry_type="payment_capture",
                    external_reference=payment.external_payment_id,
                ),
                LedgerEntry(
                    transaction=transaction_obj,
                    payment=payment,
                    account=receipt_account,
                    direction=LedgerEntry.Direction.CREDIT,
                    amount=payment.amount,
                    currency=payment.currency,
                    entry_type="payment_capture",
                    external_reference=payment.external_payment_id,
                ),
            ]
        )

    @staticmethod
    @transaction.atomic
    def mark_refund_succeeded(refund, *, source, idempotency_key, provider_refund_id, payload):
        refund = Refund.objects.select_related("transaction", "payment", "transaction__order").select_for_update().get(pk=refund.pk)
        tx = refund.transaction

        created = TransactionEngine.record_event(
            tx,
            event_type=TransactionEvent.Type.REFUND_SUCCEEDED,
            source=source,
            idempotency_key=idempotency_key,
            payment=refund.payment,
            payload=payload,
        )
        if not created:
            return refund, False

        refund.status = Refund.Status.SUCCEEDED
        refund.provider_refund_id = provider_refund_id
        refund.raw_payload = payload
        refund.save(update_fields=["status", "provider_refund_id", "raw_payload", "updated_at"])

        total_refunded = (
            tx.refunds.filter(status=Refund.Status.SUCCEEDED).exclude(pk=refund.pk).aggregate(total=models.Sum("amount"))["total"]
            or Decimal("0.00")
        ) + refund.amount
        tx.status = Transaction.Status.REFUNDED if total_refunded >= tx.amount else Transaction.Status.PARTIALLY_REFUNDED
        tx.metadata = {**(tx.metadata or {}), "last_refund_id": provider_refund_id}
        tx.save(update_fields=["status", "metadata", "updated_at"])

        TransactionEngine.post_refund_ledger_entries(tx, refund)
        return refund, True

    @staticmethod
    def post_refund_ledger_entries(transaction_obj, refund):
        TransactionEngine.ensure_ledger_accounts()
        if LedgerEntry.objects.filter(refund=refund, entry_type="refund").exists():
            return

        refund_account = LedgerAccount.objects.get(code="refunds")
        clearing_account = LedgerAccount.objects.get(code=f"provider_clearing_{refund.payment.provider}")
        LedgerEntry.objects.bulk_create(
            [
                LedgerEntry(
                    transaction=transaction_obj,
                    payment=refund.payment,
                    refund=refund,
                    account=refund_account,
                    direction=LedgerEntry.Direction.DEBIT,
                    amount=refund.amount,
                    currency=refund.currency,
                    entry_type="refund",
                    external_reference=refund.provider_refund_id,
                ),
                LedgerEntry(
                    transaction=transaction_obj,
                    payment=refund.payment,
                    refund=refund,
                    account=clearing_account,
                    direction=LedgerEntry.Direction.CREDIT,
                    amount=refund.amount,
                    currency=refund.currency,
                    entry_type="refund",
                    external_reference=refund.provider_refund_id,
                ),
            ]
        )
