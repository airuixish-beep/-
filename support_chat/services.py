import json
import subprocess
from dataclasses import dataclass

import requests
from django.conf import settings
from django.db import transaction
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.utils import timezone

from .models import ChatMessage, ChatSession
from .realtime import broadcast_message_created, broadcast_session_read, broadcast_session_snapshot


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


class OpenClawError(Exception):
    pass


@dataclass
class OpenClawResult:
    text: str
    meta: dict


class OpenClawService:
    def __init__(self):
        self.enabled = getattr(settings, "OPENCLAW_ENABLED", False)
        self.command = getattr(settings, "OPENCLAW_COMMAND", "openclaw")
        self.agent_id = getattr(settings, "OPENCLAW_AGENT_ID", "")
        self.timeout = getattr(settings, "OPENCLAW_TIMEOUT_SECONDS", 60)

    def is_enabled(self):
        return bool(self.enabled and self.command)

    def _build_command(self, *, session_key, prompt):
        command = [
            self.command,
            "agent",
            "--session-id",
            session_key,
            "--message",
            prompt,
            "--json",
            "--timeout",
            str(self.timeout),
        ]
        if self.agent_id:
            command.extend(["--agent", self.agent_id])
        return command

    def _extract_text(self, payload):
        result = payload.get("result") or {}
        payloads = result.get("payloads") or []
        parts = [item.get("text", "").strip() for item in payloads if item.get("text")]
        text = "\n\n".join(part for part in parts if part)
        if not text:
            raise OpenClawError("OpenClaw returned an empty response.")
        return text, result.get("meta") or {}

    def run(self, *, session_key, prompt):
        if not self.is_enabled():
            raise OpenClawError("OpenClaw is not enabled.")
        try:
            completed = subprocess.run(
                self._build_command(session_key=session_key, prompt=prompt),
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout + 5,
            )
        except FileNotFoundError as exc:
            raise OpenClawError("OpenClaw command is not available.") from exc
        except subprocess.TimeoutExpired as exc:
            raise OpenClawError("OpenClaw request timed out.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip()
            raise OpenClawError(detail or "OpenClaw request failed.") from exc

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise OpenClawError("OpenClaw returned invalid JSON.") from exc

        text, meta = self._extract_text(payload)
        return OpenClawResult(text=text, meta=meta)


openclaw_service = OpenClawService()

OPENCLAW_TONE_CHOICES = {
    "soft_guide": "温和导购",
    "direct_conversion": "直接成交",
    "after_sales": "售后客服",
    "neutral": "中性简洁",
}

AFTER_SALES_KEYWORDS = (
    "order",
    "refund",
    "return",
    "exchange",
    "shipping",
    "delivery",
    "tracking",
    "package",
    "damaged",
    "cancel",
    "invoice",
    "物流",
    "退款",
    "退货",
    "换货",
    "订单",
    "快递",
    "发货",
    "收货",
    "包裹",
    "支付失败",
)

SOFT_GUIDE_KEYWORDS = (
    "gift",
    "gifting",
    "recommend",
    "recommendation",
    "choose",
    "choosing",
    "suitable",
    "style",
    "budget",
    "friend",
    "送礼",
    "推荐",
    "挑选",
    "适合",
    "风格",
    "预算",
    "朋友",
    "礼物",
)

DIRECT_CONVERSION_KEYWORDS = (
    "buy",
    "purchase",
    "checkout",
    "stock",
    "available",
    "discount",
    "today",
    "now",
    "下单",
    "购买",
    "库存",
    "优惠",
    "今天发货",
    "立刻",
)


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
    session.refresh_from_db()
    broadcast_message_created(session, message)
    broadcast_session_snapshot(session)
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
    session.refresh_from_db()
    broadcast_session_read(session, viewer)
    return True


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


def normalize_openclaw_tone(tone):
    normalized = (tone or "").strip().lower()
    if normalized in OPENCLAW_TONE_CHOICES:
        return normalized
    return "neutral"


def select_openclaw_tone_for_message(text):
    normalized = (text or "").strip().lower()
    if any(keyword in normalized for keyword in AFTER_SALES_KEYWORDS):
        return "after_sales"
    if any(keyword in normalized for keyword in DIRECT_CONVERSION_KEYWORDS):
        return "direct_conversion"
    if any(keyword in normalized for keyword in SOFT_GUIDE_KEYWORDS):
        return "soft_guide"
    return "neutral"


def build_openclaw_tone_instruction(tone):
    normalized_tone = normalize_openclaw_tone(tone)
    instructions = {
        "soft_guide": "Use a warm luxury retail tone: acknowledge the request, ask one clarifying question if needed, and gently guide the customer toward a suitable recommendation.",
        "direct_conversion": "Use a confident conversion-oriented tone: recommend quickly, reduce decision friction, mention fit or availability when relevant, and guide the customer toward purchase without sounding pushy.",
        "after_sales": "Use a reassuring after-sales tone: focus on resolving the issue clearly, set expectations, and prioritize trust, order support, shipping, or refund clarity.",
        "neutral": "Use a concise and calm support tone: answer clearly, avoid pressure, and keep the response practical and minimal.",
    }
    return instructions[normalized_tone]


def build_openclaw_prompt(session, *, latest_message=None, draft_only=False, target_language=None, tone="neutral"):
    recent_messages = list(session.messages.order_by("-id")[:10])
    recent_messages.reverse()
    transcript = []
    for message in recent_messages:
        transcript.append(f"{message.sender_type}: {message.body_original}")
    if latest_message and (not recent_messages or recent_messages[-1].id != latest_message.id):
        transcript.append(f"{latest_message.sender_type}: {latest_message.body_original}")
    normalized_target_language = normalize_language(target_language or session.operator_language)
    normalized_tone = normalize_openclaw_tone(tone)
    mode = "reply draft" if draft_only else "customer-facing support reply"
    return (
        "You are helping with customer conversations for the XUANOR ecommerce website. "
        f"Write one concise {mode} in {normalized_target_language}. "
        f"Tone style: {OPENCLAW_TONE_CHOICES[normalized_tone]}. "
        f"{build_openclaw_tone_instruction(normalized_tone)} "
        "Do not mention being an AI. Keep the answer natural, commercially useful, and aligned with a refined brand voice. "
        "If the customer intent is unclear, ask at most one clarifying question.\n\n"
        f"Visitor language: {session.visitor_language}\n"
        f"Operator language: {session.operator_language}\n"
        f"Target language: {normalized_target_language}\n"
        f"Conversation status: {session.status}\n"
        f"Tone code: {normalized_tone}\n\n"
        "Recent conversation:\n"
        + ("\n".join(transcript) if transcript else "No prior messages.")
    )


@transaction.atomic
def maybe_create_openclaw_auto_reply(session, *, incoming_message):
    if not getattr(settings, "OPENCLAW_AUTO_REPLY_ENABLED", True):
        return None
    selected_tone = select_openclaw_tone_for_message(incoming_message.body_original)
    result = openclaw_service.run(
        session_key=f"xuanor-chat-{session.id}",
        prompt=build_openclaw_prompt(
            session,
            latest_message=incoming_message,
            draft_only=False,
            target_language=session.visitor_language,
            tone=selected_tone,
        ),
    )
    message = create_message(
        session=session,
        sender_type=ChatMessage.SenderType.OPERATOR,
        text=result.text,
    )
    message.translation_meta = {
        **(message.translation_meta or {}),
        "provider": getattr(settings, "OPENCLAW_SYSTEM_LABEL", "OpenClaw"),
        "auto_generated": True,
        "tone": selected_tone,
        "openclaw": result.meta,
    }
    message.save(update_fields=["translation_meta"])
    return message


def generate_openclaw_draft(session, *, language=None, tone="neutral"):
    if not getattr(settings, "OPENCLAW_DRAFT_ENABLED", True):
        raise OpenClawError("OpenClaw draft generation is disabled.")
    normalized_language = normalize_language(language or session.operator_language)
    normalized_tone = normalize_openclaw_tone(tone)
    return openclaw_service.run(
        session_key=f"xuanor-draft-{session.id}-{normalized_language}-{normalized_tone}",
        prompt=build_openclaw_prompt(
            session,
            draft_only=True,
            target_language=normalized_language,
            tone=normalized_tone,
        ),
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
