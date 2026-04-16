from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from orders.models import Order
from products.models import Product

from .models import Payment, PaymentEvent
from .services import StripeService


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
    @patch("payments.services.stripe")
    def test_stripe_webhook_is_idempotent(self, mock_stripe):
        event = {
            "id": "evt_test_123",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_intent": "pi_123",
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
        self.assertEqual(self.payment.status, Payment.Status.PAID)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(self.product.stock_quantity, 3)


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

    def test_cancel_view_only_cancels_payment_attempt(self):
        response = self.client.get(reverse("payments:cancel", args=[self.order.public_token]))

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payment.status, Payment.Status.CANCELLED)
        self.assertEqual(self.order.status, Order.Status.PENDING)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.CANCELLED)

    def test_stripe_success_page_keeps_unpaid_order_pending_confirmation(self):
        response = self.client.get(reverse("payments:success", args=[self.order.public_token]))

        self.order.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)
        self.assertContains(response, "正在等待 Stripe 回写确认")

    @patch("payments.views.PayPalService.capture_order", side_effect=Exception("boom"))
    def test_paypal_capture_failure_marks_order_failed(self, mock_capture):
        self.payment.provider = Payment.Provider.PAYPAL
        self.payment.checkout_token_or_session_id = "paypal-token"
        self.payment.save(update_fields=["provider", "checkout_token_or_session_id", "updated_at"])

        response = self.client.get(reverse("payments:success", args=[self.order.public_token]), {"token": "paypal-token"})

        self.payment.refresh_from_db()
        self.order.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.FAILED)
        mock_capture.assert_called_once()
