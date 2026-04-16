from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from products.models import Product

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
