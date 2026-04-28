from decimal import Decimal
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from orders.models import Order
from payments.models import Payment
from products.models import Product

from .engine import TransactionEngine
from .models import LedgerEntry, ReconciliationItem, ReconciliationRun, Refund, RiskAssessment, Transaction, TransactionEvent
from .reconciliation import ReconciliationService
from .refunds import RefundCenter
from .risk import RiskService
from .services import get_or_create_purchase_transaction


class RiskServiceTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Risk Product",
            slug="risk-product",
            sku="SKU-RISK",
            price=Decimal("320.00"),
            currency=Product.Currency.USD,
            stock_quantity=10,
            is_active=True,
            is_purchasable=True,
        )
        self.order = Order.objects.create(
            customer_name="Nina",
            customer_email="nina@example.com",
            shipping_country="US",
            shipping_city="San Jose",
            shipping_postal_code="95112",
            shipping_address_line1="2 Market St",
            shipping_amount=Decimal("10.00"),
            currency=Product.Currency.USD,
            subtotal_amount=Decimal("320.00"),
            total_amount=Decimal("330.00"),
        )
        self.payment = Payment.objects.create(
            order=self.order,
            provider=Payment.Provider.STRIPE,
            amount=Decimal("330.00"),
            currency="USD",
        )
        self.transaction = Transaction.objects.create(
            order=self.order,
            kind=Transaction.Kind.PURCHASE,
            provider=self.payment.provider,
            amount=self.payment.amount,
            currency=self.payment.currency,
        )
        self.payment.transaction = self.transaction
        self.payment.save(update_fields=["transaction", "updated_at"])

    def test_evaluate_marks_high_amount_for_review(self):
        score, decision, triggered_rules = RiskService.evaluate(
            self.transaction,
            payload={
                "phase": "pre_payment_checkout",
                "amount": "330.00",
                "customer_email": self.order.customer_email,
                "is_retry": False,
            },
        )

        self.assertEqual(decision, RiskAssessment.Decision.REVIEW)
        self.assertGreaterEqual(score, 40)
        self.assertEqual(triggered_rules[0]["code"], "high_amount")

    def test_evaluate_marks_recent_failed_attempts_for_review(self):
        failed_order = Order.objects.create(
            customer_name="Nina",
            customer_email="nina@example.com",
            shipping_country="US",
            shipping_city="San Jose",
            shipping_postal_code="95112",
            shipping_address_line1="2 Market St",
            shipping_amount=Decimal("10.00"),
            currency=Product.Currency.USD,
        )
        Payment.objects.create(
            order=failed_order,
            provider=Payment.Provider.STRIPE,
            amount=Decimal("10.00"),
            currency="USD",
            status=Payment.Status.FAILED,
        )
        Payment.objects.create(
            order=failed_order,
            provider=Payment.Provider.STRIPE,
            amount=Decimal("10.00"),
            currency="USD",
            status=Payment.Status.CANCELLED,
        )

        score, decision, triggered_rules = RiskService.evaluate(
            self.transaction,
            payload={
                "phase": "pre_payment_checkout",
                "amount": "10.00",
                "customer_email": self.order.customer_email,
                "is_retry": False,
            },
        )

        self.assertEqual(decision, RiskAssessment.Decision.REVIEW)
        self.assertGreaterEqual(score, 35)
        self.assertEqual(triggered_rules[0]["code"], "repeated_failed_payments")

    def test_evaluate_marks_retry_payment_for_review(self):
        Payment.objects.create(
            order=self.order,
            provider=Payment.Provider.STRIPE,
            amount=self.order.total_amount,
            currency=self.order.currency,
            transaction=self.transaction,
        )

        score, decision, triggered_rules = RiskService.evaluate(
            self.transaction,
            payload={
                "phase": "pre_payment_retry",
                "amount": "10.00",
                "customer_email": self.order.customer_email,
                "is_retry": True,
            },
        )

        self.assertEqual(decision, RiskAssessment.Decision.REVIEW)
        self.assertGreaterEqual(score, 25)
        self.assertEqual(triggered_rules[0]["code"], "retry_payment")


class TransactionIntegrationTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Transaction Product",
            slug="transaction-product",
            sku="SKU-TX",
            price=Decimal("50.00"),
            currency=Product.Currency.USD,
            stock_quantity=5,
            is_active=True,
            is_purchasable=True,
        )
        self.order = Order.objects.create(
            customer_name="Tracy",
            customer_email="tracy@example.com",
            shipping_country="US",
            shipping_city="Portland",
            shipping_postal_code="97201",
            shipping_address_line1="1 River Rd",
            shipping_amount=Decimal("10.00"),
            currency=Product.Currency.USD,
            subtotal_amount=Decimal("50.00"),
            total_amount=Decimal("60.00"),
        )
        self.order.items.create(
            product=self.product,
            product_name_snapshot=self.product.name,
            sku_snapshot=self.product.sku,
            unit_price=self.product.price,
            quantity=1,
        )
        self.payment = Payment.objects.create(
            order=self.order,
            provider=Payment.Provider.STRIPE,
            amount=Decimal("60.00"),
            currency="USD",
            checkout_token_or_session_id="cs_tx_123",
        )

    def test_get_or_create_purchase_transaction_links_payment(self):
        transaction_obj = get_or_create_purchase_transaction(self.order, self.payment)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.transaction_id, transaction_obj.id)
        self.assertEqual(transaction_obj.status, Transaction.Status.INITIATED)
        self.assertEqual(transaction_obj.events.count(), 1)
        self.assertEqual(transaction_obj.events.first().event_type, TransactionEvent.Type.INITIATED)

    def test_confirm_payment_succeeded_is_idempotent_and_posts_ledger(self):
        transaction_obj = get_or_create_purchase_transaction(self.order, self.payment)

        first_tx, first_created = TransactionEngine.confirm_payment_succeeded(
            self.payment,
            source="test",
            idempotency_key="evt:test:1",
            external_payment_id="pi_test_1",
            payload={"ok": True},
        )
        second_tx, second_created = TransactionEngine.confirm_payment_succeeded(
            self.payment,
            source="test",
            idempotency_key="evt:test:1",
            external_payment_id="pi_test_1",
            payload={"ok": True},
        )

        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        self.product.refresh_from_db()
        transaction_obj.refresh_from_db()

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_tx.id, second_tx.id)
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(transaction_obj.status, Transaction.Status.PAID)
        self.assertEqual(transaction_obj.risk_status, Transaction.RiskStatus.ALLOW)
        self.assertEqual(self.product.stock_quantity, 4)
        self.assertEqual(LedgerEntry.objects.filter(transaction=transaction_obj, entry_type="payment_capture").count(), 2)
        self.assertEqual(RiskAssessment.objects.filter(transaction=transaction_obj).count(), 1)
        self.assertEqual(RiskAssessment.objects.get(transaction=transaction_obj).payload["phase"], "post_payment_success")

    def test_mark_payment_failed_sets_transaction_failed(self):
        transaction_obj = get_or_create_purchase_transaction(self.order, self.payment)

        TransactionEngine.mark_payment_failed(
            self.payment,
            source="test",
            idempotency_key="evt:failed:1",
            payload={"ok": False},
        )

        self.order.refresh_from_db()
        self.payment.refresh_from_db()
        transaction_obj.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.FAILED)
        self.assertEqual(transaction_obj.status, Transaction.Status.FAILED)

    @override_settings(STRIPE_SECRET_KEY="sk_test")
    @patch("payments.providers.stripe.stripe")
    def test_refund_center_submits_stripe_refund_and_posts_ledger(self, mock_stripe):
        transaction_obj = get_or_create_purchase_transaction(self.order, self.payment)
        TransactionEngine.confirm_payment_succeeded(
            self.payment,
            source="test",
            idempotency_key="evt:paid:refund",
            external_payment_id="pi_refundable",
            payload={"ok": True},
        )
        mock_stripe.Refund.create.return_value = {
            "id": "re_123",
            "status": "succeeded",
        }

        refund = RefundCenter.create_request(
            transaction_obj,
            amount=Decimal("20.00"),
            currency="USD",
            reason="customer request",
        )
        payload = RefundCenter.submit(refund)

        refund.refresh_from_db()
        transaction_obj.refresh_from_db()
        self.assertEqual(payload["id"], "re_123")
        self.assertEqual(refund.status, Refund.Status.SUCCEEDED)
        self.assertEqual(transaction_obj.status, Transaction.Status.PARTIALLY_REFUNDED)
        self.assertEqual(LedgerEntry.objects.filter(refund=refund, entry_type="refund").count(), 2)

    def test_manual_refund_status_helpers_update_refund_and_transaction(self):
        transaction_obj = get_or_create_purchase_transaction(self.order, self.payment)
        TransactionEngine.confirm_payment_succeeded(
            self.payment,
            source="test",
            idempotency_key="evt:paid:manual-refund",
            external_payment_id="pi_manual_refund",
            payload={"ok": True},
        )
        refund = RefundCenter.create_request(
            transaction_obj,
            amount=Decimal("20.00"),
            currency="USD",
            reason="manual review",
        )

        RefundCenter.mark_processing(refund, payload={"step": "processing"}, operator_notes="started manually")
        refund.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.PROCESSING)
        self.assertIsNotNone(refund.submitted_at)
        self.assertEqual(refund.operator_notes, "started manually")

        RefundCenter.mark_succeeded(refund, payload={"manual": True}, provider_refund_id="manual-123")
        refund.refresh_from_db()
        transaction_obj.refresh_from_db()
        self.assertEqual(refund.status, Refund.Status.SUCCEEDED)
        self.assertEqual(refund.provider_refund_id, "manual-123")
        self.assertIsNotNone(refund.completed_at)
        self.assertEqual(transaction_obj.status, Transaction.Status.PARTIALLY_REFUNDED)

    def test_refund_center_rejects_over_refund(self):
        transaction_obj = get_or_create_purchase_transaction(self.order, self.payment)
        TransactionEngine.confirm_payment_succeeded(
            self.payment,
            source="test",
            idempotency_key="evt:paid:over-refund",
            external_payment_id="pi_refundable_2",
            payload={"ok": True},
        )
        Refund.objects.create(
            transaction=transaction_obj,
            payment=self.payment,
            amount=Decimal("50.00"),
            currency="USD",
            status=Refund.Status.SUCCEEDED,
        )

        with self.assertRaisesMessage(ValueError, "退款金额超过可退余额"):
            RefundCenter.create_request(
                transaction_obj,
                amount=Decimal("20.00"),
                currency="USD",
            )

    def test_reconciliation_detects_missing_ledger(self):
        transaction_obj = get_or_create_purchase_transaction(self.order, self.payment)
        self.payment.status = Payment.Status.PAID
        self.payment.external_payment_id = "pi_missing_ledger"
        self.payment.save(update_fields=["status", "external_payment_id", "updated_at"])
        transaction_obj.status = Transaction.Status.PAID
        transaction_obj.save(update_fields=["status", "updated_at"])

        run = ReconciliationService.run_internal_check()

        self.assertEqual(run.status, ReconciliationRun.Status.SUCCEEDED)
        self.assertTrue(
            ReconciliationItem.objects.filter(
                run=run,
                payment=self.payment,
                kind=ReconciliationItem.Kind.PAID_WITHOUT_LEDGER,
            ).exists()
        )

    def test_reconcile_transactions_command_runs(self):
        call_command("reconcile_transactions")
        self.assertEqual(ReconciliationRun.objects.count(), 1)
