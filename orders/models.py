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

    order_number = models.CharField(max_length=32, unique=True, blank=True)
    public_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING)
    fulfillment_status = models.CharField(max_length=20, choices=FulfillmentStatus.choices, default=FulfillmentStatus.UNFULFILLED)
    customer_name = models.CharField(max_length=120)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=50, blank=True)
    shipping_country = models.CharField(max_length=2)
    shipping_state = models.CharField(max_length=100, blank=True)
    shipping_city = models.CharField(max_length=100)
    shipping_postal_code = models.CharField(max_length=20)
    shipping_address_line1 = models.CharField(max_length=255)
    shipping_address_line2 = models.CharField(max_length=255, blank=True)
    subtotal_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    shipping_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField(max_length=3, default=Product.Currency.USD)
    notes = models.TextField(blank=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

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

    @transaction.atomic
    def mark_paid(self, paid_at=None):
        if self.payment_status == self.PaymentStatus.PAID:
            return

        items = list(self.items.select_related("product").select_for_update())
        for item in items:
            if item.product.stock_quantity < item.quantity:
                raise ValueError(f"商品库存不足：{item.product.name}")

        for item in items:
            item.product.stock_quantity -= item.quantity
            item.product.save(update_fields=["stock_quantity", "updated_at"])

        self.status = self.Status.PAID
        self.payment_status = self.PaymentStatus.PAID
        self.paid_at = paid_at or timezone.now()
        self.save(update_fields=["status", "payment_status", "paid_at", "updated_at"])

    def mark_payment_failed(self):
        self.payment_status = self.PaymentStatus.FAILED
        self.save(update_fields=["payment_status", "updated_at"])


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    product_name_snapshot = models.CharField(max_length=150)
    sku_snapshot = models.CharField(max_length=64, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    line_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.order.order_number} - {self.product_name_snapshot}"

    def save(self, *args, **kwargs):
        self.line_total = self.unit_price * self.quantity
        super().save(*args, **kwargs)
