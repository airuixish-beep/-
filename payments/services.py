import json
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import IntegrityError, transaction
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


class PaymentVerificationError(PaymentGatewayError):
    pass


class PaymentWebhookValidationError(PaymentGatewayError):
    pass


class PaymentWebhookProcessingError(PaymentGatewayError):
    pass


def _stripe_object_to_dict(value):
    if hasattr(value, "to_dict_recursive"):
        return value.to_dict_recursive()
    if isinstance(value, dict):
        return value
    return dict(value)


def _append_query(url, params):
    query = "&".join(f"{key}={value}" for key, value in params.items() if value not in {None, ""})
    return f"{url}?{query}" if query else url


def _to_decimal_amount(value, *, cents=False):
    amount = Decimal(str(value))
    if cents:
        amount = amount / Decimal("100")
    return amount.quantize(Decimal("0.01"))


def _normalize_currency(value):
    return str(value or "").upper()


def _mark_payment_paid(payment, *, external_payment_id, payload, paid_at=None):
    payment.status = Payment.Status.PAID
    payment.external_payment_id = external_payment_id
    payment.paid_at = paid_at or timezone.now()
    payment.raw_payload = payload
    payment.save(update_fields=["status", "external_payment_id", "paid_at", "raw_payload", "updated_at"])


def build_return_urls(request, payment, *, stripe_checkout=False):
    success_url = request.build_absolute_uri(reverse("payments:success", kwargs={"public_token": payment.order.public_token}))
    cancel_url = request.build_absolute_uri(reverse("payments:cancel", kwargs={"public_token": payment.order.public_token}))
    success_query = {"attempt": payment.id}
    if stripe_checkout:
        success_query["session_id"] = "{CHECKOUT_SESSION_ID}"
    return {
        "success_url": _append_query(success_url, success_query),
        "cancel_url": _append_query(cancel_url, {"attempt": payment.id}),
    }


def is_payment_provider_available(provider):
    if provider == Payment.Provider.STRIPE:
        return bool(settings.STRIPE_SECRET_KEY) and stripe is not None
    if provider == Payment.Provider.PAYPAL:
        return bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET) and requests is not None
    return False


def get_available_payment_provider_choices():
    return [choice for choice in Payment.Provider.choices if is_payment_provider_available(choice[0])]


class StripeService:
    @staticmethod
    def create_checkout_session(payment, request):
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
        return session.url

    @staticmethod
    def _get_payment_for_session(session):
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
                    payment.order.mark_paid()
                    _mark_payment_paid(
                        payment,
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

    @staticmethod
    def _verify_capture_response(payment, data):
        if data.get("id") != payment.checkout_token_or_session_id:
            raise PaymentVerificationError("PayPal order 与支付尝试不匹配")

        purchase_units = data.get("purchase_units") or []
        if not purchase_units:
            raise PaymentVerificationError("PayPal 返回缺少 purchase_units")

        purchase_unit = purchase_units[0]
        if purchase_unit.get("reference_id") != payment.order.order_number:
            raise PaymentVerificationError("PayPal order 与订单不匹配")

        captures = ((purchase_unit.get("payments") or {}).get("captures") or [])
        if not captures:
            raise PaymentVerificationError("PayPal capture 缺失")

        capture = captures[0]
        amount_info = capture.get("amount") or purchase_unit.get("amount") or {}
        if _to_decimal_amount(amount_info.get("value")) != payment.amount:
            raise PaymentVerificationError("PayPal 金额不匹配")
        if _normalize_currency(amount_info.get("currency_code")) != _normalize_currency(payment.currency):
            raise PaymentVerificationError("PayPal 币种不匹配")
        if capture.get("status") != "COMPLETED":
            raise PaymentVerificationError("PayPal capture 未完成")
        return capture

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
        capture = cls._verify_capture_response(payment, data)
        event_id = capture.get("id") or data.get("id") or payment.checkout_token_or_session_id
        if PaymentEvent.objects.filter(provider=Payment.Provider.PAYPAL, event_id=event_id).exists():
            return data, False

        with transaction.atomic():
            payment.order.mark_paid()
            _mark_payment_paid(
                payment,
                external_payment_id=event_id,
                payload=data,
            )
            try:
                PaymentEvent.objects.create(
                    provider=Payment.Provider.PAYPAL,
                    event_id=event_id,
                    event_type="paypal.order.captured",
                    payload=data,
                )
            except IntegrityError:
                return data, False
        return data, True


def create_payment_redirect(payment, request):
    if payment.provider == Payment.Provider.STRIPE:
        return StripeService.create_checkout_session(payment, request)
    if payment.provider == Payment.Provider.PAYPAL:
        return PayPalService.create_order(payment, request)
    raise PaymentGatewayError(f"不支持的支付方式：{payment.provider}")
