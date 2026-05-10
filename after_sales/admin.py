from django.contrib import admin, messages

from shipping.services import ShipmentOpsService
from transactions.refunds import RefundCenter

from .models import AfterSalesCase, AfterSalesEvent


class AfterSalesEventInline(admin.TabularInline):
    model = AfterSalesEvent
    extra = 0
    readonly_fields = ("event_type", "message", "payload", "created_at")
    can_delete = False


@admin.action(description="标记为处理中")
def mark_processing(modeladmin, request, queryset):
    updated = queryset.update(status=AfterSalesCase.Status.PROCESSING)
    for case in queryset:
        AfterSalesEvent.objects.create(case=case, event_type="processing", message="售后单进入处理中")
    if updated:
        modeladmin.message_user(request, f"已更新 {updated} 个售后单为处理中。", level=messages.SUCCESS)


@admin.action(description="标记为已解决")
def mark_resolved(modeladmin, request, queryset):
    updated = queryset.update(status=AfterSalesCase.Status.RESOLVED)
    for case in queryset:
        AfterSalesEvent.objects.create(case=case, event_type="resolved", message="售后单已解决")
    if updated:
        modeladmin.message_user(request, f"已更新 {updated} 个售后单为已解决。", level=messages.SUCCESS)


@admin.action(description="标记为已关闭")
def mark_closed(modeladmin, request, queryset):
    updated = queryset.update(status=AfterSalesCase.Status.CLOSED)
    for case in queryset:
        AfterSalesEvent.objects.create(case=case, event_type="closed", message="售后单已关闭")
    if updated:
        modeladmin.message_user(request, f"已关闭 {updated} 个售后单。", level=messages.SUCCESS)


@admin.action(description="创建退款请求")
def create_refund_request(modeladmin, request, queryset):
    created = 0
    for case in queryset:
        try:
            if case.refund_id:
                continue
            transaction_obj = case.order.transactions.order_by("-created_at").first()
            if transaction_obj is None:
                raise ValueError("订单未关联交易，无法创建退款")
            refund = RefundCenter.create_request(
                transaction_obj,
                amount=transaction_obj.amount,
                currency=transaction_obj.currency,
                reason=case.reason or case.get_case_type_display(),
            )
            case.refund = refund
            case.save(update_fields=["refund", "updated_at"])
            AfterSalesEvent.objects.create(
                case=case,
                event_type="refund_requested",
                message="已创建退款请求",
                payload={"refund_id": refund.id},
            )
            created += 1
        except Exception as exc:
            modeladmin.message_user(request, f"{case.case_no}: {exc}", level=messages.ERROR)
    if created:
        modeladmin.message_user(request, f"已为 {created} 个售后单创建退款请求。", level=messages.SUCCESS)


@admin.action(description="创建补发发货单")
def create_resend_shipment(modeladmin, request, queryset):
    created = 0
    for case in queryset:
        try:
            shipment = ShipmentOpsService.create_manual_shipment(
                case.order,
                carrier_name="manual_resend",
                operator_notes=f"after-sales resend for {case.case_no}",
            )
            case.shipment = shipment
            case.save(update_fields=["shipment", "updated_at"])
            AfterSalesEvent.objects.create(
                case=case,
                event_type="resend_created",
                message="已创建补发发货单",
                payload={"shipment_id": shipment.id},
            )
            created += 1
        except Exception as exc:
            modeladmin.message_user(request, f"{case.case_no}: {exc}", level=messages.ERROR)
    if created:
        modeladmin.message_user(request, f"已创建 {created} 个补发发货单。", level=messages.SUCCESS)


@admin.register(AfterSalesCase)
class AfterSalesCaseAdmin(admin.ModelAdmin):
    list_display = (
        "case_no",
        "order_number",
        "case_type",
        "status",
        "customer_summary",
        "refund",
        "shipment",
        "created_at",
    )
    list_filter = ("case_type", "status", "created_at")
    search_fields = ("case_no", "order__order_number", "reason", "customer_message")
    readonly_fields = (
        "case_no",
        "order_customer",
        "linked_chat_session",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("order", "shipment", "refund", "chat_session")
    inlines = [AfterSalesEventInline]
    actions = [mark_processing, mark_resolved, mark_closed, create_refund_request, create_resend_shipment]
    fieldsets = (
        (
            "售后概览",
            {
                "fields": (
                    "case_no",
                    "order",
                    "order_customer",
                    "case_type",
                    "status",
                    "linked_chat_session",
                )
            },
        ),
        ("客户诉求", {"fields": ("reason", "customer_message", "internal_notes", "resolution_summary")}),
        ("关联处理链路", {"fields": ("refund", "shipment")}),
        ("时间与审计", {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )
    list_select_related = ("order", "refund", "shipment", "chat_session")
    date_hierarchy = "created_at"
    save_on_top = True

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(
            request,
            extra_context={
                **(extra_context or {}),
                "title": "After-sales",
                "subtitle": "处理售后单、补发协作与退款联动。",
            },
        )

    def add_view(self, request, form_url="", extra_context=None):
        return super().add_view(
            request,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "新增售后单",
                "subtitle": "录入售后类型、客户诉求和关联订单。",
            },
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "编辑售后单",
                "subtitle": "维护售后状态、客户诉求、退款与补发信息。",
            },
        )

    @admin.display(description="订单号", ordering="order__order_number")
    def order_number(self, obj):
        return obj.order.order_number

    @admin.display(description="客户")
    def customer_summary(self, obj):
        return f"{obj.order.customer_name} / {obj.order.customer_email}"

    @admin.display(description="客户信息")
    def order_customer(self, obj):
        return f"{obj.order.customer_name} / {obj.order.customer_email} / {obj.order.customer_phone or '-'}"

    @admin.display(description="关联会话")
    def linked_chat_session(self, obj):
        if not obj.chat_session_id:
            return "-"
        return str(obj.chat_session)


@admin.register(AfterSalesEvent)
class AfterSalesEventAdmin(admin.ModelAdmin):
    list_display = ("case", "order_number", "event_type", "message", "created_at")
    list_filter = ("event_type", "created_at")
    search_fields = ("case__case_no", "case__order__order_number", "message")
    readonly_fields = ("payload", "created_at")
    autocomplete_fields = ("case",)
    fieldsets = (
        ("事件概览", {"fields": ("case", "event_type", "message")}),
        ("事件数据", {"classes": ("collapse",), "fields": ("payload", "created_at")}),
    )
    list_select_related = ("case__order",)
    date_hierarchy = "created_at"
    save_on_top = True

    @admin.display(description="订单号", ordering="case__order__order_number")
    def order_number(self, obj):
        return obj.case.order.order_number
