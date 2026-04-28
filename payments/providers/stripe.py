from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import IntegrityError, transaction

from transactions.engine import TransactionEngine
from transactions.models import Refund
from transactions.services import confirm_payment_succeeded, mark_payment_requires_action

from payments.models import Payment, PaymentEvent

try:
    import stripe
except ImportError:  # pragma: no cover
    stripe = None


class StripeService:
    @staticmethod
    def create_checkout_session(payment, request):
        from payments.services import PaymentConfigurationError, _stripe_object_to_dict, build_return_urls

        if stripe is None:
            raise PaymentConfigurationError("stripe 未安装")
        if not settings.STRIPE_SECRET_KEY:
            raise PaymentConfigurationError("未配置 STRIPE_SECRET_KEY")

        stripe.api_key = settings.STRIPE_SECRET_KEY
        urls = build_return_urls(request, payment, stripe_checkout=True)
        session = stripe.checkout.Session.create(
            mode="payment",
            success_url=urls["success_url"],
            cancel_url=urls["cancel_url"],
            customer_email=payment.order.customer_email,
            metadata={"order_id": str(payment.order_id), "payment_id": str(payment.id)},
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": payment.currency.lower(),
                        "unit_amount": int((payment.amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
                        "product_data": {"name": f"Order {payment.order.order_number}"},
                    },
                }
            ],
        )
        payment.checkout_token_or_session_id = session.id
        payment.approval_url = session.url or ""
        payment.status = Payment.Status.REQUIRES_ACTION
        payment.raw_payload = _stripe_object_to_dict(session)
        payment.save(update_fields=["checkout_token_or_session_id", "approval_url", "status", "raw_payload", "updated_at"])
        payment.order.mark_payment_pending()
        mark_payment_requires_action(payment, source="stripe.checkout_session", payload=payment.raw_payload)
        return session.url

    @staticmethod
    def _get_payment_for_session(session):
        from payments.services import PaymentVerificationError, _normalize_currency, _to_decimal_amount

        metadata = session.get("metadata") or {}
        payment_id = metadata.get("payment_id")
        order_id = metadata.get("order_id")
        if not payment_id or not order_id:
            raise PaymentVerificationError("Stripe session metadata 不完整")

        payment = Payment.objects.select_related("order").get(pk=payment_id)
        if str(payment.order_id) != str(order_id):
            raise PaymentVerificationError("Stripe session 与订单不匹配")
        if session.get("id") != payment.checkout_token_or_session_id:
            raise PaymentVerificationError("Stripe session 与支付尝试不匹配")

        amount_total = session.get("amount_total")
        currency = session.get("currency")
        if amount_total is None or not currency:
            raise PaymentVerificationError("Stripe session 缺少金额或币种")
        if _to_decimal_amount(amount_total, cents=True) != payment.amount:
            raise PaymentVerificationError("Stripe session 金额不匹配")
        if _normalize_currency(currency) != _normalize_currency(payment.currency):
            raise PaymentVerificationError("Stripe session 币种不匹配")
        return payment

    @classmethod
    def handle_webhook(cls, payload, signature):
        from payments.services import (
            PaymentConfigurationError,
            PaymentVerificationError,
            PaymentWebhookProcessingError,
            PaymentWebhookValidationError,
            _stripe_object_to_dict,
        )

        if stripe is None:
            raise PaymentConfigurationError("stripe 未安装")
        if not settings.STRIPE_SECRET_KEY or not settings.STRIPE_WEBHOOK_SECRET:
            raise PaymentConfigurationError("Stripe webhook 配置缺失")

        stripe.api_key = settings.STRIPE_SECRET_KEY
        try:
            event = stripe.Webhook.construct_event(payload=payload, sig_header=signature, secret=settings.STRIPE_WEBHOOK_SECRET)
        except Exception as exc:
            raise PaymentWebhookValidationError("invalid webhook") from exc

        event_data = _stripe_object_to_dict(event)
        existing_event = PaymentEvent.objects.filter(provider=Payment.Provider.STRIPE, event_id=event_data["id"]).first()
        if existing_event is not None:
            return existing_event, False

        try:
            with transaction.atomic():
                if event_data["type"] == "checkout.session.completed":
                    session = event_data["data"]["object"]
                    payment = cls._get_payment_for_session(session)
                    confirm_payment_succeeded(
                        payment,
                        source="stripe.webhook",
                        idempotency_key=f"stripe:{event_data['id']}",
                        external_payment_id=session.get("payment_intent", ""),
                        payload=session,
                    )
                payment_event = PaymentEvent.objects.create(
                    provider=Payment.Provider.STRIPE,
                    event_id=event_data["id"],
                    event_type=event_data["type"],
                    payload=event_data,
                )
        except IntegrityError:
            existing_event = PaymentEvent.objects.get(provider=Payment.Provider.STRIPE, event_id=event_data["id"])
            return existing_event, False
        except PaymentVerificationError as exc:
            raise PaymentWebhookProcessingError(str(exc)) from exc
        except Exception as exc:
            raise PaymentWebhookProcessingError("webhook processing failed") from exc
        return payment_event, True

    @staticmethod
    def create_refund(refund):
        from payments.services import PaymentConfigurationError, _stripe_object_to_dict

        if stripe is None:
            raise PaymentConfigurationError("stripe 未安装")
        if not settings.STRIPE_SECRET_KEY:
            raise PaymentConfigurationError("未配置 STRIPE_SECRET_KEY")

        stripe.api_key = settings.STRIPE_SECRET_KEY
        stripe_refund = stripe.Refund.create(
            payment_intent=refund.payment.external_payment_id,
            amount=int((refund.amount * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)),
            metadata={
                "refund_id": str(refund.id),
                "transaction_id": str(refund.transaction_id),
                "payment_id": str(refund.payment_id),
            },
        )
        payload = _stripe_object_to_dict(stripe_refund)
        refund.status = Refund.Status.PROCESSING if payload.get("status") not in {"succeeded", "failed"} else (
            Refund.Status.SUCCEEDED if payload.get("status") == "succeeded" else Refund.Status.FAILED
        )
        refund.provider_refund_id = payload.get("id", "")
        refund.raw_payload = payload
        refund.save(update_fields=["status", "provider_refund_id", "raw_payload", "updated_at"])
        if refund.status == Refund.Status.SUCCEEDED:
            TransactionEngine.mark_refund_succeeded(
                refund,
                source="stripe.refund",
                idempotency_key=f"stripe-refund:{payload.get('id', refund.id)}",
                provider_refund_id=payload.get("id", ""),
                payload=payload,
            )
        return payload
