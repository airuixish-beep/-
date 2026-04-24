from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from .models import ChatMessage, ChatOfflineMessage, ChatSession
from .realtime import broadcast_session_closed
from .services import (
    create_message,
    create_or_resume_session,
    get_incremental_messages,
    get_session_queryset,
    get_session_summary,
    mark_session_seen,
)
from .views import _create_offline_message, _get_int_query_param, _is_rate_limited, _json_error, _parse_json_body


@require_POST
def api_session_create_view(request):
    if _is_rate_limited(request, "session", getattr(settings, "CHAT_SESSION_RATE_LIMIT", 20)):
        return _json_error("Too many chat session requests. Please try again in a minute.", status=429)

    payload = _parse_json_body(request)
    session, created = create_or_resume_session(
        token=(payload.get("public_token") or "").strip(),
        visitor_name=(payload.get("visitor_name") or "").strip(),
        visitor_email=(payload.get("visitor_email") or "").strip(),
        related_order_no=(payload.get("related_order_no") or "").strip(),
        visitor_language=payload.get("language") or "en",
    )
    messages = get_incremental_messages(session, after_id=0, viewer="visitor")
    return JsonResponse(
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


@require_GET
def api_session_detail_view(request, public_token):
    session = get_object_or_404(ChatSession, public_token=public_token)
    return JsonResponse({"session": get_session_summary(session)})


@require_GET
def api_session_messages_view(request, public_token):
    if _is_rate_limited(request, "poll", getattr(settings, "CHAT_POLL_RATE_LIMIT", 240)):
        return _json_error("Too many chat refresh requests. Please try again shortly.", status=429)

    session = get_object_or_404(ChatSession, public_token=public_token)
    try:
        after_id = _get_int_query_param(request, "after")
    except ValueError as exc:
        return _json_error(str(exc))

    return JsonResponse(
        {
            "messages": get_incremental_messages(session, after_id=after_id, viewer="visitor"),
            "session": get_session_summary(session),
        }
    )


@require_POST
def api_session_send_view(request, public_token):
    if _is_rate_limited(request, "send", getattr(settings, "CHAT_SEND_RATE_LIMIT", 60)):
        return _json_error("You are sending messages too quickly. Please wait a moment and try again.", status=429)

    session = get_object_or_404(ChatSession, public_token=public_token)
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

    return JsonResponse(
        {
            "message": get_incremental_messages(session, after_id=message.id - 1, viewer="visitor")[0],
            "session": get_session_summary(session),
        }
    )


@require_POST
def api_session_read_view(request, public_token):
    session = get_object_or_404(ChatSession, public_token=public_token)
    mark_session_seen(session, viewer="visitor")
    return JsonResponse({"ok": True})


@require_POST
def api_offline_message_view(request):
    payload = _parse_json_body(request)
    try:
        offline_message = _create_offline_message(payload)
    except ValueError as exc:
        return _json_error(str(exc))
    return JsonResponse({"ok": True, "offline_message_id": offline_message.id})


@user_passes_test(lambda user: user.is_authenticated and user.is_staff)
def _staff_required_view(_request):
    return None


@require_GET
def api_admin_sessions_view(request):
    guard = _staff_required_view(request)
    if guard is not None:
        return JsonResponse({"error": "Forbidden"}, status=403)

    queryset = get_session_queryset().order_by("-last_message_at", "-created_at")
    status_value = (request.GET.get("status") or "").strip()
    visitor_email = (request.GET.get("visitor_email") or "").strip()
    visitor_name = (request.GET.get("visitor_name") or "").strip()
    limit_raw = (request.GET.get("limit") or "50").strip()

    if status_value:
        queryset = queryset.filter(status=status_value)
    if visitor_email:
        queryset = queryset.filter(visitor_email__icontains=visitor_email)
    if visitor_name:
        queryset = queryset.filter(visitor_name__icontains=visitor_name)

    try:
        limit = int(limit_raw)
    except ValueError:
        return _json_error("Invalid 'limit' parameter.")
    if limit < 1:
        return _json_error("Invalid 'limit' parameter.")

    sessions = [get_session_summary(session) for session in queryset[: min(limit, 100)]]
    return JsonResponse({"sessions": sessions})


@require_GET
def api_admin_session_messages_view(request, session_id):
    guard = _staff_required_view(request)
    if guard is not None:
        return JsonResponse({"error": "Forbidden"}, status=403)

    session = get_object_or_404(ChatSession, pk=session_id)
    try:
        after_id = _get_int_query_param(request, "after")
    except ValueError as exc:
        return _json_error(str(exc))

    mark_session_seen(session, viewer="operator")
    return JsonResponse({"messages": get_incremental_messages(session, after_id=after_id, viewer="operator")})


@require_POST
def api_admin_session_reply_view(request, session_id):
    guard = _staff_required_view(request)
    if guard is not None:
        return JsonResponse({"error": "Forbidden"}, status=403)

    session = get_object_or_404(ChatSession, pk=session_id)
    if session.status == ChatSession.Status.CLOSED:
        return _json_error("This conversation has ended. Please leave your email and we will follow up.", status=409)

    payload = _parse_json_body(request)
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
def api_admin_session_close_view(request, session_id):
    guard = _staff_required_view(request)
    if guard is not None:
        return JsonResponse({"error": "Forbidden"}, status=403)

    session = get_object_or_404(ChatSession, pk=session_id)
    session.status = ChatSession.Status.CLOSED
    session.save(update_fields=["status", "updated_at"])
    session.refresh_from_db()
    broadcast_session_closed(session)
    return JsonResponse({"ok": True, "session": get_session_summary(session)})
