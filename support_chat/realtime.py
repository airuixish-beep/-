from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings


def _get_session_summary(session):
    from .services import get_session_summary

    return get_session_summary(session)


def session_group_name(session_id):
    return f"support_chat_session_{session_id}"


def admin_group_name():
    return "support_chat_admin_sessions"


def serialize_realtime_message(message):
    return {
        "id": message.id,
        "session_id": message.session_id,
        "sender_type": message.sender_type,
        "text_for_visitor": message.display_for_visitor,
        "text_for_operator": message.display_for_operator,
        "original_text": message.body_original,
        "original_language": message.original_language,
        "translation_status": message.translation_status,
        "created_at": message.created_at.isoformat(),
        "translation_meta": message.translation_meta or {},
    }


def _group_send(group_name, payload):
    if not getattr(settings, "CHAT_REALTIME_ENABLED", True):
        return
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "chat.event",
                "payload": payload,
            },
        )
    except Exception:
        return


def broadcast_message_created(session, message):
    payload = {
        "event": "chat.message.created",
        "session": _get_session_summary(session),
        "message": serialize_realtime_message(message),
    }
    _group_send(session_group_name(session.id), payload)
    _group_send(
        admin_group_name(),
        {
            "event": "chat.session.list.changed",
            "session": _get_session_summary(session),
            "message": serialize_realtime_message(message),
        },
    )


def broadcast_session_read(session, viewer):
    payload = {
        "event": "chat.session.read",
        "viewer": viewer,
        "session": _get_session_summary(session),
    }
    _group_send(session_group_name(session.id), payload)
    _group_send(
        admin_group_name(),
        {
            "event": "chat.session.list.changed",
            "session": _get_session_summary(session),
            "viewer": viewer,
        },
    )


def broadcast_session_closed(session):
    payload = {
        "event": "chat.session.closed",
        "session": _get_session_summary(session),
    }
    _group_send(session_group_name(session.id), payload)
    _group_send(
        admin_group_name(),
        {
            "event": "chat.session.list.changed",
            "session": _get_session_summary(session),
        },
    )


def broadcast_session_snapshot(session):
    payload = {
        "event": "chat.session.updated",
        "session": _get_session_summary(session),
    }
    _group_send(session_group_name(session.id), payload)
    _group_send(
        admin_group_name(),
        {
            "event": "chat.session.list.changed",
            "session": _get_session_summary(session),
        },
    )
