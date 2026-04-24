import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.conf import settings

from .models import ChatSession
from .realtime import admin_group_name, session_group_name
from .services import get_session_summary, mark_session_seen


class BaseChatConsumer(AsyncWebsocketConsumer):
    async def chat_event(self, event):
        await self.send(text_data=json.dumps(event["payload"]))

    async def send_payload(self, payload):
        await self.send(text_data=json.dumps(payload))


class VisitorChatConsumer(BaseChatConsumer):
    async def connect(self):
        if not getattr(settings, "CHAT_REALTIME_ENABLED", True):
            await self.close()
            return
        self.session = await self.get_session_by_token(self.scope["url_route"]["kwargs"].get("public_token"))
        if self.session is None:
            await self.close()
            return
        self.session_group = session_group_name(self.session["id"])
        await self.channel_layer.group_add(self.session_group, self.channel_name)
        await self.accept()
        await self.send_payload({"event": "chat.connected", "role": "visitor", "session": self.session})

    async def disconnect(self, close_code):
        if hasattr(self, "session_group"):
            await self.channel_layer.group_discard(self.session_group, self.channel_name)

    async def receive(self, text_data):
        try:
            payload = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            return
        event = payload.get("event")
        if event == "chat.mark_read":
            await self.mark_read(self.session["id"], "visitor")
        elif event == "ping":
            await self.send_payload({"event": "pong"})

    @database_sync_to_async
    def get_session_by_token(self, public_token):
        session = ChatSession.objects.filter(public_token=public_token).first()
        if session is None:
            return None
        return get_session_summary(session)

    @database_sync_to_async
    def get_session_by_id(self, session_id):
        session = ChatSession.objects.get(pk=session_id)
        return get_session_summary(session)

    @database_sync_to_async
    def mark_read(self, session_id, viewer):
        session = ChatSession.objects.get(pk=session_id)
        return mark_session_seen(session, viewer=viewer)


class OperatorChatConsumer(BaseChatConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not getattr(settings, "CHAT_REALTIME_ENABLED", True) or user is None or not user.is_authenticated or not user.is_staff:
            await self.close()
            return
        self.user = user
        self.current_session_group = None
        await self.channel_layer.group_add(admin_group_name(), self.channel_name)
        await self.accept()
        await self.send_payload({"event": "chat.connected", "role": "operator"})

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(admin_group_name(), self.channel_name)
        if self.current_session_group:
            await self.channel_layer.group_discard(self.current_session_group, self.channel_name)

    async def receive(self, text_data):
        try:
            payload = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            return
        event = payload.get("event")
        if event == "chat.subscribe":
            await self.subscribe_session(payload.get("session_id"))
        elif event == "chat.mark_read":
            session_id = payload.get("session_id")
            if session_id:
                await self.mark_read(session_id, "operator")
        elif event == "ping":
            await self.send_payload({"event": "pong"})

    async def subscribe_session(self, session_id):
        if self.current_session_group:
            await self.channel_layer.group_discard(self.current_session_group, self.channel_name)
            self.current_session_group = None
        if not session_id:
            return
        session_exists = await self.session_exists(session_id)
        if not session_exists:
            return
        self.current_session_group = session_group_name(session_id)
        await self.channel_layer.group_add(self.current_session_group, self.channel_name)
        session = await self.get_session_by_id(session_id)
        await self.send_payload({"event": "chat.session.updated", "session": session})

    @database_sync_to_async
    def session_exists(self, session_id):
        return ChatSession.objects.filter(pk=session_id).exists()

    @database_sync_to_async
    def get_session_by_id(self, session_id):
        session = ChatSession.objects.get(pk=session_id)
        return get_session_summary(session)

    @database_sync_to_async
    def mark_read(self, session_id, viewer):
        session = ChatSession.objects.get(pk=session_id)
        return mark_session_seen(session, viewer=viewer)
