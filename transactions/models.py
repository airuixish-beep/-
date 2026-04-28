from decimal import Decimal

from django.db import models


class Transaction(models.Model):
    class Kind(models.TextChoices):
        PURCHASE = "purchase", "购买"

    class Status(models.TextChoices):
        INITIATED = "initiated", "已发起"
        PENDING = "pending", "待支付"
        REQUIRES_ACTION = "requires_action", "待用户操作"
        PAID = "paid", "已支付"
        PARTIALLY_REFUNDED = "partially_refunded", "部分退款"
        REFUNDED = "refunded", "已退款"
        FAILED = "failed", "支付失败"
        CANCELLED = "cancelled", "已取消"

    class RiskStatus(models.TextChoices):
        NONE = "none", "未评估"
        ALLOW = "allow", "放行"
        REVIEW = "review", "人工审核"
        BLOCK = "block", "阻断"

    order = models.ForeignKey("orders.Order", verbose_name="所属订单", on_delete=models.CASCADE, related_name="transactions")
    kind = models.CharField("交易类型", max_length=20, choices=Kind.choices, default=Kind.PURCHASE)
    provider = models.CharField("主支付渠道", max_length=20, blank=True)
    status = models.CharField("交易状态", max_length=20, choices=Status.choices, default=Status.INITIATED)
    risk_status = models.CharField("风控状态", max_length=20, choices=RiskStatus.choices, default=RiskStatus.NONE)
    amount = models.DecimalField("交易金额", max_digits=10, decimal_places=2)
    currency = models.CharField("币种", max_length=3)
    paid_at = models.DateTimeField("支付时间", blank=True, null=True)
    metadata = models.JSONField("扩展信息", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "交易"
        verbose_name_plural = "交易"

    def __str__(self):
        return f"{self.order.order_number} - {self.kind}"


class TransactionEvent(models.Model):
    class Type(models.TextChoices):
        INITIATED = "initiated", "交易发起"
        PAYMENT_PENDING = "payment_pending", "待支付"
        PAYMENT_REQUIRES_ACTION = "payment_requires_action", "待用户操作"
        PAYMENT_PAID = "payment_paid", "支付成功"
        PAYMENT_FAILED = "payment_failed", "支付失败"
        PAYMENT_CANCELLED = "payment_cancelled", "支付取消"
        REFUND_REQUESTED = "refund_requested", "退款申请"
        REFUND_SUCCEEDED = "refund_succeeded", "退款成功"
        REFUND_FAILED = "refund_failed", "退款失败"

    transaction = models.ForeignKey(Transaction, verbose_name="所属交易", on_delete=models.CASCADE, related_name="events")
    payment = models.ForeignKey("payments.Payment", verbose_name="支付尝试", on_delete=models.SET_NULL, related_name="transaction_events", null=True, blank=True)
    event_type = models.CharField("事件类型", max_length=40, choices=Type.choices)
    source = models.CharField("事件来源", max_length=40)
    idempotency_key = models.CharField("幂等键", max_length=120)
    payload = models.JSONField("事件数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "交易事件"
        verbose_name_plural = "交易事件"
        constraints = [
            models.UniqueConstraint(fields=["transaction", "idempotency_key"], name="uniq_transaction_event_key_per_transaction"),
        ]

    def __str__(self):
        return f"{self.transaction_id} - {self.event_type}"


class Refund(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "已申请"
        PROCESSING = "processing", "处理中"
        SUCCEEDED = "succeeded", "退款成功"
        FAILED = "failed", "退款失败"
        CANCELLED = "cancelled", "已取消"

    transaction = models.ForeignKey(Transaction, verbose_name="所属交易", on_delete=models.CASCADE, related_name="refunds")
    payment = models.ForeignKey("payments.Payment", verbose_name="原支付", on_delete=models.SET_NULL, related_name="refunds", null=True, blank=True)
    amount = models.DecimalField("退款金额", max_digits=10, decimal_places=2)
    currency = models.CharField("币种", max_length=3)
    status = models.CharField("退款状态", max_length=20, choices=Status.choices, default=Status.REQUESTED)
    provider_refund_id = models.CharField("第三方退款单号", max_length=120, blank=True)
    reason = models.CharField("退款原因", max_length=255, blank=True)
    operator_notes = models.TextField("操作备注", blank=True)
    failure_reason = models.CharField("失败原因", max_length=255, blank=True)
    submitted_at = models.DateTimeField("提交时间", blank=True, null=True)
    completed_at = models.DateTimeField("完成时间", blank=True, null=True)
    raw_payload = models.JSONField("原始退款数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "退款"
        verbose_name_plural = "退款"


class LedgerAccount(models.Model):
    code = models.CharField("账户编码", max_length=50, unique=True)
    name = models.CharField("账户名称", max_length=100)
    is_active = models.BooleanField("启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "账务账户"
        verbose_name_plural = "账务账户"

    def __str__(self):
        return f"{self.code} - {self.name}"


class LedgerEntry(models.Model):
    class Direction(models.TextChoices):
        DEBIT = "debit", "借"
        CREDIT = "credit", "贷"

    transaction = models.ForeignKey(Transaction, verbose_name="所属交易", on_delete=models.CASCADE, related_name="ledger_entries")
    payment = models.ForeignKey("payments.Payment", verbose_name="支付尝试", on_delete=models.SET_NULL, related_name="ledger_entries", null=True, blank=True)
    refund = models.ForeignKey(Refund, verbose_name="退款", on_delete=models.SET_NULL, related_name="ledger_entries", null=True, blank=True)
    account = models.ForeignKey(LedgerAccount, verbose_name="账户", on_delete=models.PROTECT, related_name="entries")
    direction = models.CharField("方向", max_length=10, choices=Direction.choices)
    amount = models.DecimalField("金额", max_digits=10, decimal_places=2, default=Decimal("0.00"))
    currency = models.CharField("币种", max_length=3)
    entry_type = models.CharField("分录类型", max_length=40)
    external_reference = models.CharField("外部引用", max_length=120, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "账务分录"
        verbose_name_plural = "账务分录"


class ReconciliationRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "待执行"
        SUCCEEDED = "succeeded", "成功"
        FAILED = "failed", "失败"

    started_at = models.DateTimeField("开始时间", auto_now_add=True)
    finished_at = models.DateTimeField("结束时间", null=True, blank=True)
    status = models.CharField("状态", max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField("备注", blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "对账任务"
        verbose_name_plural = "对账任务"


class ReconciliationItem(models.Model):
    class Kind(models.TextChoices):
        PAID_WITHOUT_LEDGER = "paid_without_ledger", "支付成功未记账"
        ORDER_TRANSACTION_MISMATCH = "order_transaction_mismatch", "订单交易状态不一致"
        AMOUNT_MISMATCH = "amount_mismatch", "金额不一致"
        DUPLICATE_EXTERNAL_ID = "duplicate_external_id", "外部单号重复"

    run = models.ForeignKey(ReconciliationRun, verbose_name="所属任务", on_delete=models.CASCADE, related_name="items")
    transaction = models.ForeignKey(Transaction, verbose_name="关联交易", on_delete=models.SET_NULL, related_name="reconciliation_items", null=True, blank=True)
    payment = models.ForeignKey("payments.Payment", verbose_name="关联支付", on_delete=models.SET_NULL, related_name="reconciliation_items", null=True, blank=True)
    kind = models.CharField("异常类型", max_length=50, choices=Kind.choices)
    payload = models.JSONField("异常详情", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "对账异常"
        verbose_name_plural = "对账异常"


class RiskAssessment(models.Model):
    class Decision(models.TextChoices):
        ALLOW = "allow", "放行"
        REVIEW = "review", "人工审核"
        BLOCK = "block", "阻断"

    transaction = models.ForeignKey(Transaction, verbose_name="关联交易", on_delete=models.CASCADE, related_name="risk_assessments")
    decision = models.CharField("决策", max_length=20, choices=Decision.choices, default=Decision.ALLOW)
    score = models.PositiveIntegerField("风险分", default=0)
    triggered_rules = models.JSONField("命中规则", default=list, blank=True)
    payload = models.JSONField("风险上下文", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "风控评估"
        verbose_name_plural = "风控评估"
