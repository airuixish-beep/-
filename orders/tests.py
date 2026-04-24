from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from payments.models import Payment
from products.models import Product
from shipping.models import Shipment, ShipmentEvent

from .models import Order, OrderItem


class OrderModelTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Test Product",
            slug="test-product",
            sku="SKU-001",
            price=Decimal("99.00"),
            currency=Product.Currency.USD,
            stock_quantity=5,
            is_active=True,
            is_purchasable=True,
        )

    def test_recalculate_totals_includes_shipping(self):
        order = Order.objects.create(
            customer_name="Alice",
            customer_email="alice@example.com",
            shipping_country="US",
            shipping_city="New York",
            shipping_postal_code="10001",
            shipping_address_line1="1 Main St",
            shipping_amount=Decimal("15.00"),
            currency=Product.Currency.USD,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name_snapshot=self.product.name,
            sku_snapshot=self.product.sku,
            unit_price=self.product.price,
            quantity=2,
        )

        order.recalculate_totals()

        self.assertEqual(order.subtotal_amount, Decimal("198.00"))
        self.assertEqual(order.total_amount, Decimal("213.00"))

    def test_mark_paid_deducts_inventory_once(self):
        order = Order.objects.create(
            customer_name="Alice",
            customer_email="alice@example.com",
            shipping_country="US",
            shipping_city="New York",
            shipping_postal_code="10001",
            shipping_address_line1="1 Main St",
            shipping_amount=Decimal("15.00"),
            currency=Product.Currency.USD,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name_snapshot=self.product.name,
            sku_snapshot=self.product.sku,
            unit_price=self.product.price,
            quantity=2,
        )
        order.recalculate_totals()

        paid_at = timezone.now()
        order.mark_paid(paid_at)
        self.product.refresh_from_db()
        order.refresh_from_db()

        self.assertEqual(self.product.stock_quantity, 3)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(order.paid_at, paid_at)

        order.mark_paid(paid_at)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 3)

    def test_mark_processing_requires_paid_order(self):
        order = Order.objects.create(
            customer_name="Alice",
            customer_email="alice@example.com",
            shipping_country="US",
            shipping_city="New York",
            shipping_postal_code="10001",
            shipping_address_line1="1 Main St",
            shipping_amount=Decimal("15.00"),
            currency=Product.Currency.USD,
        )

        with self.assertRaisesMessage(ValueError, "未支付订单不能标记为处理中"):
            order.mark_processing()


class OrderDetailTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Detail Product",
            slug="detail-product",
            sku="SKU-DETAIL",
            price=Decimal("88.00"),
            currency=Product.Currency.USD,
            stock_quantity=6,
            is_active=True,
            is_purchasable=True,
        )

    def create_order(self):
        order = Order.objects.create(
            customer_name="Dana",
            customer_email="dana@example.com",
            shipping_country="US",
            shipping_city="Boston",
            shipping_postal_code="02110",
            shipping_address_line1="5 Harbor St",
            shipping_amount=Decimal("12.00"),
            currency=Product.Currency.USD,
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            product_name_snapshot=self.product.name,
            sku_snapshot=self.product.sku,
            unit_price=self.product.price,
            quantity=1,
        )
        order.recalculate_totals()
        return order

    def test_order_detail_shows_retry_button_for_unpaid_order(self):
        order = self.create_order()
        Payment.objects.create(
            order=order,
            provider=Payment.Provider.STRIPE,
            status=Payment.Status.CANCELLED,
            amount=order.total_amount,
            currency=order.currency,
        )
        order.mark_payment_cancelled()

        response = self.client.get(reverse("orders:detail", args=[order.public_token]))

        self.assertContains(response, "重新支付")

    def test_order_detail_hides_retry_button_for_paid_order(self):
        order = self.create_order()
        Payment.objects.create(
            order=order,
            provider=Payment.Provider.STRIPE,
            status=Payment.Status.PAID,
            amount=order.total_amount,
            currency=order.currency,
            paid_at=timezone.now(),
        )
        order.mark_paid()

        response = self.client.get(reverse("orders:detail", args=[order.public_token]))

        self.assertNotContains(response, "重新支付")

    def test_order_detail_shows_shipment_timeline(self):
        order = self.create_order()
        shipment = Shipment.objects.create(order=order, status=Shipment.Status.IN_TRANSIT)
        ShipmentEvent.objects.create(
            shipment=shipment,
            status=Shipment.Status.LABEL_PURCHASED,
            message="已创建面单",
            event_time=timezone.now() - timedelta(hours=1),
        )
        ShipmentEvent.objects.create(
            shipment=shipment,
            status=Shipment.Status.IN_TRANSIT,
            message="运输中",
            event_time=timezone.now(),
        )

        response = self.client.get(reverse("orders:detail", args=[order.public_token]))

        self.assertContains(response, "物流时间线")
        self.assertContains(response, "运输中")


class RetryPaymentTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Retry Product",
            slug="retry-product",
            sku="SKU-RETRY",
            price=Decimal("66.00"),
            currency=Product.Currency.USD,
            stock_quantity=6,
            is_active=True,
            is_purchasable=True,
        )
        self.order = Order.objects.create(
            customer_name="Eve",
            customer_email="eve@example.com",
            shipping_country="US",
            shipping_city="Chicago",
            shipping_postal_code="60601",
            shipping_address_line1="7 Lake St",
            shipping_amount=Decimal("10.00"),
            currency=Product.Currency.USD,
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_name_snapshot=self.product.name,
            sku_snapshot=self.product.sku,
            unit_price=self.product.price,
            quantity=1,
        )
        self.order.recalculate_totals()
        Payment.objects.create(
            order=self.order,
            provider=Payment.Provider.STRIPE,
            status=Payment.Status.CANCELLED,
            amount=self.order.total_amount,
            currency=self.order.currency,
        )
        self.order.mark_payment_cancelled()

    @patch("orders.views.create_payment_redirect", return_value="https://payments.example/checkout")
    def test_retry_payment_creates_new_payment_attempt(self, mock_redirect):
        response = self.client.post(reverse("orders:retry_payment", args=[self.order.public_token]))

        self.order.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "https://payments.example/checkout")
        self.assertEqual(self.order.payments.count(), 2)
        self.assertEqual(self.order.payments.first().status, Payment.Status.PENDING)
        self.assertEqual(self.order.payment_status, Order.PaymentStatus.PENDING)
        mock_redirect.assert_called_once()
