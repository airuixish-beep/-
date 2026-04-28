from django.db.models import Count
from django.utils import timezone

from payments.models import Payment

from .models import LedgerEntry, ReconciliationItem, ReconciliationRun, Refund, Transaction


class ReconciliationService:
    @staticmethod
    def run_internal_check():
        run = ReconciliationRun.objects.create()

        paid_payments = Payment.objects.filter(status=Payment.Status.PAID).select_related("transaction", "order")
        for payment in paid_payments:
            if payment.transaction_id and not LedgerEntry.objects.filter(transaction_id=payment.transaction_id, entry_type="payment_capture").exists():
                ReconciliationItem.objects.create(
                    run=run,
                    transaction=payment.transaction,
                    payment=payment,
                    kind=ReconciliationItem.Kind.PAID_WITHOUT_LEDGER,
                    payload={"payment_id": payment.id},
                )

            if payment.transaction_id and payment.transaction.amount != payment.amount:
                ReconciliationItem.objects.create(
                    run=run,
                    transaction=payment.transaction,
                    payment=payment,
                    kind=ReconciliationItem.Kind.AMOUNT_MISMATCH,
                    payload={"payment_amount": str(payment.amount), "transaction_amount": str(payment.transaction.amount)},
                )

        mismatched_transactions = Transaction.objects.filter(status=Transaction.Status.PAID).exclude(order__payment_status="paid")
        for tx in mismatched_transactions:
            ReconciliationItem.objects.create(
                run=run,
                transaction=tx,
                kind=ReconciliationItem.Kind.ORDER_TRANSACTION_MISMATCH,
                payload={"order_id": tx.order_id},
            )

        duplicate_external_ids = (
            Payment.objects.exclude(external_payment_id="")
            .values("provider", "external_payment_id")
            .annotate(total=Count("id"))
            .filter(total__gt=1)
        )
        for row in duplicate_external_ids:
            for payment in Payment.objects.filter(provider=row["provider"], external_payment_id=row["external_payment_id"]):
                ReconciliationItem.objects.create(
                    run=run,
                    transaction=payment.transaction,
                    payment=payment,
                    kind=ReconciliationItem.Kind.DUPLICATE_EXTERNAL_ID,
                    payload={"external_payment_id": payment.external_payment_id, "provider": payment.provider},
                )

        pending_refunds = Refund.objects.filter(status=Refund.Status.SUCCEEDED)
        for refund in pending_refunds:
            if not LedgerEntry.objects.filter(refund=refund, entry_type="refund").exists():
                ReconciliationItem.objects.create(
                    run=run,
                    transaction=refund.transaction,
                    payment=refund.payment,
                    kind=ReconciliationItem.Kind.PAID_WITHOUT_LEDGER,
                    payload={"refund_id": refund.id, "reason": "refund_missing_ledger"},
                )

        run.status = ReconciliationRun.Status.SUCCEEDED
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "finished_at"])
        return run
