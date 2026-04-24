import secrets
import uuid
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from products.models import Product


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待支付"
        PAID = "paid", "已支付"
        PROCESSING = "processing", "处理中"
        SHIPPED = "shipped", "已发货"
        DELIVERED = "delivered", "已送达"
        CANCELLED = "cancelled", "已取消"

    class PaymentStatus(models.TextChoices):
        PENDING = "pending", "待支付"
        PAID = "paid", "已支付"
        FAILED = "failed", "支付失败"
        CANCELLED = "cancelled", "已取消"

    class FulfillmentStatus(models.TextChoices):
        UNFULFILLED = "unfulfilled", "待发货"
        PROCESSING = "processing", "备货中"
        SHIPPED = "shipped", "已发货"
        DELIVERED = "delivered", "已送达"
        CANCELLED = "cancelled", "已取消"

    order_number = models.CharField("订单号", max_length=32, unique=True, blank=True)
    public_token = models.UUIDField("公开访问令牌", default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField("订单状态", max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_status = models.CharField("支付状态", max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    fulfillment_status = models.CharField("履约状态", max_length=20, choices=FulfillmentStatus.choices, default=FulfillmentStatus.UNFULFILLED)
    customer_name = models.CharField("客户姓名", max_length=120)
    customer_email = models.EmailField("客户邮箱")
    customer_phone = models.CharField("客户电话", max_length=50, blank=True)
    shipping_country = models.CharField("收货国家", max_length=2)
    shipping_state = models.CharField("州/省", max_length=100, blank=True)
    shipping_city = models.CharField("城市", max_length=100)
    shipping_postal_code = models.CharField("邮编", max_length=20)
    shipping_address_line1 = models.CharField("地址 1", max_length=255)
    shipping_address_line2 = models.CharField("地址 2", max_length=255, blank=True)
    subtotal_amount = models.DecimalField("商品小计", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    shipping_amount = models.DecimalField("运费", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField("订单总额", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField("币种", max_length=3, default=Product.Currency.USD)
    notes = models.TextField("备注", blank=True)
    paid_at = models.DateTimeField("支付时间", blank=True, null=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "订单"
        verbose_name_plural = "订单"

    def __str__(self):
        return self.order_number

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = self.generate_order_number()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_order_number():
        return f"XO{timezone.now():%Y%m%d}{secrets.token_hex(3).upper()}"

    @property
    def shipping_address(self):
        parts = [
            self.shipping_address_line1,
            self.shipping_address_line2,
            self.shipping_city,
            self.shipping_state,
            self.shipping_postal_code,
            self.shipping_country,
        ]
        return ", ".join([part for part in parts if part])

    def recalculate_totals(self, save=True):
        subtotal = sum((item.line_total for item in self.items.all()), Decimal("0.00"))
        self.subtotal_amount = subtotal
        self.total_amount = subtotal + self.shipping_amount
        if save:
            self.save(update_fields=["subtotal_amount", "total_amount", "updated_at"])
        return self.total_amount

    @property
    def can_retry_payment(self):
        return self.payment_status != self.PaymentStatus.PAID and self.status != self.Status.CANCELLED

    def mark_payment_pending(self):
        if self.payment_status == self.PaymentStatus.PAID:
            return
        self.status = self.Status.PENDING
        self.payment_status = self.PaymentStatus.PENDING
        self.save(update_fields=["status", "payment_status", "updated_at"])

    @transaction.atomic
    def mark_paid(self, paid_at=None):
        if self.payment_status == self.PaymentStatus.PAID:
            return

        items = list(self.items.select_for_update())
        products = {
            product.id: product
            for product in Product.objects.select_for_update().filter(id__in=[item.product_id for item in items])
        }

        for item in items:
            product = products[item.product_id]
            if product.stock_quantity < item.quantity:
                raise ValueError(f"商品库存不足：{product.name}")

        for item in items:
            product = products[item.product_id]
            product.stock_quantity -= item.quantity
            product.save(update_fields=["stock_quantity", "updated_at"])

        self.status = self.Status.PAID
        self.payment_status = self.PaymentStatus.PAID
        self.paid_at = paid_at or timezone.now()
        self.save(update_fields=["status", "payment_status", "paid_at", "updated_at"])

    def mark_payment_failed(self):
        if self.payment_status == self.PaymentStatus.PAID:
            return
        self.status = self.Status.PENDING
        self.payment_status = self.PaymentStatus.FAILED
        self.save(update_fields=["status", "payment_status", "updated_at"])

    def mark_payment_cancelled(self):
        if self.payment_status == self.PaymentStatus.PAID:
            return
        self.status = self.Status.PENDING
        self.payment_status = self.PaymentStatus.CANCELLED
        self.save(update_fields=["status", "payment_status", "updated_at"])

    def mark_processing(self):
        if self.payment_status != self.PaymentStatus.PAID:
            raise ValueError("未支付订单不能标记为处理中")
        self.fulfillment_status = self.FulfillmentStatus.PROCESSING
        self.status = self.Status.PROCESSING
        self.save(update_fields=["fulfillment_status", "status", "updated_at"])

    def sync_fulfillment_from_shipment_status(self, shipment_status):
        from shipping.models import Shipment

        update_fields = []

        if shipment_status == Shipment.Status.LABEL_PURCHASED:
            self.fulfillment_status = self.FulfillmentStatus.PROCESSING
            update_fields.append("fulfillment_status")
            if self.payment_status == self.PaymentStatus.PAID:
                self.status = self.Status.PROCESSING
                update_fields.append("status")
        elif shipment_status in {Shipment.Status.SHIPPED, Shipment.Status.IN_TRANSIT}:
            self.fulfillment_status = self.FulfillmentStatus.SHIPPED
            update_fields.append("fulfillment_status")
            if self.payment_status == self.PaymentStatus.PAID:
                self.status = self.Status.SHIPPED
                update_fields.append("status")
        elif shipment_status == Shipment.Status.DELIVERED:
            self.fulfillment_status = self.FulfillmentStatus.DELIVERED
            update_fields.append("fulfillment_status")
            if self.payment_status == self.PaymentStatus.PAID:
                self.status = self.Status.DELIVERED
                update_fields.append("status")
        elif shipment_status == Shipment.Status.CANCELLED:
            self.fulfillment_status = self.FulfillmentStatus.CANCELLED
            update_fields.append("fulfillment_status")
            if self.payment_status == self.PaymentStatus.PAID:
                self.status = self.Status.CANCELLED
                update_fields.append("status")
        elif shipment_status == Shipment.Status.EXCEPTION:
            self.fulfillment_status = self.FulfillmentStatus.PROCESSING
            update_fields.append("fulfillment_status")

        if update_fields:
            self.save(update_fields=[*dict.fromkeys(update_fields), "updated_at"])


class OrderItem(models.Model):
    order = models.ForeignKey(Order, verbose_name="所属订单", on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, verbose_name="关联商品", on_delete=models.PROTECT, related_name="order_items")
    product_name_snapshot = models.CharField("商品名称快照", max_length=150)
    sku_snapshot = models.CharField("SKU 快照", max_length=64, blank=True)
    unit_price = models.DecimalField("单价", max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField("数量", default=1)
    line_total = models.DecimalField("小计", max_digits=10, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["id"]
        verbose_name = "订单商品"
        verbose_name_plural = "订单商品"

    def __str__(self):
        return f"{self.order.order_number} - {self.product_name_snapshot}"

    def save(self, *args, **kwargs):
        self.line_total = self.unit_price * self.quantity
        super().save(*args, **kwargs)
