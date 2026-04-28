from decimal import Decimal

from django.conf import settings
from django.urls import reverse

from .models import Payment
from .providers import PayPalService, StripeService
from .providers.paypal import requests as paypal_requests
from .providers.stripe import stripe


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
        return bool(settings.PAYPAL_CLIENT_ID and settings.PAYPAL_CLIENT_SECRET) and paypal_requests is not None
    return False


def get_available_payment_provider_choices():
    return [choice for choice in Payment.Provider.choices if is_payment_provider_available(choice[0])]


def _observe_provider_redirect(payment, redirect_url):
    if payment.transaction_id is None:
        return
    try:
        from transactions.services import observe_risk

        observe_risk(
            payment.transaction,
            phase="provider_redirect_creation",
            payload={
                "transaction_id": payment.transaction_id,
                "payment_id": payment.id,
                "order_id": payment.order_id,
                "provider": payment.provider,
                "provider_session_id": payment.checkout_token_or_session_id,
                "approval_url": payment.approval_url,
                "redirect_url": redirect_url,
            },
        )
    except Exception:
        pass


def create_payment_redirect(payment, request):
    if payment.provider == Payment.Provider.STRIPE:
        redirect_url = StripeService.create_checkout_session(payment, request)
        _observe_provider_redirect(payment, redirect_url)
        return redirect_url
    if payment.provider == Payment.Provider.PAYPAL:
        redirect_url = PayPalService.create_order(payment, request)
        _observe_provider_redirect(payment, redirect_url)
        return redirect_url
    raise PaymentGatewayError(f"不支持的支付方式：{payment.provider}")
