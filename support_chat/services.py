from dataclasses import dataclass

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.utils import timezone

from .models import ChatMessage, ChatSession


@dataclass
class TranslationResult:
    text: str
    detected_language: str
    status: str
    meta: dict


class TranslationService:
    def __init__(self):
        self.provider = getattr(settings, "CHAT_TRANSLATION_PROVIDER", "mock")
        self.api_key = getattr(settings, "CHAT_TRANSLATION_API_KEY", "")

    def detect_language(self, text, fallback_language):
        normalized = (text or "").strip()
        if not normalized:
            return fallback_language
        if all(ord(char) < 128 for char in normalized):
            return "en"
        return fallback_language or "zh-hans"

    def translate(self, text, source_lang, target_lang):
        if not text:
            return TranslationResult(text="", detected_language=source_lang, status=ChatMessage.TranslationStatus.NOT_NEEDED, meta={"provider": self.provider})
        if source_lang == target_lang:
            return TranslationResult(
                text=text,
                detected_language=source_lang,
                status=ChatMessage.TranslationStatus.NOT_NEEDED,
                meta={"provider": self.provider, "reason": "same_language"},
            )
        if self.provider == "mock" or not self.api_key:
            return TranslationResult(
                text=f"[{target_lang}] {text}",
                detected_language=source_lang,
                status=ChatMessage.TranslationStatus.TRANSLATED,
                meta={"provider": self.provider, "mock": True},
            )
        if self.provider == "libretranslate":
            response = requests.post(
                "https://libretranslate.com/translate",
                data={
                    "q": text,
                    "source": source_lang,
                    "target": target_lang,
                    "api_key": self.api_key,
                    "format": "text",
                },
                timeout=15,
            )
            response.raise_for_status()
            payload = response.json()
            return TranslationResult(
                text=payload.get("translatedText", text),
                detected_language=source_lang,
                status=ChatMessage.TranslationStatus.TRANSLATED,
                meta={"provider": self.provider},
            )
        raise ValueError(f"Unsupported translation provider: {self.provider}")


translation_service = TranslationService()


def normalize_language(language):
    normalized = (language or "").strip().lower().replace("_", "-")
    if not normalized:
        return getattr(settings, "CHAT_DEFAULT_OPERATOR_LANGUAGE", "zh-hans")
    if normalized.startswith("zh"):
        return "zh-hans"
    if normalized.startswith("en"):
        return "en"
    if normalized.startswith("ja"):
        return "ja"
    if normalized.startswith("ko"):
        return "ko"
    return normalized.split(",")[0]


def get_preferred_visitor_language(request):
    explicit = request.POST.get("language") or request.GET.get("language")
    if explicit:
        return normalize_language(explicit)
    accept_language = request.META.get("HTTP_ACCEPT_LANGUAGE", "")
    primary = accept_language.split(",")[0]
    return normalize_language(primary or "en")


@transaction.atomic
def create_or_resume_session(*, token=None, visitor_name="", visitor_email="", visitor_language="en"):
    session = None
    if token:
        session = ChatSession.objects.filter(public_token=token).first()
    if session and session.status != ChatSession.Status.CLOSED:
        updated_fields = []
        if visitor_name and session.visitor_name != visitor_name:
            session.visitor_name = visitor_name
            updated_fields.append("visitor_name")
        if visitor_email and session.visitor_email != visitor_email:
            session.visitor_email = visitor_email
            updated_fields.append("visitor_email")
        normalized_language = normalize_language(visitor_language)
        if normalized_language and session.visitor_language != normalized_language:
            session.visitor_language = normalized_language
            updated_fields.append("visitor_language")
        if updated_fields:
            session.save(update_fields=[*updated_fields, "updated_at"])
        return session, False

    session = ChatSession.objects.create(
        visitor_name=visitor_name,
        visitor_email=visitor_email,
        visitor_language=normalize_language(visitor_language),
        operator_language=normalize_language(getattr(settings, "CHAT_DEFAULT_OPERATOR_LANGUAGE", "zh-hans")),
        status=ChatSession.Status.OPEN,
    )
    return session, True


@transaction.atomic
def create_message(*, session, sender_type, text, sender_user=None):
    normalized_text = (text or "").strip()
    if not normalized_text:
        raise ValueError("Message text cannot be empty.")

    if sender_type == ChatMessage.SenderType.VISITOR:
        source_language = translation_service.detect_language(normalized_text, session.visitor_language)
        target_language = session.operator_language
        viewer_language = session.visitor_language
    elif sender_type == ChatMessage.SenderType.OPERATOR:
        source_language = translation_service.detect_language(normalized_text, session.operator_language)
        target_language = session.visitor_language
        viewer_language = session.operator_language
    else:
        source_language = normalize_language(session.operator_language)
        target_language = source_language
        viewer_language = source_language

    source_language = normalize_language(source_language)
    target_language = normalize_language(target_language)
    viewer_language = normalize_language(viewer_language)

    translation_status = ChatMessage.TranslationStatus.NOT_NEEDED
    translation_meta = {"provider": translation_service.provider}
    body_for_visitor = normalized_text if sender_type != ChatMessage.SenderType.OPERATOR else ""
    body_for_operator = normalized_text if sender_type != ChatMessage.SenderType.VISITOR else ""

    try:
        translated = translation_service.translate(normalized_text, source_language, target_language)
        translation_status = translated.status
        translation_meta = translated.meta
        if sender_type == ChatMessage.SenderType.VISITOR:
            body_for_visitor = normalized_text
            body_for_operator = translated.text
        elif sender_type == ChatMessage.SenderType.OPERATOR:
            body_for_visitor = translated.text
            body_for_operator = normalized_text
        else:
            body_for_visitor = normalized_text
            body_for_operator = normalized_text
    except Exception as exc:
        translation_status = ChatMessage.TranslationStatus.FAILED
        translation_meta = {"provider": translation_service.provider, "error": str(exc)}
        body_for_visitor = normalized_text
        body_for_operator = normalized_text

    message = ChatMessage.objects.create(
        session=session,
        sender_type=sender_type,
        sender_user=sender_user,
        body_original=normalized_text,
        original_language=source_language,
        body_for_visitor=body_for_visitor,
        body_for_operator=body_for_operator,
        translation_status=translation_status,
        translation_meta=translation_meta,
    )
    message.mark_session_activity()
    return message


def serialize_message(message, *, viewer):
    display_text = message.display_for_visitor if viewer == "visitor" else message.display_for_operator
    return {
        "id": message.id,
        "sender_type": message.sender_type,
        "text": display_text,
        "original_text": message.body_original,
        "original_language": message.original_language,
        "translation_status": message.translation_status,
        "created_at": message.created_at.isoformat(),
    }


def get_incremental_messages(session, *, after_id=0, viewer="visitor"):
    messages = session.messages.filter(id__gt=after_id).select_related("sender_user")
    return [serialize_message(message, viewer=viewer) for message in messages]


def mark_session_seen(session, *, viewer):
    now = timezone.now()
    if viewer == "visitor":
        session.last_seen_by_visitor_at = now
        session.save(update_fields=["last_seen_by_visitor_at", "updated_at"])
    else:
        session.last_seen_by_operator_at = now
        session.save(update_fields=["last_seen_by_operator_at", "updated_at"])


def get_session_queryset():
    last_message_preview = Subquery(
        ChatMessage.objects.filter(session=OuterRef("pk")).order_by("-id").values("body_for_operator")[:1]
    )
    last_message_preview_visitor = Subquery(
        ChatMessage.objects.filter(session=OuterRef("pk")).order_by("-id").values("body_for_visitor")[:1]
    )
    last_message_sender_type = Subquery(
        ChatMessage.objects.filter(session=OuterRef("pk")).order_by("-id").values("sender_type")[:1]
    )
    unread_for_operator_count = Count(
        "messages",
        filter=Q(messages__sender_type=ChatMessage.SenderType.VISITOR)
        & (Q(last_seen_by_operator_at__isnull=True) | Q(messages__created_at__gt=F("last_seen_by_operator_at"))),
        distinct=True,
    )
    unread_for_visitor_count = Count(
        "messages",
        filter=Q(messages__sender_type=ChatMessage.SenderType.OPERATOR)
        & (Q(last_seen_by_visitor_at__isnull=True) | Q(messages__created_at__gt=F("last_seen_by_visitor_at"))),
        distinct=True,
    )
    return ChatSession.objects.annotate(
        last_message_preview=last_message_preview,
        last_message_preview_visitor=last_message_preview_visitor,
        last_message_sender_type=last_message_sender_type,
        unread_for_operator_count=unread_for_operator_count,
        unread_for_visitor_count=unread_for_visitor_count,
    )


def get_session_summary(session):
    visitor_name = session.visitor_name or "Anonymous visitor"
    last_message_preview = getattr(session, "last_message_preview", "") or ""
    last_message_preview_visitor = getattr(session, "last_message_preview_visitor", "") or ""
    last_message_sender_type = getattr(session, "last_message_sender_type", "") or ""
    unread_for_operator = getattr(session, "unread_for_operator_count", None)
    unread_for_visitor = getattr(session, "unread_for_visitor_count", None)
    return {
        "id": session.id,
        "public_token": session.public_token,
        "status": session.status,
        "visitor_name": visitor_name,
        "visitor_email": session.visitor_email,
        "visitor_language": session.visitor_language,
        "operator_language": session.operator_language,
        "last_message_at": session.last_message_at.isoformat() if session.last_message_at else None,
        "unread_for_operator": session.unread_for_operator if unread_for_operator is None else unread_for_operator,
        "unread_for_visitor": session.unread_for_visitor if unread_for_visitor is None else unread_for_visitor,
        "last_message_preview": last_message_preview[:80],
        "last_message_preview_visitor": last_message_preview_visitor[:80],
        "last_message_sender_type": last_message_sender_type,
        "has_contact_details": bool(session.visitor_name or session.visitor_email),
    }
