from django.contrib import admin, messages
from django.utils import timezone

from .models import (
    LedgerAccount,
    LedgerEntry,
    ReconciliationItem,
    ReconciliationRun,
    Refund,
    RiskAssessment,
    Transaction,
    TransactionEvent,
)
from .refunds import RefundCenter


@admin.action(description="为选中交易发起全额退款")
def request_full_refund(modeladmin, request, queryset):
    success_count = 0
    for transaction_obj in queryset:
        try:
            refund = RefundCenter.create_request(
                transaction_obj,
                amount=transaction_obj.amount,
                currency=transaction_obj.currency,
                reason="admin full refund",
            )
            RefundCenter.submit(refund)
            success_count += 1
        except Exception as exc:
            modeladmin.message_user(request, f"交易 {transaction_obj.id} 退款失败：{exc}", level=messages.ERROR)
    if success_count:
        modeladmin.message_user(request, f"已发起 {success_count} 笔退款", level=messages.SUCCESS)


@admin.action(description="提交选中退款")
def submit_refunds(modeladmin, request, queryset):
    success_count = 0
    for refund in queryset:
        try:
            RefundCenter.mark_processing(refund, payload={"submitted_from": "admin"}, operator_notes="admin submit")
            RefundCenter.submit(refund)
            success_count += 1
        except Exception as exc:
            modeladmin.message_user(request, f"退款 {refund.id} 提交失败：{exc}", level=messages.ERROR)
    if success_count:
        modeladmin.message_user(request, f"已提交 {success_count} 笔退款", level=messages.SUCCESS)


@admin.action(description="标记退款处理中")
def mark_refund_processing(modeladmin, request, queryset):
    updated = 0
    for refund in queryset:
        try:
            RefundCenter.mark_processing(refund, payload={"updated_from": "admin"}, operator_notes="admin mark processing")
        except Exception as exc:
            modeladmin.message_user(request, f"退款 {refund.id} 标记处理中失败：{exc}", level=messages.ERROR)
        else:
            updated += 1
    if updated:
        modeladmin.message_user(request, f"已标记 {updated} 笔退款处理中", level=messages.SUCCESS)


@admin.action(description="标记退款成功")
def mark_refund_succeeded(modeladmin, request, queryset):
    updated = 0
    for refund in queryset:
        try:
            RefundCenter.mark_succeeded(
                refund,
                payload={"updated_from": "admin", "completed_at": timezone.now().isoformat()},
                provider_refund_id=f"manual-{refund.id}",
            )
        except Exception as exc:
            modeladmin.message_user(request, f"退款 {refund.id} 标记成功失败：{exc}", level=messages.ERROR)
        else:
            updated += 1
    if updated:
        modeladmin.message_user(request, f"已标记 {updated} 笔退款成功", level=messages.SUCCESS)


@admin.action(description="标记退款失败")
def mark_refund_failed(modeladmin, request, queryset):
    updated = 0
    for refund in queryset:
        try:
            RefundCenter.mark_failed(
                refund,
                payload={"updated_from": "admin"},
                failure_reason="admin marked failed",
            )
        except Exception as exc:
            modeladmin.message_user(request, f"退款 {refund.id} 标记失败失败：{exc}", level=messages.ERROR)
        else:
            updated += 1
    if updated:
        modeladmin.message_user(request, f"已标记 {updated} 笔退款失败", level=messages.SUCCESS)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("order", "kind", "provider", "status", "risk_status", "amount", "currency", "paid_at", "created_at")
    list_filter = ("kind", "provider", "status", "risk_status", "currency", "created_at")
    search_fields = ("order__order_number",)
    readonly_fields = ("metadata", "created_at", "updated_at")
    actions = [request_full_refund]


@admin.register(TransactionEvent)
class TransactionEventAdmin(admin.ModelAdmin):
    list_display = ("transaction", "payment", "event_type", "source", "idempotency_key", "created_at")
    list_filter = ("event_type", "source", "created_at")
    search_fields = ("idempotency_key", "transaction__order__order_number", "payment__external_payment_id")
    readonly_fields = ("payload", "created_at")


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = (
        "transaction",
        "order_number",
        "payment",
        "amount",
        "currency",
        "status",
        "provider_refund_id",
        "failure_reason",
        "completed_at",
        "created_at",
    )
    list_filter = ("status", "currency", "created_at")
    search_fields = ("provider_refund_id", "transaction__order__order_number")
    readonly_fields = ("raw_payload", "created_at", "updated_at")
    actions = [submit_refunds, mark_refund_processing, mark_refund_succeeded, mark_refund_failed]

    @admin.display(description="订单号")
    def order_number(self, obj):
        return obj.transaction.order.order_number


@admin.register(LedgerAccount)
class LedgerAccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("code", "name")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = ("transaction", "payment", "account", "direction", "amount", "currency", "entry_type", "created_at")
    list_filter = ("direction", "currency", "entry_type", "created_at")
    search_fields = ("transaction__order__order_number", "external_reference", "account__code")


@admin.register(ReconciliationRun)
class ReconciliationRunAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "started_at", "finished_at")
    list_filter = ("status", "started_at")
    readonly_fields = ("started_at", "finished_at")


@admin.register(ReconciliationItem)
class ReconciliationItemAdmin(admin.ModelAdmin):
    list_display = ("run", "transaction", "payment", "kind", "created_at")
    list_filter = ("kind", "created_at")
    readonly_fields = ("payload", "created_at")


@admin.register(RiskAssessment)
class RiskAssessmentAdmin(admin.ModelAdmin):
    list_display = ("transaction", "decision", "score", "phase", "created_at")
    list_filter = ("decision", "created_at")
    search_fields = ("transaction__order__order_number", "payload")
    readonly_fields = ("triggered_rules", "payload", "created_at")

    @admin.display(description="阶段")
    def phase(self, obj):
        return obj.payload.get("phase", "-")
