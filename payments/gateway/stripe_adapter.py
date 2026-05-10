from payments.providers import StripeService

from .base import BasePaymentGateway


class StripeGatewayAdapter(BasePaymentGateway):
    provider = "stripe"

    def create_payment(self, *, payment, request=None, metadata=None):
        approval_url = StripeService.create_checkout_session(payment, request)
        return {
            "provider_payment_id": payment.external_payment_id,
            "provider_session_id": payment.checkout_token_or_session_id,
            "approval_url": approval_url,
            "status": payment.status,
            "payload": payment.raw_payload,
        }

    def capture_payment(self, *, payment, payload=None):
        return {
            "provider_payment_id": payment.external_payment_id,
            "provider_session_id": payment.checkout_token_or_session_id,
            "status": payment.status,
            "payload": payload or payment.raw_payload,
        }

    def refund_payment(self, *, refund):
        payload = StripeService.create_refund(refund)
        return {
            "provider_refund_id": refund.provider_refund_id,
            "status": refund.status,
            "payload": payload,
        }

    def retrieve_payment(self, *, payment):
        return {
            "provider_payment_id": payment.external_payment_id,
            "provider_session_id": payment.checkout_token_or_session_id,
            "status": payment.status,
            "payload": payment.raw_payload,
        }
