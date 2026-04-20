import json

from django.conf import settings
from django.contrib import admin
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import ChatMessage, ChatSession
from .services import (
    create_message,
    create_or_resume_session,
    get_incremental_messages,
    get_preferred_visitor_language,
    get_session_summary,
    mark_session_seen,
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
        raise Http404("会话不存在")
    return get_object_or_404(ChatSession, public_token=token)


def _json_error(message, *, status=400):
    return JsonResponse({"error": message}, status=status)


@ensure_csrf_cookie
@require_POST
def session_view(request):
    payload = _parse_json_body(request)
    token = request.COOKIES.get(SESSION_COOKIE_NAME)
    visitor_language = payload.get("language") or get_preferred_visitor_language(request)
    session, created = create_or_resume_session(
        token=token,
        visitor_name=(payload.get("visitor_name") or "").strip(),
        visitor_email=(payload.get("visitor_email") or "").strip(),
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
        }
    )
    response.set_cookie(SESSION_COOKIE_NAME, session.public_token, max_age=60 * 60 * 24 * 30, samesite="Lax")
    return response


@require_GET
def messages_view(request):
    session = _get_public_session(request)
    after_id = int(request.GET.get("after", 0) or 0)
    messages = get_incremental_messages(session, after_id=after_id, viewer="visitor")
    return JsonResponse({"messages": messages, "session": get_session_summary(session)})


@require_POST
def mark_read_view(request):
    session = _get_public_session(request)
    mark_session_seen(session, viewer="visitor")
    return JsonResponse({"ok": True})


@require_POST
def visitor_send_view(request):
    session = _get_public_session(request)
    if session.status == ChatSession.Status.CLOSED:
        return _json_error("This conversation has ended. Please leave your email and we will follow up.", status=409)
    payload = _parse_json_body(request)
    try:
        message = create_message(session=session, sender_type=ChatMessage.SenderType.VISITOR, text=payload.get("text", ""))
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse({"message": get_incremental_messages(session, after_id=message.id - 1, viewer="visitor")[0]})


@require_GET
def operator_console_view(request):
    sessions = ChatSession.objects.prefetch_related("messages")[:20]
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
    }
    return TemplateResponse(request, "admin/support_chat/index.html", context)


@require_GET
def operator_sessions_view(request):
    sessions = [get_session_summary(session) for session in ChatSession.objects.order_by("-last_message_at", "-created_at")[:50]]
    return JsonResponse({"sessions": sessions})


@require_GET
def operator_messages_view(request):
    session = get_object_or_404(ChatSession, pk=request.GET.get("session_id"))
    after_id = int(request.GET.get("after", 0) or 0)
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
def operator_close_view(request):
    payload = _parse_json_body(request)
    session = get_object_or_404(ChatSession, pk=payload.get("session_id"))
    session.status = ChatSession.Status.CLOSED
    session.save(update_fields=["status", "updated_at"])
    return JsonResponse({"ok": True, "session": get_session_summary(session)})
