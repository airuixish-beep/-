import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class ChatSession(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "进行中"
        WAITING_OPERATOR = "waiting_operator", "待客服回复"
        WAITING_VISITOR = "waiting_visitor", "待访客回复"
        CLOSED = "closed", "已关闭"

    public_token = models.CharField("公开令牌", max_length=40, unique=True, editable=False)
    status = models.CharField("会话状态", max_length=20, choices=Status.choices, default=Status.OPEN)
    visitor_name = models.CharField("访客姓名", max_length=100, blank=True)
    visitor_email = models.EmailField("访客邮箱", blank=True)
    visitor_language = models.CharField("访客语言", max_length=20, default="en")
    operator_language = models.CharField("客服语言", max_length=20, default="zh-hans")
    last_message_at = models.DateTimeField("最后消息时间", blank=True, null=True)
    last_seen_by_visitor_at = models.DateTimeField("访客最后查看时间", blank=True, null=True)
    last_seen_by_operator_at = models.DateTimeField("客服最后查看时间", blank=True, null=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        verbose_name = "聊天会话"
        verbose_name_plural = "聊天会话"

    def __str__(self):
        return self.visitor_name or f"访客会话 {self.pk}"

    def save(self, *args, **kwargs):
        if not self.public_token:
            self.public_token = secrets.token_urlsafe(24)
        super().save(*args, **kwargs)

    @property
    def unread_for_operator(self):
        last_seen = self.last_seen_by_operator_at
        queryset = self.messages.filter(sender_type=ChatMessage.SenderType.VISITOR)
        if last_seen:
            queryset = queryset.filter(created_at__gt=last_seen)
        return queryset.count()

    @property
    def unread_for_visitor(self):
        last_seen = self.last_seen_by_visitor_at
        queryset = self.messages.filter(sender_type=ChatMessage.SenderType.OPERATOR)
        if last_seen:
            queryset = queryset.filter(created_at__gt=last_seen)
        return queryset.count()


class ChatMessage(models.Model):
    class SenderType(models.TextChoices):
        VISITOR = "visitor", "访客"
        OPERATOR = "operator", "客服"
        SYSTEM = "system", "系统"

    class TranslationStatus(models.TextChoices):
        TRANSLATED = "translated", "已翻译"
        FAILED = "failed", "翻译失败"
        NOT_NEEDED = "not_needed", "无需翻译"

    session = models.ForeignKey(ChatSession, verbose_name="所属会话", on_delete=models.CASCADE, related_name="messages")
    sender_type = models.CharField("发送方", max_length=20, choices=SenderType.choices)
    sender_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="客服用户",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="chat_messages",
    )
    body_original = models.TextField("原文")
    original_language = models.CharField("原文语言", max_length=20)
    body_for_visitor = models.TextField("面向访客内容")
    body_for_operator = models.TextField("面向客服内容")
    translation_status = models.CharField(
        "翻译状态",
        max_length=20,
        choices=TranslationStatus.choices,
        default=TranslationStatus.NOT_NEEDED,
    )
    translation_meta = models.JSONField("翻译元数据", default=dict, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "聊天消息"
        verbose_name_plural = "聊天消息"

    def __str__(self):
        return f"{self.get_sender_type_display()} - {self.created_at:%Y-%m-%d %H:%M:%S}"

    @property
    def display_for_visitor(self):
        return self.body_for_visitor or self.body_original

    @property
    def display_for_operator(self):
        return self.body_for_operator or self.body_original

    def mark_session_activity(self):
        self.session.last_message_at = self.created_at or timezone.now()
        if self.sender_type == self.SenderType.VISITOR:
            self.session.status = ChatSession.Status.WAITING_OPERATOR
        elif self.sender_type == self.SenderType.OPERATOR:
            self.session.status = ChatSession.Status.WAITING_VISITOR
        self.session.save(update_fields=["last_message_at", "status", "updated_at"])
