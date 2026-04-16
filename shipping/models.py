from django.db import models

from orders.models import Order


class Shipment(models.Model):
    class Provider(models.TextChoices):
        EASYPOST = "easypost", "EasyPost"
        MANUAL = "manual", "手动录入"

    class Status(models.TextChoices):
        PENDING = "pending", "待创建"
        LABEL_PURCHASED = "label_purchased", "已购面单"
        SHIPPED = "shipped", "已发货"
        IN_TRANSIT = "in_transit", "运输中"
        DELIVERED = "delivered", "已送达"
        EXCEPTION = "exception", "异常"
        CANCELLED = "cancelled", "已取消"

    order = models.ForeignKey(Order, verbose_name="所属订单", on_delete=models.CASCADE, related_name="shipments")
    provider = models.CharField("物流渠道", max_length=20, choices=Provider.choices, default=Provider.MANUAL)
    status = models.CharField("物流状态", max_length=20, choices=Status.choices, default=Status.PENDING)
    external_shipment_id = models.CharField("第三方发货单号", max_length=120, blank=True)
    tracking_number = models.CharField("运单号", max_length=120, blank=True)
    tracking_url = models.URLField("物流追踪链接", blank=True)
    label_url = models.URLField("面单链接", blank=True)
    raw_payload = models.JSONField("原始物流数据", default=dict, blank=True)
    shipped_at = models.DateTimeField("发货时间", blank=True, null=True)
    delivered_at = models.DateTimeField("送达时间", blank=True, null=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "发货单"
        verbose_name_plural = "发货单"

    def __str__(self):
        return f"{self.order.order_number} - {self.get_provider_display()}"


class ShipmentEvent(models.Model):
    shipment = models.ForeignKey(Shipment, verbose_name="所属发货单", on_delete=models.CASCADE, related_name="events")
    status = models.CharField("事件状态", max_length=20, choices=Shipment.Status.choices)
    message = models.CharField("事件说明", max_length=255, blank=True)
    event_time = models.DateTimeField("事件时间")
    payload = models.JSONField("事件数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["-event_time", "-id"]
        verbose_name = "物流事件"
        verbose_name_plural = "物流事件"

    def __str__(self):
        return f"{self.shipment.order.order_number} - {self.status}"
