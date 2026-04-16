from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from orders.models import Order

from .models import Shipment, ShipmentEvent


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
