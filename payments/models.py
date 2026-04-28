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

    order = models.ForeignKey("orders.Order", verbose_name="所属订单", on_delete=models.CASCADE, related_name="payments")
    transaction = models.ForeignKey(
        "transactions.Transaction",
        verbose_name="所属交易",
        on_delete=models.SET_NULL,
        related_name="payment_attempts",
        null=True,
        blank=True,
    )
    provider = models.CharField("支付渠道", max_length=20, choices=Provider.choices)
    status = models.CharField("支付状态", max_length=20, choices=Status.choices, default=Status.PENDING)
    amount = models.DecimalField("支付金额", max_digits=10, decimal_places=2)
    currency = models.CharField("币种", max_length=3)
    external_payment_id = models.CharField("第三方支付单号", max_length=120, blank=True)
    checkout_token_or_session_id = models.CharField("会话 / 支付令牌", max_length=120, blank=True)
    approval_url = models.URLField("支付跳转地址", blank=True)
    paid_at = models.DateTimeField("支付完成时间", blank=True, null=True)
    raw_payload = models.JSONField("原始回调数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "支付记录"
        verbose_name_plural = "支付记录"

    def __str__(self):
        return f"{self.order.order_number} - {self.provider}"


class PaymentEvent(models.Model):
    provider = models.CharField("支付渠道", max_length=20, choices=Payment.Provider.choices)
    event_id = models.CharField("事件 ID", max_length=120)
    event_type = models.CharField("事件类型", max_length=120)
    payload = models.JSONField("事件数据", default=dict, blank=True)
    processed_at = models.DateTimeField("处理时间", auto_now_add=True)

    class Meta:
        ordering = ["-processed_at"]
        verbose_name = "支付事件"
        verbose_name_plural = "支付事件"
        constraints = [
            models.UniqueConstraint(fields=["provider", "event_id"], name="uniq_payment_event_provider_event_id"),
        ]

    def __str__(self):
        return f"{self.provider} - {self.event_type}"
