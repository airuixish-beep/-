from django.db import models


class Payment(models.Model):
    class Provider(models.TextChoices):
        STRIPE = "stripe", "Stripe"
        PAYPAL = "paypal", "PayPal"

    class Status(models.TextChoices):
        PENDING = "pending", "待支付"
        REQUIRES_ACTION = "requires_action", "待用户操作"
        PAID = "paid", "已支付"
        FAILED = "failed", "支付失败"
        CANCELLED = "cancelled", "已取消"

    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="payments")
    provider = models.CharField(max_length=20, choices=Provider.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3)
    external_payment_id = models.CharField(max_length=120, blank=True)
    checkout_token_or_session_id = models.CharField(max_length=120, blank=True)
    approval_url = models.URLField(blank=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.order.order_number} - {self.provider}"


class PaymentEvent(models.Model):
    provider = models.CharField(max_length=20, choices=Payment.Provider.choices)
    event_id = models.CharField(max_length=120, unique=True)
    event_type = models.CharField(max_length=120)
    payload = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-processed_at"]

    def __str__(self):
        return f"{self.provider} - {self.event_type}"
