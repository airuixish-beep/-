from django.db import models

from orders.models import Order


class Shipment(models.Model):
    class Provider(models.TextChoices):
        EASYPOST = "easypost", "EasyPost"
        MANUAL = "manual", "Manual"

    class Status(models.TextChoices):
        PENDING = "pending", "待创建"
        LABEL_PURCHASED = "label_purchased", "已购面单"
        SHIPPED = "shipped", "已发货"
        IN_TRANSIT = "in_transit", "运输中"
        DELIVERED = "delivered", "已送达"
        EXCEPTION = "exception", "异常"
        CANCELLED = "cancelled", "已取消"

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="shipments")
    provider = models.CharField(max_length=20, choices=Provider.choices, default=Provider.MANUAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    external_shipment_id = models.CharField(max_length=120, blank=True)
    tracking_number = models.CharField(max_length=120, blank=True)
    tracking_url = models.URLField(blank=True)
    label_url = models.URLField(blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    shipped_at = models.DateTimeField(blank=True, null=True)
    delivered_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order.order_number} - {self.get_provider_display()}"


class ShipmentEvent(models.Model):
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=20, choices=Shipment.Status.choices)
    message = models.CharField(max_length=255, blank=True)
    event_time = models.DateTimeField()
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-event_time", "-id"]

    def __str__(self):
        return f"{self.shipment.order.order_number} - {self.status}"
