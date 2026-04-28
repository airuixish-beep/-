import secrets

from django.db import models

from orders.models import Order
from shipping.models import Shipment
from support_chat.models import ChatSession
from transactions.models import Refund


class AfterSalesCase(models.Model):
    class CaseType(models.TextChoices):
        REFUND_ONLY = "refund_only", "仅退款"
        RETURN_REFUND = "return_refund", "退货退款"
        RESEND = "resend", "补发"
        LOGISTICS_EXCEPTION = "logistics_exception", "物流异常"
        OTHER = "other", "其他"

    class Status(models.TextChoices):
        OPEN = "open", "待处理"
        PROCESSING = "processing", "处理中"
        RESOLVED = "resolved", "已解决"
        CLOSED = "closed", "已关闭"

    case_no = models.CharField("售后单号", max_length=32, unique=True, blank=True)
    order = models.ForeignKey(Order, verbose_name="关联订单", on_delete=models.CASCADE, related_name="after_sales_cases")
    shipment = models.ForeignKey(
        Shipment,
        verbose_name="关联发货单",
        on_delete=models.SET_NULL,
        related_name="after_sales_cases",
        null=True,
        blank=True,
    )
    refund = models.ForeignKey(
        Refund,
        verbose_name="关联退款",
        on_delete=models.SET_NULL,
        related_name="after_sales_cases",
        null=True,
        blank=True,
    )
    chat_session = models.ForeignKey(
        ChatSession,
        verbose_name="关联客服会话",
        on_delete=models.SET_NULL,
        related_name="after_sales_cases",
        null=True,
        blank=True,
    )
    case_type = models.CharField("售后类型", max_length=32, choices=CaseType.choices, default=CaseType.REFUND_ONLY)
    status = models.CharField("售后状态", max_length=20, choices=Status.choices, default=Status.OPEN)
    reason = models.CharField("售后原因", max_length=255, blank=True)
    customer_message = models.TextField("客户描述", blank=True)
    internal_notes = models.TextField("内部备注", blank=True)
    resolution_summary = models.TextField("处理结果", blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "售后单"
        verbose_name_plural = "售后单"

    def __str__(self):
        return self.case_no

    def save(self, *args, **kwargs):
        if not self.case_no:
            self.case_no = self.generate_case_no()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_case_no():
        return f"AS{secrets.token_hex(4).upper()}"


class AfterSalesEvent(models.Model):
    case = models.ForeignKey(AfterSalesCase, verbose_name="所属售后单", on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField("事件类型", max_length=40)
    message = models.CharField("事件说明", max_length=255, blank=True)
    payload = models.JSONField("事件数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "售后事件"
        verbose_name_plural = "售后事件"

    def __str__(self):
        return f"{self.case.case_no} - {self.event_type}"
