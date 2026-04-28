from .engine import TransactionEngine


class OrderHub:
    @staticmethod
    def create_purchase_transaction(order, payment):
        return TransactionEngine.start_checkout_transaction(order, payment)

    @staticmethod
    def attach_retry_payment(transaction_obj, payment):
        return TransactionEngine.attach_payment_attempt(transaction_obj, payment, source="retry")
