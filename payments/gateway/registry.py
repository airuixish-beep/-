from payments.models import Payment

from .paypal_adapter import PayPalGatewayAdapter
from .stripe_adapter import StripeGatewayAdapter


class PaymentGatewayRegistry:
    GATEWAYS = {
        Payment.Provider.STRIPE: StripeGatewayAdapter(),
        Payment.Provider.PAYPAL: PayPalGatewayAdapter(),
    }

    @classmethod
    def get(cls, provider):
        try:
            return cls.GATEWAYS[provider]
        except KeyError as exc:
            raise ValueError(f"Unsupported payment provider: {provider}") from exc
