import json
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import Payment, PaymentEvent

try:
    import stripe
except ImportError:  # pragma: no cover
    stripe = None

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


class PaymentConfigurationError(Exception):
    pass


class PaymentGatewayError(Exception):
    pass


def _stripe_object_to_dict(value):
    if hasattr(value, "to_dict_recursive"):
        return value.to_dict_recursive()
    if isinstance(value, dict):
        return value
    return dict(value)


def build_return_urls(request, payment):
    return {
        "success_url": request.build_absolute_uri(reverse("payments:success", kwargs={"public_token": payment.order.public_token})),
        "cancel_url": request.build_absolute_uri(reverse("payments:cancel", kwargs={"public_token": payment.order.public_token})),
    }


class StripeService:
    @staticmethod
    def create_checkout_session(payment, request):
        if stripe is None:
            raise PaymentConfigurationError("stripe 未安装")
        if not settings.STRIPE_SECRET_KEY:
            raise PaymentConfigurationError("未配置 STRIPE_SECRET_KEY")

        stripe.api_key = settings.STRIPE_SECRET_KEY
        urls = build_return_urls(request, payment)
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
        return session.url

    @staticmethod
    def handle_webhook(payload, signature):
        if stripe is None:
            raise PaymentConfigurationError("stripe 未安装")
        if not settings.STRIPE_SECRET_KEY or not settings.STRIPE_WEBHOOK_SECRET:
            raise PaymentConfigurationError("Stripe webhook 配置缺失")

        stripe.api_key = settings.STRIPE_SECRET_KEY
        event = stripe.Webhook.construct_event(payload=payload, sig_header=signature, secret=settings.STRIPE_WEBHOOK_SECRET)
        event_data = _stripe_object_to_dict(event)
        payment_event, created = PaymentEvent.objects.get_or_create(
            provider=Payment.Provider.STRIPE,
            event_id=event_data["id"],
            defaults={"event_type": event_data["type"], "payload": event_data},
        )
        if not created:
            return payment_event, False

        if event_data["type"] == "checkout.session.completed":
            session = event_data["data"]["object"]
            payment = Payment.objects.select_related("order").get(checkout_token_or_session_id=session["id"])
            payment.status = Payment.Status.PAID
            payment.external_payment_id = session.get("payment_intent", "")
            payment.paid_at = timezone.now()
            payment.raw_payload = session
            payment.save(update_fields=["status", "external_payment_id", "paid_at", "raw_payload", "updated_at"])
            payment.order.mark_paid(payment.paid_at)
        return payment_event, True


class PayPalService:
    @staticmethod
    def _get_access_token():
        if requests is None:
            raise PaymentConfigurationError("requests 未安装")
        if not settings.PAYPAL_CLIENT_ID or not settings.PAYPAL_CLIENT_SECRET:
            raise PaymentConfigurationError("未配置 PayPal 凭证")

        response = requests.post(
            f"{settings.PAYPAL_BASE_URL}/v1/oauth2/token",
            auth=(settings.PAYPAL_CLIENT_ID, settings.PAYPAL_CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json", "Accept-Language": "en_US"},
            timeout=20,
        )
        response.raise_for_status()
        return response.json()["access_token"]

    @classmethod
    def create_order(cls, payment, request):
        access_token = cls._get_access_token()
        urls = build_return_urls(request, payment)
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": payment.order.order_number,
                    "amount": {"currency_code": payment.currency, "value": str(payment.amount)},
                }
            ],
            "payment_source": {
                "paypal": {
                    "experience_context": {
                        "return_url": urls["success_url"],
                        "cancel_url": urls["cancel_url"],
                    }
                }
            },
        }
        response = requests.post(
            f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        approve_link = next((link["href"] for link in data.get("links", []) if link.get("rel") in {"approve", "payer-action"}), "")
        payment.checkout_token_or_session_id = data.get("id", "")
        payment.approval_url = approve_link
        payment.status = Payment.Status.REQUIRES_ACTION
        payment.raw_payload = data
        payment.save(update_fields=["checkout_token_or_session_id", "approval_url", "status", "raw_payload", "updated_at"])
        return approve_link

    @classmethod
    def capture_order(cls, payment):
        access_token = cls._get_access_token()
        response = requests.post(
            f"{settings.PAYPAL_BASE_URL}/v2/checkout/orders/{payment.checkout_token_or_session_id}/capture",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        if PaymentEvent.objects.filter(provider=Payment.Provider.PAYPAL, event_id=data.get("id", "")).exists():
            return data, False
        PaymentEvent.objects.create(
            provider=Payment.Provider.PAYPAL,
            event_id=data.get("id", payment.checkout_token_or_session_id),
            event_type="paypal.order.captured",
            payload=data,
        )
        payment.status = Payment.Status.PAID
        payment.external_payment_id = data.get("id", "")
        payment.paid_at = timezone.now()
        payment.raw_payload = data
        payment.save(update_fields=["status", "external_payment_id", "paid_at", "raw_payload", "updated_at"])
        payment.order.mark_paid(payment.paid_at)
        return data, True


def create_payment_redirect(payment, request):
    if payment.provider == Payment.Provider.STRIPE:
        return StripeService.create_checkout_session(payment, request)
    if payment.provider == Payment.Provider.PAYPAL:
        return PayPalService.create_order(payment, request)
    raise PaymentGatewayError(f"不支持的支付方式：{payment.provider}")
