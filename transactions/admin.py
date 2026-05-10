from django.contrib import admin, messages
from django.utils import timezone

from .models import (
    AccountBalanceSnapshot,
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
    ReconciliationItem,
    ReconciliationRun,
    Refund,
    RiskAssessment,
    SettlementRecord,
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
    list_display = (
        "order_number",
        "kind",
        "provider",
        "status",
        "risk_status",
        "amount",
        "currency",
        "paid_at",
        "created_at",
    )
    list_filter = ("kind", "provider", "status", "risk_status", "currency", "paid_at", "created_at")
    search_fields = ("order__order_number",)
    readonly_fields = ("order_customer", "metadata", "created_at", "updated_at")
    autocomplete_fields = ("order",)
    actions = [request_full_refund]
    fieldsets = (
        ("交易概览", {"fields": ("order", "order_customer", "kind", "provider", "status", "risk_status")}),
        ("金额信息", {"fields": ("amount", "currency", "paid_at")}),
        ("原始数据与审计", {"classes": ("collapse",), "fields": ("metadata", "created_at", "updated_at")}),
    )
    list_select_related = ("order",)
    date_hierarchy = "created_at"
    save_on_top = True

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(
            request,
            extra_context={
                **(extra_context or {}),
                "title": "Transactions",
                "subtitle": "查看交易状态、支付结果与退款入口。",
            },
        )

    def add_view(self, request, form_url="", extra_context=None):
        return super().add_view(
            request,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "新增交易",
                "subtitle": "录入关联订单、金额、支付渠道与状态。",
            },
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "编辑交易",
                "subtitle": "维护交易状态、金额、支付结果与风控判断。",
            },
        )

    @admin.display(description="订单号", ordering="order__order_number")
    def order_number(self, obj):
        return obj.order.order_number

    @admin.display(description="客户")
    def order_customer(self, obj):
        return f"{obj.order.customer_name} / {obj.order.customer_email}"


@admin.register(TransactionEvent)
class TransactionEventAdmin(admin.ModelAdmin):
    list_display = ("order_number", "transaction", "payment", "event_type", "source", "idempotency_key", "created_at")
    list_filter = ("event_type", "source", "created_at")
    search_fields = ("idempotency_key", "transaction__order__order_number", "payment__external_payment_id")
    readonly_fields = ("payload", "created_at")
    autocomplete_fields = ("transaction", "payment")
    fieldsets = (
        ("事件概览", {"fields": ("transaction", "payment", "event_type", "source", "idempotency_key")}),
        ("事件数据", {"classes": ("collapse",), "fields": ("payload", "created_at")}),
    )
    list_select_related = ("transaction__order", "payment")
    date_hierarchy = "created_at"
    save_on_top = True

    @admin.display(description="订单号", ordering="transaction__order__order_number")
    def order_number(self, obj):
        return obj.transaction.order.order_number




@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "transaction",
        "payment",
        "amount",
        "currency",
        "status",
        "provider_refund_id",
        "failure_reason",
        "completed_at",
        "created_at",
    )
    list_filter = ("status", "currency", "submitted_at", "completed_at", "created_at")
    search_fields = ("provider_refund_id", "transaction__order__order_number")
    readonly_fields = ("transaction_customer", "raw_payload", "created_at", "updated_at")
    autocomplete_fields = ("transaction", "payment")
    actions = [submit_refunds, mark_refund_processing, mark_refund_succeeded, mark_refund_failed]
    fieldsets = (
        ("退款概览", {"fields": ("transaction", "transaction_customer", "payment", "amount", "currency", "status")}),
        (
            "处理链路",
            {
                "fields": (
                    "provider_refund_id",
                    "reason",
                    "operator_notes",
                    "failure_reason",
                    "submitted_at",
                    "completed_at",
                )
            },
        ),
        ("原始数据与审计", {"classes": ("collapse",), "fields": ("raw_payload", "created_at", "updated_at")}),
    )
    list_select_related = ("transaction__order", "payment")
    date_hierarchy = "created_at"
    save_on_top = True

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(
            request,
            extra_context={
                **(extra_context or {}),
                "title": "Refunds",
                "subtitle": "查看退款申请、处理状态、失败原因与完成结果。",
            },
        )

    def add_view(self, request, form_url="", extra_context=None):
        return super().add_view(
            request,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "新增退款",
                "subtitle": "录入退款金额、币种、关联交易和原因。",
            },
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "编辑退款",
                "subtitle": "维护退款金额、状态、失败原因和完成信息。",
            },
        )

    @admin.display(description="订单号")
    def order_number(self, obj):
        return obj.transaction.order.order_number

    @admin.display(description="客户")
    def transaction_customer(self, obj):
        return f"{obj.transaction.order.customer_name} / {obj.transaction.order.customer_email}"


@admin.register(LedgerAccount)
class LedgerAccountAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "account_type", "currency", "is_active", "updated_at")
    list_filter = ("account_type", "currency", "is_active")
    search_fields = ("code", "name")
    fieldsets = (
        ("账户概览", {"fields": ("code", "name", "account_type", "currency", "is_active")}),
        ("时间与审计", {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at")
    save_on_top = True


@admin.register(LedgerTransaction)
class LedgerTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "reference_no",
        "order_number",
        "kind",
        "payment",
        "refund",
        "currency",
        "gross_amount",
        "net_amount",
        "occurred_at",
    )
    list_filter = ("kind", "currency", "occurred_at")
    search_fields = ("reference_no", "order__order_number")
    readonly_fields = ("metadata", "created_at")
    autocomplete_fields = ("order", "payment", "refund")
    fieldsets = (
        ("账务概览", {"fields": ("reference_no", "kind", "order", "payment", "refund")}),
        ("金额信息", {"fields": ("currency", "gross_amount", "net_amount", "occurred_at")}),
        ("扩展与审计", {"classes": ("collapse",), "fields": ("metadata", "created_at")}),
    )
    list_select_related = ("order", "payment", "refund")
    date_hierarchy = "occurred_at"
    save_on_top = True

    @admin.display(description="订单号", ordering="order__order_number")
    def order_number(self, obj):
        if not obj.order_id:
            return "-"
        return obj.order.order_number


@admin.register(LedgerEntry)
class LedgerEntryAdmin(admin.ModelAdmin):
    list_display = (
        "order_number",
        "ledger_transaction",
        "account",
        "direction",
        "amount",
        "currency",
        "entry_type",
        "external_reference",
        "created_at",
    )
    list_filter = ("direction", "currency", "entry_type", "created_at")
    search_fields = ("transaction__order__order_number", "external_reference", "account__code", "ledger_transaction__reference_no")
    autocomplete_fields = ("transaction", "ledger_transaction", "payment", "refund", "account")
    fieldsets = (
        ("分录概览", {"fields": ("transaction", "ledger_transaction", "payment", "refund", "account")}),
        ("记账信息", {"fields": ("direction", "amount", "currency", "entry_type", "external_reference", "description")}),
        ("时间与审计", {"classes": ("collapse",), "fields": ("created_at",)}),
    )
    readonly_fields = ("created_at",)
    list_select_related = ("transaction__order", "ledger_transaction", "payment", "refund", "account")
    date_hierarchy = "created_at"
    save_on_top = True

    @admin.display(description="订单号", ordering="transaction__order__order_number")
    def order_number(self, obj):
        return obj.transaction.order.order_number


@admin.register(AccountBalanceSnapshot)
class AccountBalanceSnapshotAdmin(admin.ModelAdmin):
    list_display = ("account", "currency", "balance", "available_balance", "pending_balance", "snapshot_at")
    list_filter = ("currency", "snapshot_at")
    search_fields = ("account__code", "account__name")
    autocomplete_fields = ("account",)
    fieldsets = (
        ("余额快照", {"fields": ("account", "currency", "balance", "available_balance", "pending_balance", "snapshot_at")}),
        ("时间与审计", {"classes": ("collapse",), "fields": ("created_at",)}),
    )
    readonly_fields = ("created_at",)
    list_select_related = ("account",)
    date_hierarchy = "snapshot_at"
    save_on_top = True


@admin.register(SettlementRecord)
class SettlementRecordAdmin(admin.ModelAdmin):
    list_display = ("settlement_no", "provider", "currency", "gross_amount", "fee_amount", "net_amount", "status", "settled_at", "created_at")
    list_filter = ("provider", "currency", "status", "settled_at", "created_at")
    search_fields = ("settlement_no",)
    readonly_fields = ("payload", "created_at")
    fieldsets = (
        ("结算概览", {"fields": ("settlement_no", "provider", "status", "currency")}),
        ("金额信息", {"fields": ("gross_amount", "fee_amount", "net_amount", "settled_at")}),
        ("原始数据与审计", {"classes": ("collapse",), "fields": ("payload", "created_at")}),
    )
    date_hierarchy = "created_at"
    save_on_top = True


@admin.register(ReconciliationRun)
class ReconciliationRunAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "started_at", "finished_at", "notes")
    list_filter = ("status", "started_at")
    search_fields = ("id", "notes")
    readonly_fields = ("started_at", "finished_at")
    fieldsets = (
        ("任务概览", {"fields": ("status", "notes")}),
        ("时间与审计", {"classes": ("collapse",), "fields": ("started_at", "finished_at")}),
    )
    date_hierarchy = "started_at"
    save_on_top = True


@admin.register(ReconciliationItem)
class ReconciliationItemAdmin(admin.ModelAdmin):
    list_display = ("run", "order_number", "payment", "kind", "created_at")
    list_filter = ("kind", "created_at")
    readonly_fields = ("payload", "created_at")
    autocomplete_fields = ("run", "transaction", "payment")
    fieldsets = (
        ("异常概览", {"fields": ("run", "transaction", "payment", "kind")}),
        ("异常详情", {"classes": ("collapse",), "fields": ("payload", "created_at")}),
    )
    list_select_related = ("run", "transaction__order", "payment")
    date_hierarchy = "created_at"
    save_on_top = True

    @admin.display(description="订单号", ordering="transaction__order__order_number")
    def order_number(self, obj):
        if not obj.transaction_id:
            return "-"
        return obj.transaction.order.order_number


@admin.register(RiskAssessment)
class RiskAssessmentAdmin(admin.ModelAdmin):
    list_display = ("order_number", "transaction", "decision", "score", "phase", "created_at")
    list_filter = ("decision", "created_at")
    search_fields = ("transaction__order__order_number", "payload")
    readonly_fields = ("triggered_rules", "payload", "created_at")
    autocomplete_fields = ("transaction",)
    fieldsets = (
        ("风控概览", {"fields": ("transaction", "decision", "score", "phase")}),
        ("规则与上下文", {"fields": ("triggered_rules", "payload")}),
        ("时间与审计", {"classes": ("collapse",), "fields": ("created_at",)}),
    )
    date_hierarchy = "created_at"
    save_on_top = True

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(
            request,
            extra_context={
                **(extra_context or {}),
                "title": "Risk",
                "subtitle": "查看风控评估、命中规则与人工审核/阻断决策。",
            },
        )

    def add_view(self, request, form_url="", extra_context=None):
        return super().add_view(
            request,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "新增风控评估",
                "subtitle": "录入关联交易、风险分与命中规则。",
            },
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "编辑风控评估",
                "subtitle": "维护风险决策、命中规则与风险上下文。",
            },
        )

    @admin.display(description="订单号")
    def order_number(self, obj):
        return obj.transaction.order.order_number

    @admin.display(description="阶段")
    def phase(self, obj):
        return obj.payload.get("phase", "-")
