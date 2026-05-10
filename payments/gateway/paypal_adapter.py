from payments.providers import PayPalService

from .base import BasePaymentGateway


class PayPalGatewayAdapter(BasePaymentGateway):
    provider = "paypal"

    def create_payment(self, *, payment, request=None, metadata=None):
        approval_url = PayPalService.create_order(payment, request)
        return {
            "provider_payment_id": payment.external_payment_id,
            "provider_session_id": payment.checkout_token_or_session_id,
            "approval_url": approval_url,
            "status": payment.status,
            "payload": payment.raw_payload,
        }

    def capture_payment(self, *, payment, payload=None):
        data, _created = PayPalService.capture_order(payment)
        payment.refresh_from_db()
        return {
            "provider_payment_id": payment.external_payment_id,
            "provider_session_id": payment.checkout_token_or_session_id,
            "status": payment.status,
            "payload": data,
        }

    def refund_payment(self, *, refund):
        payload = PayPalService.create_refund(refund)
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
