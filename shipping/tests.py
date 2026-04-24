from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from orders.models import Order, OrderItem
from products.models import Product

from .models import Shipment, ShipmentEvent
from .services import EasyPostService, ShippingConfigurationError


class ShipmentModelTests(TestCase):
    def test_events_are_sorted_latest_first(self):
        order = Order.objects.create(
            customer_name="Carol",
            customer_email="carol@example.com",
            shipping_country="US",
            shipping_city="Austin",
            shipping_postal_code="73301",
            shipping_address_line1="3 River Rd",
        )
        shipment = Shipment.objects.create(order=order)
        older = timezone.now() - timedelta(days=1)
        newer = timezone.now()
        ShipmentEvent.objects.create(shipment=shipment, status=Shipment.Status.SHIPPED, message="older", event_time=older)
        ShipmentEvent.objects.create(shipment=shipment, status=Shipment.Status.DELIVERED, message="newer", event_time=newer)

        events = list(shipment.events.all())

        self.assertEqual(events[0].message, "newer")
        self.assertEqual(events[1].message, "older")

    def test_sync_fulfillment_from_shipment_status_updates_order_states(self):
        order = Order.objects.create(
            customer_name="Carol",
            customer_email="carol@example.com",
            shipping_country="US",
            shipping_city="Austin",
            shipping_postal_code="73301",
            shipping_address_line1="3 River Rd",
        )
        order.payment_status = Order.PaymentStatus.PAID
        order.status = Order.Status.PAID
        order.save(update_fields=["payment_status", "status", "updated_at"])

        order.sync_fulfillment_from_shipment_status(Shipment.Status.LABEL_PURCHASED)
        order.refresh_from_db()
        self.assertEqual(order.fulfillment_status, Order.FulfillmentStatus.PROCESSING)
        self.assertEqual(order.status, Order.Status.PROCESSING)

        order.sync_fulfillment_from_shipment_status(Shipment.Status.SHIPPED)
        order.refresh_from_db()
        self.assertEqual(order.fulfillment_status, Order.FulfillmentStatus.SHIPPED)
        self.assertEqual(order.status, Order.Status.SHIPPED)

        order.sync_fulfillment_from_shipment_status(Shipment.Status.DELIVERED)
        order.refresh_from_db()
        self.assertEqual(order.fulfillment_status, Order.FulfillmentStatus.DELIVERED)
        self.assertEqual(order.status, Order.Status.DELIVERED)

    def test_sync_fulfillment_from_cancelled_shipment_cancels_order(self):
        order = Order.objects.create(
            customer_name="Carol",
            customer_email="carol@example.com",
            shipping_country="US",
            shipping_city="Austin",
            shipping_postal_code="73301",
            shipping_address_line1="3 River Rd",
        )
        order.payment_status = Order.PaymentStatus.PAID
        order.status = Order.Status.PAID
        order.save(update_fields=["payment_status", "status", "updated_at"])

        order.sync_fulfillment_from_shipment_status(Shipment.Status.CANCELLED)
        order.refresh_from_db()

        self.assertEqual(order.fulfillment_status, Order.FulfillmentStatus.CANCELLED)
        self.assertEqual(order.status, Order.Status.CANCELLED)


class EasyPostServiceTests(TestCase):
    @override_settings(
        EASYPOST_API_KEY="ep_test",
        SHIP_FROM_ADDRESS_LINE1="1 Warehouse St",
        SHIP_FROM_CITY="San Jose",
        SHIP_FROM_STATE="CA",
        SHIP_FROM_POSTAL_CODE="95112",
        SHIP_FROM_COUNTRY="US",
    )
    @patch("shipping.services.easypost")
    def test_create_shipment_uses_quantity_aware_weight_and_marks_processing(self, mock_easypost):
        product = Product.objects.create(
            name="Ship Product",
            slug="ship-product",
            sku="SKU-SHIP",
            price=Decimal("40.00"),
            currency=Product.Currency.USD,
            stock_quantity=10,
            is_active=True,
            is_purchasable=True,
            weight=Decimal("8.00"),
            length=Decimal("12.00"),
            width=Decimal("6.00"),
            height=Decimal("2.00"),
        )
        order = Order.objects.create(
            customer_name="Gary",
            customer_email="gary@example.com",
            shipping_country="US",
            shipping_city="Denver",
            shipping_state="CO",
            shipping_postal_code="80202",
            shipping_address_line1="10 Market St",
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name_snapshot=product.name,
            sku_snapshot=product.sku,
            unit_price=product.price,
            quantity=3,
        )
        order.payment_status = Order.PaymentStatus.PAID
        order.status = Order.Status.PAID
        order.save(update_fields=["payment_status", "status", "updated_at"])
        shipment = Shipment.objects.create(order=order)

        bought = SimpleNamespace(
            id="shp_123",
            tracking_code="TRACK123",
            tracker=SimpleNamespace(tracking_code="TRACK123", public_url="https://track.example/123"),
            postage_label=SimpleNamespace(label_url="https://label.example/123"),
            to_dict=lambda: {"id": "shp_123"},
        )
        created = SimpleNamespace(id="created_123", lowest_rate=lambda: {"id": "rate_123"})
        client = SimpleNamespace(
            shipment=SimpleNamespace(
                create=lambda **kwargs: created,
                buy=lambda shipment_id, rate: bought,
            )
        )
        mock_easypost.EasyPostClient.return_value = client

        EasyPostService.create_shipment(shipment)

        shipment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(shipment.status, Shipment.Status.LABEL_PURCHASED)
        self.assertEqual(order.fulfillment_status, Order.FulfillmentStatus.PROCESSING)
        self.assertEqual(order.status, Order.Status.PROCESSING)
        parcel = EasyPostService._parcel_for_order(order)
        self.assertEqual(parcel["weight"], 24.0)

    @override_settings(
        EASYPOST_API_KEY="ep_test",
        SHIP_FROM_ADDRESS_LINE1="1 Warehouse St",
        SHIP_FROM_CITY="San Jose",
        SHIP_FROM_STATE="CA",
        SHIP_FROM_POSTAL_CODE="95112",
        SHIP_FROM_COUNTRY="US",
    )
    def test_create_shipment_rejects_unpaid_order(self):
        product = Product.objects.create(
            name="Ship Product 2",
            slug="ship-product-2",
            sku="SKU-SHIP-2",
            price=Decimal("40.00"),
            currency=Product.Currency.USD,
            stock_quantity=10,
            is_active=True,
            is_purchasable=True,
        )
        order = Order.objects.create(
            customer_name="Nina",
            customer_email="nina@example.com",
            shipping_country="US",
            shipping_city="Denver",
            shipping_state="CO",
            shipping_postal_code="80202",
            shipping_address_line1="10 Market St",
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name_snapshot=product.name,
            sku_snapshot=product.sku,
            unit_price=product.price,
            quantity=1,
        )
        shipment = Shipment.objects.create(order=order)

        with self.assertRaisesMessage(ShippingConfigurationError, "只有已支付订单才能创建发货单"):
            EasyPostService.create_shipment(shipment)
