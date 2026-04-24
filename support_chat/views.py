import json

from django.conf import settings
from django.contrib import admin
from django.core.cache import cache
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import ChatMessage, ChatOfflineMessage, ChatSession
from .realtime import broadcast_session_closed
from .services import (
    OpenClawError,
    create_message,
    create_or_resume_session,
    generate_openclaw_draft,
    get_incremental_messages,
    get_preferred_visitor_language,
    get_session_queryset,
    get_session_summary,
    mark_session_seen,
    maybe_create_openclaw_auto_reply,
)

SESSION_COOKIE_NAME = "support_chat_token"


def _parse_json_body(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return {}


def _get_public_session(request):
    token = request.COOKIES.get(SESSION_COOKIE_NAME)
    if not token:
        raise Http404("Conversation not found")
    return get_object_or_404(ChatSession, public_token=token)


def _json_error(message, *, status=400):
    return JsonResponse({"error": message}, status=status)


def _create_offline_message(payload):
    name = (payload.get("name") or payload.get("visitor_name") or "").strip()
    contact = (payload.get("contact") or payload.get("visitor_email") or "").strip()
    message = (payload.get("message") or payload.get("text") or "").strip()
    related_order_no = (payload.get("related_order_no") or "").strip()
    if not contact:
        raise ValueError("Please leave an email or other contact detail.")
    if not message:
        raise ValueError("Message text cannot be empty.")
    return ChatOfflineMessage.objects.create(
        name=name,
        contact=contact,
        related_order_no=related_order_no,
        message=message,
    )


def _get_int_query_param(request, name, *, default=0):
    raw_value = request.GET.get(name, default)
    try:
        value = int(raw_value or default)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid '{name}' parameter.")
    if value < 0:
        raise ValueError(f"Invalid '{name}' parameter.")
    return value


def _get_client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")


def _rate_limit_key(request, scope):
    return f"support_chat_rate_limit:{scope}:{_get_client_ip(request)}"


def _is_rate_limited(request, scope, limit):
    window = max(getattr(settings, "CHAT_RATE_LIMIT_WINDOW_SECONDS", 60), 1)
    key = _rate_limit_key(request, scope)
    added = cache.add(key, 1, timeout=window)
    if added:
        return False
    try:
        count = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window)
        return False
    return count > limit


@ensure_csrf_cookie
@require_POST
def session_view(request):
    if _is_rate_limited(request, "session", getattr(settings, "CHAT_SESSION_RATE_LIMIT", 20)):
        return _json_error("Too many chat session requests. Please try again in a minute.", status=429)
    payload = _parse_json_body(request)
    token = request.COOKIES.get(SESSION_COOKIE_NAME)
    visitor_language = payload.get("language") or get_preferred_visitor_language(request)
    session, created = create_or_resume_session(
        token=token,
        visitor_name=(payload.get("visitor_name") or "").strip(),
        visitor_email=(payload.get("visitor_email") or "").strip(),
        related_order_no=(payload.get("related_order_no") or "").strip(),
        visitor_language=visitor_language,
    )
    messages = get_incremental_messages(session, after_id=0, viewer="visitor")
    response = JsonResponse(
        {
            "created": created,
            "session": get_session_summary(session),
            "messages": messages,
            "poll_interval_ms": settings.CHAT_POLL_INTERVAL_MS,
            "background_poll_interval_ms": max(settings.CHAT_POLL_INTERVAL_MS * 3, settings.CHAT_POLL_INTERVAL_MS),
            "widget_enabled": settings.CHAT_WIDGET_ENABLED,
            "realtime_enabled": getattr(settings, "CHAT_REALTIME_ENABLED", True),
            "visitor_websocket_url": f"/ws/support-chat/visitor/{session.public_token}/",
        }
    )
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session.public_token,
        max_age=60 * 60 * 24 * 30,
        samesite="Lax",
        secure=getattr(settings, "CHAT_COOKIE_SECURE", not settings.DEBUG),
        httponly=getattr(settings, "CHAT_COOKIE_HTTPONLY", True),
    )
    return response


@require_GET
def messages_view(request):
    if _is_rate_limited(request, "poll", getattr(settings, "CHAT_POLL_RATE_LIMIT", 240)):
        return _json_error("Too many chat refresh requests. Please try again shortly.", status=429)
    session = _get_public_session(request)
    try:
        after_id = _get_int_query_param(request, "after")
    except ValueError as exc:
        return _json_error(str(exc))
    messages = get_incremental_messages(session, after_id=after_id, viewer="visitor")
    return JsonResponse({"messages": messages, "session": get_session_summary(session)})


@require_POST
def mark_read_view(request):
    session = _get_public_session(request)
    mark_session_seen(session, viewer="visitor")
    return JsonResponse({"ok": True})


@require_POST
def offline_message_view(request):
    payload = _parse_json_body(request)
    try:
        offline_message = _create_offline_message(payload)
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "offline_message_id": offline_message.id})


@require_POST
def visitor_send_view(request):
    if _is_rate_limited(request, "send", getattr(settings, "CHAT_SEND_RATE_LIMIT", 60)):
        return _json_error("You are sending messages too quickly. Please wait a moment and try again.", status=429)
    session = _get_public_session(request)
    if session.status == ChatSession.Status.CLOSED:
        return _json_error("This conversation has ended. Please leave your email and we will follow up.", status=409)
    payload = _parse_json_body(request)
    session, _created = create_or_resume_session(
        token=session.public_token,
        visitor_name=(payload.get("visitor_name") or "").strip(),
        visitor_email=(payload.get("visitor_email") or "").strip(),
        related_order_no=(payload.get("related_order_no") or "").strip(),
        visitor_language=payload.get("language") or session.visitor_language,
    )
    try:
        message = create_message(session=session, sender_type=ChatMessage.SenderType.VISITOR, text=payload.get("text", ""))
    except ValueError as exc:
        return _json_error(str(exc))

    auto_reply = None
    if getattr(settings, "OPENCLAW_ENABLED", False):
        try:
            auto_reply = maybe_create_openclaw_auto_reply(session, incoming_message=message)
        except OpenClawError:
            auto_reply = None

    response_payload = {"message": get_incremental_messages(session, after_id=message.id - 1, viewer="visitor")[0]}
    if auto_reply:
        response_payload["auto_reply"] = get_incremental_messages(session, after_id=auto_reply.id - 1, viewer="visitor")[0]
    return JsonResponse(response_payload)


@require_GET
def operator_console_view(request):
    sessions = list(get_session_queryset()[:20])
    selected_session = sessions[0] if sessions else None
    if request.GET.get("session"):
        selected_session = get_object_or_404(ChatSession, pk=request.GET["session"])
    selected_session_messages = list(selected_session.messages.select_related("sender_user")) if selected_session else []
    context = {
        **admin.site.each_context(request),
        "title": "Support chat",
        "subtitle": "Automatic translation for visitor conversations",
        "sessions": sessions,
        "selected_session": selected_session,
        "selected_session_messages": selected_session_messages,
        "selected_session_last_message_id": selected_session_messages[-1].id if selected_session_messages else 0,
        "poll_interval_ms": settings.CHAT_POLL_INTERVAL_MS,
        "realtime_enabled": getattr(settings, "CHAT_REALTIME_ENABLED", True),
        "operator_websocket_url": "/ws/support-chat/operator/",
        "openclaw_enabled": getattr(settings, "OPENCLAW_ENABLED", False),
        "openclaw_auto_reply_enabled": getattr(settings, "OPENCLAW_AUTO_REPLY_ENABLED", True),
        "openclaw_draft_enabled": getattr(settings, "OPENCLAW_DRAFT_ENABLED", True),
        "openclaw_label": getattr(settings, "OPENCLAW_SYSTEM_LABEL", "OpenClaw"),
    }
    return TemplateResponse(request, "admin/support_chat/index.html", context)


@require_GET
def operator_sessions_view(request):
    sessions = [get_session_summary(session) for session in get_session_queryset().order_by("-last_message_at", "-created_at")[:50]]
    return JsonResponse({"sessions": sessions})


@require_GET
def operator_messages_view(request):
    session_id = request.GET.get("session_id")
    if not session_id:
        return _json_error("Invalid 'session_id' parameter.")
    session = get_object_or_404(ChatSession, pk=session_id)
    try:
        after_id = _get_int_query_param(request, "after")
    except ValueError as exc:
        return _json_error(str(exc))
    mark_session_seen(session, viewer="operator")
    return JsonResponse({"messages": get_incremental_messages(session, after_id=after_id, viewer="operator")})


@require_POST
def operator_reply_view(request):
    payload = _parse_json_body(request)
    session = get_object_or_404(ChatSession, pk=payload.get("session_id"))
    if session.status == ChatSession.Status.CLOSED:
        return _json_error("This conversation has ended. Please leave your email and we will follow up.", status=409)
    try:
        message = create_message(
            session=session,
            sender_type=ChatMessage.SenderType.OPERATOR,
            text=payload.get("text", ""),
            sender_user=request.user,
        )
    except ValueError as exc:
        return _json_error(str(exc))
    mark_session_seen(session, viewer="operator")
    return JsonResponse({"message": get_incremental_messages(session, after_id=message.id - 1, viewer="operator")[0]})


@require_POST
def operator_draft_view(request):
    payload = _parse_json_body(request)
    session = get_object_or_404(ChatSession, pk=payload.get("session_id"))
    language = payload.get("language") or session.operator_language
    tone = payload.get("tone") or "neutral"
    try:
        result = generate_openclaw_draft(session, language=language, tone=tone)
    except OpenClawError as exc:
        return _json_error(str(exc), status=503)
    return JsonResponse(
        {
            "draft": result.text,
            "provider": getattr(settings, "OPENCLAW_SYSTEM_LABEL", "OpenClaw"),
            "language": language,
            "tone": tone,
        }
    )


@require_POST
def operator_close_view(request):
    payload = _parse_json_body(request)
    session = get_object_or_404(ChatSession, pk=payload.get("session_id"))
    session.status = ChatSession.Status.CLOSED
    session.save(update_fields=["status", "updated_at"])
    session.refresh_from_db()
    broadcast_session_closed(session)
    return JsonResponse({"ok": True, "session": get_session_summary(session)})
