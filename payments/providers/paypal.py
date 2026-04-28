import json

from django.conf import settings
from django.db import IntegrityError, transaction

from transactions.engine import TransactionEngine
from transactions.models import Refund
from transactions.services import confirm_payment_succeeded, mark_payment_requires_action

from payments.models import Payment, PaymentEvent

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


class PayPalService:
    @staticmethod
    def _get_access_token():
        from payments.services import PaymentConfigurationError

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
        from payments.services import build_return_urls

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
        payment.order.mark_payment_pending()
        mark_payment_requires_action(payment, source="paypal.create_order", payload=data)
        return approve_link

    @staticmethod
    def _verify_capture_response(payment, data):
        from payments.services import PaymentVerificationError, _normalize_currency, _to_decimal_amount

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
            confirm_payment_succeeded(
                payment,
                source="paypal.capture",
                idempotency_key=f"paypal:{event_id}",
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

    @classmethod
    def create_refund(cls, refund):
        access_token = cls._get_access_token()
        capture_id = refund.payment.external_payment_id
        response = requests.post(
            f"{settings.PAYPAL_BASE_URL}/v2/payments/captures/{capture_id}/refund",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            data=json.dumps(
                {
                    "amount": {
                        "value": str(refund.amount),
                        "currency_code": refund.currency,
                    },
                    "note_to_payer": refund.reason,
                }
            ),
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        refund_id = data.get("id", "")
        refund.status = Refund.Status.PROCESSING if data.get("status") not in {"COMPLETED", "FAILED"} else (
            Refund.Status.SUCCEEDED if data.get("status") == "COMPLETED" else Refund.Status.FAILED
        )
        refund.provider_refund_id = refund_id
        refund.raw_payload = data
        refund.save(update_fields=["status", "provider_refund_id", "raw_payload", "updated_at"])
        if refund.status == Refund.Status.SUCCEEDED:
            TransactionEngine.mark_refund_succeeded(
                refund,
                source="paypal.refund",
                idempotency_key=f"paypal-refund:{refund_id or refund.id}",
                provider_refund_id=refund_id,
                payload=data,
            )
        return data
