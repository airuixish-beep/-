class BasePaymentGateway:
    provider = ""

    def create_payment(self, *, payment, request=None, metadata=None):
        raise NotImplementedError

    def capture_payment(self, *, payment, payload=None):
        raise NotImplementedError

    def refund_payment(self, *, refund):
        raise NotImplementedError

    def retrieve_payment(self, *, payment):
        raise NotImplementedError
