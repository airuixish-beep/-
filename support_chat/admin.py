from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from .models import ChatMessage, ChatOfflineMessage, ChatSession


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "visitor_name",
        "visitor_email",
        "visitor_language",
        "status",
        "last_message_at",
        "created_at",
    )
    list_filter = ("status", "visitor_language", "operator_language", "created_at")
    search_fields = ("visitor_name", "visitor_email", "public_token")
    readonly_fields = ("public_token", "last_message_at", "last_seen_by_visitor_at", "last_seen_by_operator_at", "created_at", "updated_at")

    def get_model_perms(self, request):
        return {}

    def changelist_view(self, request, extra_context=None):
        return redirect(reverse("support_chat_console"))


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "sender_type", "original_language", "translation_status", "created_at")
    list_filter = ("sender_type", "translation_status", "original_language", "created_at")
    search_fields = ("body_original", "body_for_visitor", "body_for_operator", "session__public_token")
    readonly_fields = ("translation_meta", "created_at")

    def get_model_perms(self, request):
        return {}


@admin.register(ChatOfflineMessage)
class ChatOfflineMessageAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "contact", "related_order_no", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("name", "contact", "related_order_no", "message")
    readonly_fields = ("created_at", "updated_at")
