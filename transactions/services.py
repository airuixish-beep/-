from .engine import TransactionEngine
from .models import RiskAssessment, Transaction
from .order_hub import OrderHub
from .risk import RiskService


def get_or_create_purchase_transaction(order, payment):
    existing = order.transactions.filter(kind=Transaction.Kind.PURCHASE).order_by("created_at", "id").first()
    if existing is None:
        return OrderHub.create_purchase_transaction(order, payment)
    OrderHub.attach_retry_payment(existing, payment)
    return existing


def mark_payment_pending(payment, *, source, payload=None):
    return TransactionEngine.mark_payment_pending(payment, source=source, payload=payload)


def mark_payment_requires_action(payment, *, source, payload=None):
    return TransactionEngine.mark_payment_requires_action(payment, source=source, payload=payload)


def confirm_payment_succeeded(payment, *, source, idempotency_key, external_payment_id, payload, paid_at=None):
    return TransactionEngine.confirm_payment_succeeded(
        payment,
        source=source,
        idempotency_key=idempotency_key,
        external_payment_id=external_payment_id,
        payload=payload,
        paid_at=paid_at,
    )


def mark_payment_failed(payment, *, source, idempotency_key, payload=None):
    return TransactionEngine.mark_payment_failed(
        payment,
        source=source,
        idempotency_key=idempotency_key,
        payload=payload,
    )


def cancel_payment_attempt(payment, *, source, idempotency_key, payload=None):
    return TransactionEngine.cancel_payment_attempt(
        payment,
        source=source,
        idempotency_key=idempotency_key,
        payload=payload,
    )


def observe_risk(transaction_obj, *, phase, payload, score=None, decision=None, triggered_rules=None):
    return RiskService.observe(
        transaction_obj,
        score=score,
        decision=decision,
        triggered_rules=triggered_rules,
        payload={"phase": phase, **(payload or {})},
    )
