from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from orders.models import Order
from products.models import Product

from transactions.models import LedgerEntry, RiskAssessment, Transaction, TransactionEvent

from .models import Payment, PaymentEvent
from .services import (
    PaymentWebhookProcessingError,
    PaymentWebhookValidationError,
    PayPalService,
    StripeService,
    create_payment_redirect,
)


class PaymentRedirectObservationTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Redirect Product",
            slug="redirect-product",
            sku="SKU-REDIRECT",
            price=Decimal("50.00"),
            currency=Product.Currency.USD,
            stock_quantity=4,
            is_active=True,
            is_purchasable=True,
        )
        self.order = Order.objects.create(
            customer_name="Rita",
            customer_email="rita@example.com",
            shipping_country="US",
            shipping_city="Denver",
            shipping_postal_code="80201",
            shipping_address_line1="9 Cloud St",
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

    @patch("payments.services.StripeService.create_checkout_session", return_value="https://payments.example/stripe")
    def test_create_payment_redirect_records_provider_redirect_observation(self, mock_create):
        redirect_url = create_payment_redirect(self.payment, request=None)

        self.transaction.refresh_from_db()
        self.assertEqual(redirect_url, "https://payments.example/stripe")
        self.assertEqual(RiskAssessment.objects.filter(transaction=self.transaction).count(), 1)
        self.assertTrue(
            RiskAssessment.objects.filter(transaction=self.transaction, payload__phase="provider_redirect_creation").exists()
        )
        mock_create.assert_called_once_with(self.payment, None)


class StripeWebhookTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Webhook Product",
            slug="webhook-product",
            sku="SKU-002",
            price=Decimal("50.00"),
            currency=Product.Currency.USD,
            stock_quantity=4,
            is_active=True,
            is_purchasable=True,
        )
        self.order = Order.objects.create(
            customer_name="Bob",
            customer_email="bob@example.com",
            shipping_country="US",
            shipping_city="Seattle",
            shipping_postal_code="98101",
            shipping_address_line1="2 Pine St",
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
            checkout_token_or_session_id="cs_test_123",
        )

    @override_settings(STRIPE_SECRET_KEY="sk_test", STRIPE_WEBHOOK_SECRET="whsec_test")
    @patch("payments.providers.stripe.stripe")
    def test_stripe_webhook_is_idempotent(self, mock_stripe):
        event = {
            "id": "evt_test_123",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_intent": "pi_123",
                    "amount_total": 6000,
                    "currency": "usd",
                    "metadata": {
                        "order_id": str(self.order.id),
                        "payment_id": str(self.payment.id),
                    },
                }
            },
        }
        mock_stripe.Webhook.construct_event.return_value = event

        first_event, first_created = StripeService.handle_webhook(b"{}", "sig")
        second_event, second_created = StripeService.handle_webhook(b"{}", "sig")

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.product.refresh_from_db()

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_event.id, second_event.id)
        self.assertEqual(PaymentEvent.objects.count(), 1)
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(TransactionEvent.objects.filter(event_type=TransactionEvent.Type.PAYMENT_PAID).count(), 1)
        self.assertEqual(RiskAssessment.objects.filter(transaction=self.payment.transaction).count(), 1)
        self.assertTrue(
            RiskAssessment.objects.filter(transaction=self.payment.transaction, payload__phase="post_payment_success").exists()
        )
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(self.product.stock_quantity, 3)
        self.assertEqual(LedgerEntry.objects.filter(entry_type="payment_capture").count(), 2)

    @override_settings(STRIPE_SECRET_KEY="sk_test", STRIPE_WEBHOOK_SECRET="whsec_test")
    @patch("payments.providers.stripe.stripe")
    def test_stripe_webhook_rejects_amount_mismatch(self, mock_stripe):
        event = {
            "id": "evt_bad_amount",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_intent": "pi_123",
                    "amount_total": 5000,
                    "currency": "usd",
                    "metadata": {
                        "order_id": str(self.order.id),
                        "payment_id": str(self.payment.id),
                    },
                }
            },
        }
        mock_stripe.Webhook.construct_event.return_value = event

        with self.assertRaises(PaymentWebhookProcessingError):
            StripeService.handle_webhook(b"{}", "sig")

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)
        self.assertEqual(self.product.stock_quantity, 4)
        self.assertEqual(PaymentEvent.objects.count(), 0)

    @override_settings(STRIPE_SECRET_KEY="sk_test", STRIPE_WEBHOOK_SECRET="whsec_test")
    @patch("payments.providers.stripe.stripe")
    def test_stripe_webhook_surfaces_validation_errors(self, mock_stripe):
        mock_stripe.Webhook.construct_event.side_effect = Exception("bad signature")

        with self.assertRaises(PaymentWebhookValidationError):
            StripeService.handle_webhook(b"{}", "sig")


class PaymentFlowTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Payment Product",
            slug="payment-product",
            sku="SKU-003",
            price=Decimal("50.00"),
            currency=Product.Currency.USD,
            stock_quantity=4,
            is_active=True,
            is_purchasable=True,
        )
        self.order = Order.objects.create(
            customer_name="Frank",
            customer_email="frank@example.com",
            shipping_country="US",
            shipping_city="Miami",
            shipping_postal_code="33101",
            shipping_address_line1="8 Palm Ave",
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
            status=Payment.Status.REQUIRES_ACTION,
            amount=Decimal("60.00"),
            currency="USD",
            checkout_token_or_session_id="cs_test_flow",
        )
        self.order.mark_payment_pending()

    def test_cancel_view_only_cancels_matching_payment_attempt(self):
        other_payment = Payment.objects.create(
            order=self.order,
            provider=Payment.Provider.STRIPE,
            status=Payment.Status.REQUIRES_ACTION,
            amount=Decimal("60.00"),
            currency="USD",
            checkout_token_or_session_id="cs_other",
        )

        response = self.client.get(
            reverse("payments:cancel", args=[self.order.public_token]),
            {"attempt": other_payment.id, "session_id": "cs_other"},
        )

        self.payment.refresh_from_db()
        other_payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payment.status, Payment.Status.REQUIRES_ACTION)
        self.assertEqual(other_payment.status, Payment.Status.CANCELLED)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.CANCELLED)

    def test_cancel_view_does_not_fallback_to_latest_attempt(self):
        response = self.client.get(reverse("payments:cancel", args=[self.order.public_token]))

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payment.status, Payment.Status.REQUIRES_ACTION)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)

    def test_stripe_success_page_keeps_unpaid_order_pending_confirmation(self):
        response = self.client.get(
            reverse("payments:success", args=[self.order.public_token]),
            {"attempt": self.payment.id, "session_id": "cs_test_flow"},
        )

        self.order.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)
        self.assertContains(response, "正在等待 Stripe 回写确认")

    def test_success_view_without_matching_attempt_is_non_mutating(self):
        response = self.client.get(reverse("payments:success", args=[self.order.public_token]), {"session_id": "wrong"})

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payment.status, Payment.Status.REQUIRES_ACTION)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)

    @patch("payments.views.PayPalService.capture_order", side_effect=Exception("boom"))
    def test_paypal_capture_failure_marks_order_failed(self, mock_capture):
        self.payment.provider = Payment.Provider.PAYPAL
        self.payment.checkout_token_or_session_id = "paypal-token"
        self.payment.save(update_fields=["provider", "checkout_token_or_session_id", "updated_at"])

        response = self.client.get(
            reverse("payments:success", args=[self.order.public_token]),
            {"attempt": self.payment.id, "token": "paypal-token"},
        )

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.FAILED)
        mock_capture.assert_called_once()

    def test_stripe_webhook_view_returns_500_for_processing_errors(self):
        with patch("payments.views.StripeService.handle_webhook", side_effect=PaymentWebhookProcessingError("boom")):
            response = self.client.post(reverse("payments:stripe_webhook"), data=b"{}", content_type="application/json")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["ok"], False)

    def test_stripe_webhook_view_returns_400_for_validation_errors(self):
        with patch("payments.views.StripeService.handle_webhook", side_effect=PaymentWebhookValidationError("bad")):
            response = self.client.post(reverse("payments:stripe_webhook"), data=b"{}", content_type="application/json")

        self.assertEqual(response.status_code, 400)


class PayPalServiceTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="PayPal Product",
            slug="paypal-product",
            sku="SKU-PAYPAL",
            price=Decimal("50.00"),
            currency=Product.Currency.USD,
            stock_quantity=4,
            is_active=True,
            is_purchasable=True,
        )
        self.order = Order.objects.create(
            customer_name="Pam",
            customer_email="pam@example.com",
            shipping_country="US",
            shipping_city="Austin",
            shipping_postal_code="73301",
            shipping_address_line1="1 Pay St",
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
            provider=Payment.Provider.PAYPAL,
            amount=Decimal("60.00"),
            currency="USD",
            checkout_token_or_session_id="paypal_order_123",
        )

    @override_settings(PAYPAL_CLIENT_ID="id", PAYPAL_CLIENT_SECRET="secret")
    @patch("payments.providers.paypal.requests.post")
    def test_paypal_capture_verifies_amount_and_currency(self, mock_post):
        token_response = type("Response", (), {"raise_for_status": lambda self: None, "json": lambda self: {"access_token": "token"}})()
        order_number = self.order.order_number
        capture_response = type(
            "Response",
            (),
            {
                "raise_for_status": lambda self: None,
                "json": lambda self: {
                    "id": "paypal_order_123",
                    "purchase_units": [
                        {
                            "reference_id": order_number,
                            "payments": {
                                "captures": [
                                    {
                                        "id": "capture_123",
                                        "status": "COMPLETED",
                                        "amount": {"value": "55.00", "currency_code": "USD"},
                                    }
                                ]
                            },
                        }
                    ],
                },
            },
        )()
        mock_post.side_effect = [token_response, capture_response]

        with self.assertRaisesMessage(Exception, "PayPal 金额不匹配"):
            PayPalService.capture_order(self.payment)

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)
        self.assertEqual(PaymentEvent.objects.count(), 0)
