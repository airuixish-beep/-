from unittest.mock import patch

from asgiref.sync import async_to_sync, sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from config.asgi import application

from .models import ChatMessage, ChatSession
from .services import (
    OpenClawError,
    OpenClawResult,
    create_message,
    create_or_resume_session,
    select_openclaw_tone_for_message,
)


API_ROOT = "/api/lobster/customer-service/"


class SupportChatServiceTests(TestCase):
    def test_create_or_resume_session_updates_existing_session(self):
        session, created = create_or_resume_session(visitor_name="Alice", visitor_language="en")
        self.assertTrue(created)

        resumed, created = create_or_resume_session(token=session.public_token, visitor_name="Alicia", visitor_language="zh-CN")

        self.assertFalse(created)
        self.assertEqual(resumed.id, session.id)
        self.assertEqual(resumed.visitor_name, "Alicia")
        self.assertEqual(resumed.visitor_language, "zh-hans")

    def test_same_language_message_skips_translation(self):
        session = ChatSession.objects.create(visitor_language="zh-hans", operator_language="zh-hans")

        message = create_message(session=session, sender_type=ChatMessage.SenderType.VISITOR, text="你好")

        self.assertEqual(message.translation_status, ChatMessage.TranslationStatus.NOT_NEEDED)
        self.assertEqual(message.body_for_operator, "你好")

    @patch("support_chat.services.translation_service.translate")
    def test_translation_failure_keeps_original_text(self, mock_translate):
        mock_translate.side_effect = RuntimeError("boom")
        session = ChatSession.objects.create(visitor_language="en", operator_language="zh-hans")

        message = create_message(session=session, sender_type=ChatMessage.SenderType.VISITOR, text="Hello")

        self.assertEqual(message.translation_status, ChatMessage.TranslationStatus.FAILED)
        self.assertEqual(message.body_for_operator, "Hello")
        self.assertEqual(message.body_for_visitor, "Hello")

    def test_select_openclaw_tone_for_after_sales_message(self):
        self.assertEqual(select_openclaw_tone_for_message("Where is my order and tracking update?"), "after_sales")

    def test_select_openclaw_tone_for_direct_conversion_message(self):
        self.assertEqual(select_openclaw_tone_for_message("I want to buy today, do you have stock?"), "direct_conversion")

    def test_select_openclaw_tone_for_soft_guide_message(self):
        self.assertEqual(select_openclaw_tone_for_message("Can you recommend a gift for my friend?"), "soft_guide")

    def test_select_openclaw_tone_defaults_to_neutral(self):
        self.assertEqual(select_openclaw_tone_for_message("Thanks for the info."), "neutral")


class SupportChatViewTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_public_session_and_send_flow(self):
        session_response = self.client.post(
            reverse("support_chat_public:session"),
            data='{"visitor_name":"Amy","language":"en"}',
            content_type="application/json",
        )
        self.assertEqual(session_response.status_code, 200)
        self.assertIn("support_chat_token", session_response.cookies)

        send_response = self.client.post(
            reverse("support_chat_public:send"),
            data='{"text":"Hello"}',
            content_type="application/json",
        )
        self.assertEqual(send_response.status_code, 200)
        self.assertContains(send_response, "Hello")

    @override_settings(CHAT_COOKIE_SECURE=True, CHAT_COOKIE_HTTPONLY=True)
    def test_session_cookie_uses_secure_flags(self):
        response = self.client.post(
            reverse("support_chat_public:session"),
            data='{"language":"en"}',
            content_type="application/json",
        )

        cookie = response.cookies["support_chat_token"]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")

    @override_settings(CHAT_RATE_LIMIT_WINDOW_SECONDS=60, CHAT_SESSION_RATE_LIMIT=1)
    def test_session_endpoint_rate_limits(self):
        first = self.client.post(
            reverse("support_chat_public:session"),
            data='{"language":"en"}',
            content_type="application/json",
        )
        second = self.client.post(
            reverse("support_chat_public:session"),
            data='{"language":"en"}',
            content_type="application/json",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Too many chat session requests", second.json()["error"])

    @override_settings(CHAT_RATE_LIMIT_WINDOW_SECONDS=60, CHAT_SEND_RATE_LIMIT=1)
    def test_send_endpoint_rate_limits(self):
        self.client.post(
            reverse("support_chat_public:session"),
            data='{"language":"en"}',
            content_type="application/json",
        )

        first = self.client.post(
            reverse("support_chat_public:send"),
            data='{"text":"Hello"}',
            content_type="application/json",
        )
        second = self.client.post(
            reverse("support_chat_public:send"),
            data='{"text":"Again"}',
            content_type="application/json",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("sending messages too quickly", second.json()["error"])

    @override_settings(CHAT_RATE_LIMIT_WINDOW_SECONDS=60, CHAT_POLL_RATE_LIMIT=1)
    def test_messages_endpoint_rate_limits(self):
        self.client.post(
            reverse("support_chat_public:session"),
            data='{"language":"en"}',
            content_type="application/json",
        )

        first = self.client.get(reverse("support_chat_public:messages"))
        second = self.client.get(reverse("support_chat_public:messages"))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Too many chat refresh requests", second.json()["error"])

    def test_messages_endpoint_rejects_invalid_after(self):
        self.client.post(
            reverse("support_chat_public:session"),
            data='{"language":"en"}',
            content_type="application/json",
        )

        response = self.client.get(reverse("support_chat_public:messages"), {"after": "abc"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Invalid 'after' parameter.")

    def test_closed_session_rejects_public_message(self):
        session = ChatSession.objects.create(status=ChatSession.Status.CLOSED)
        self.client.cookies["support_chat_token"] = session.public_token

        response = self.client.post(
            reverse("support_chat_public:send"),
            data='{"text":"Hello"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("conversation has ended", response.json()["error"])

    def test_empty_message_returns_english_error(self):
        self.client.post(
            reverse("support_chat_public:session"),
            data='{"language":"en"}',
            content_type="application/json",
        )

        response = self.client.post(
            reverse("support_chat_public:send"),
            data='{"text":"   "}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Message text cannot be empty.")

    def test_session_summary_exposes_contact_flags(self):
        response = self.client.post(
            reverse("support_chat_public:session"),
            data='{"visitor_email":"amy@example.com","language":"en"}',
            content_type="application/json",
        )

        payload = response.json()
        self.assertTrue(payload["session"]["has_contact_details"])
        self.assertIn("background_poll_interval_ms", payload)

    @override_settings(OPENCLAW_ENABLED=False)
    def test_first_message_can_send_without_contact_details(self):
        self.client.post(
            reverse("support_chat_public:session"),
            data='{"language":"en"}',
            content_type="application/json",
        )

        response = self.client.post(
            reverse("support_chat_public:send"),
            data='{"text":"Need help with sizing"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ChatMessage.objects.count(), 1)

    @override_settings(OPENCLAW_ENABLED=True, OPENCLAW_AUTO_REPLY_ENABLED=True)
    @patch("support_chat.services.openclaw_service.run")
    def test_openclaw_auto_reply_adds_operator_message(self, mock_run):
        mock_run.return_value = OpenClawResult(text="当然可以，请告诉我你想了解哪款产品。", meta={"provider": "test"})
        self.client.post(
            reverse("support_chat_public:session"),
            data='{"language":"en"}',
            content_type="application/json",
        )

        response = self.client.post(
            reverse("support_chat_public:send"),
            data='{"text":"Can you help me?"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ChatMessage.objects.count(), 2)
        self.assertIn("auto_reply", response.json())
        self.assertEqual(ChatMessage.objects.order_by("id").last().sender_type, ChatMessage.SenderType.OPERATOR)

    @override_settings(OPENCLAW_ENABLED=True, OPENCLAW_AUTO_REPLY_ENABLED=True)
    @patch("support_chat.services.openclaw_service.run")
    def test_openclaw_auto_reply_uses_detected_after_sales_tone(self, mock_run):
        mock_run.return_value = OpenClawResult(text="We can help with your order.", meta={"provider": "test"})
        self.client.post(
            reverse("support_chat_public:session"),
            data='{"language":"en"}',
            content_type="application/json",
        )

        response = self.client.post(
            reverse("support_chat_public:send"),
            data='{"text":"My order has not arrived yet."}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        _, kwargs = mock_run.call_args
        self.assertIn("Tone code: after_sales", kwargs["prompt"])
        self.assertIn("Target language: en", kwargs["prompt"])

    @override_settings(OPENCLAW_ENABLED=True, OPENCLAW_AUTO_REPLY_ENABLED=True)
    @patch("support_chat.services.openclaw_service.run")
    def test_openclaw_failure_keeps_original_message(self, mock_run):
        mock_run.side_effect = OpenClawError("boom")
        self.client.post(
            reverse("support_chat_public:session"),
            data='{"language":"en"}',
            content_type="application/json",
        )

        response = self.client.post(
            reverse("support_chat_public:send"),
            data='{"text":"Can you help me?"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ChatMessage.objects.count(), 1)
        self.assertNotIn("auto_reply", response.json())

    def test_operator_console_requires_staff(self):
        response = self.client.get("/admin/support-chat/")
        self.assertEqual(response.status_code, 302)

    def test_staff_can_reply(self):
        user = get_user_model().objects.create_user(username="agent", password="pass", is_staff=True, is_superuser=True)
        session = ChatSession.objects.create(visitor_language="en", operator_language="zh-hans")
        self.client.force_login(user)

        response = self.client.post(
            "/admin/support-chat/reply/",
            data='{"session_id": %d, "text": "你好"}' % session.id,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.messages.count(), 1)
        self.assertEqual(response.json()["message"]["text"], "你好")

    def test_operator_sessions_summary_includes_last_message_preview(self):
        user = get_user_model().objects.create_user(username="admin", password="pass", is_staff=True, is_superuser=True)
        session = ChatSession.objects.create(visitor_language="en", operator_language="zh-hans")
        create_message(session=session, sender_type=ChatMessage.SenderType.VISITOR, text="Hello there")
        self.client.force_login(user)

        response = self.client.get("/admin/support-chat/sessions/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()["sessions"]
        self.assertEqual(payload[0]["id"], session.id)
        self.assertTrue(payload[0]["last_message_preview"])
        self.assertEqual(payload[0]["unread_for_operator"], 1)

    @override_settings(OPENCLAW_ENABLED=True, OPENCLAW_DRAFT_ENABLED=True)
    @patch("support_chat.services.openclaw_service.run")
    def test_staff_can_generate_draft(self, mock_run):
        mock_run.return_value = OpenClawResult(text="您好，我们建议您先告诉我订单号。", meta={"provider": "test"})
        user = get_user_model().objects.create_user(username="draft", password="pass", is_staff=True, is_superuser=True)
        session = ChatSession.objects.create(visitor_language="en", operator_language="zh-hans")
        self.client.force_login(user)

        response = self.client.post(
            "/admin/support-chat/draft/",
            data='{"session_id": %d, "language": "zh-hans", "tone": "after_sales"}' % session.id,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["draft"], "您好，我们建议您先告诉我订单号。")
        self.assertEqual(response.json()["language"], "zh-hans")
        self.assertEqual(response.json()["tone"], "after_sales")
        _, kwargs = mock_run.call_args
        self.assertIn("Tone code: after_sales", kwargs["prompt"])
        self.assertIn("Target language: zh-hans", kwargs["prompt"])

    @override_settings(OPENCLAW_ENABLED=True, OPENCLAW_DRAFT_ENABLED=True)
    @patch("support_chat.services.openclaw_service.run")
    def test_staff_can_generate_english_soft_guide_draft(self, mock_run):
        mock_run.return_value = OpenClawResult(text="I can help you choose a thoughtful gift.", meta={"provider": "test"})
        user = get_user_model().objects.create_user(username="draft_en", password="pass", is_staff=True, is_superuser=True)
        session = ChatSession.objects.create(visitor_language="en", operator_language="zh-hans")
        self.client.force_login(user)

        response = self.client.post(
            "/admin/support-chat/draft/",
            data='{"session_id": %d, "language": "en", "tone": "soft_guide"}' % session.id,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["language"], "en")
        self.assertEqual(response.json()["tone"], "soft_guide")
        _, kwargs = mock_run.call_args
        self.assertIn("Tone code: soft_guide", kwargs["prompt"])
        self.assertIn("Target language: en", kwargs["prompt"])

    @override_settings(OPENCLAW_ENABLED=True, OPENCLAW_DRAFT_ENABLED=True)
    @patch("support_chat.services.openclaw_service.run")
    def test_staff_draft_returns_service_error(self, mock_run):
        mock_run.side_effect = OpenClawError("service unavailable")
        user = get_user_model().objects.create_user(username="draft2", password="pass", is_staff=True, is_superuser=True)
        session = ChatSession.objects.create(visitor_language="en", operator_language="zh-hans")
        self.client.force_login(user)

        response = self.client.post(
            "/admin/support-chat/draft/",
            data='{"session_id": %d}' % session.id,
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "service unavailable")

    def test_operator_messages_rejects_invalid_after(self):
        user = get_user_model().objects.create_user(username="ops", password="pass", is_staff=True, is_superuser=True)
        session = ChatSession.objects.create(visitor_language="en", operator_language="zh-hans")
        self.client.force_login(user)

        response = self.client.get("/admin/support-chat/messages/", {"session_id": session.id, "after": "abc"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Invalid 'after' parameter.")

    def test_operator_messages_requires_session_id(self):
        user = get_user_model().objects.create_user(username="support", password="pass", is_staff=True, is_superuser=True)
        self.client.force_login(user)

        response = self.client.get("/admin/support-chat/messages/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Invalid 'session_id' parameter.")


class SupportChatRealtimeTests(TestCase):
    @override_settings(CHANNEL_LAYER_BACKEND="memory", CHAT_REALTIME_ENABLED=True)
    def test_visitor_websocket_connects_with_valid_token(self):
        async def scenario():
            session = await sync_to_async(ChatSession.objects.create)(visitor_language="en", operator_language="zh-hans")
            communicator = WebsocketCommunicator(application, f"/ws/support-chat/visitor/{session.public_token}/")
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            payload = await communicator.receive_json_from()
            self.assertEqual(payload["event"], "chat.connected")
            self.assertEqual(payload["role"], "visitor")
            await communicator.disconnect()

        async_to_sync(scenario)()

    @override_settings(CHANNEL_LAYER_BACKEND="memory", CHAT_REALTIME_ENABLED=True)
    def test_visitor_websocket_rejects_invalid_token(self):
        async def scenario():
            communicator = WebsocketCommunicator(application, "/ws/support-chat/visitor/invalid-token/")
            connected, _ = await communicator.connect()
            self.assertFalse(connected)

        async_to_sync(scenario)()


class SupportChatApiViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client(enforce_csrf_checks=True)

    def _prime_csrf(self):
        response = self.client.get(reverse("pages:chat"))
        return response.cookies["csrftoken"].value

    def test_api_create_and_resume_session_flow(self):
        csrf_token = self._prime_csrf()
        create_response = self.client.post(
            f"{API_ROOT}sessions",
            data='{"visitor_name":"Amy","visitor_email":"amy@example.com","language":"en-US"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(create_response.status_code, 200)
        create_payload = create_response.json()
        self.assertTrue(create_payload["created"])
        self.assertEqual(create_payload["session"]["visitor_language"], "en")
        public_token = create_payload["session"]["public_token"]

        resume_response = self.client.post(
            f"{API_ROOT}sessions",
            data='{"public_token":"%s","visitor_name":"Alicia","language":"zh-CN"}' % public_token,
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(resume_response.status_code, 200)
        resume_payload = resume_response.json()
        self.assertFalse(resume_payload["created"])
        self.assertEqual(resume_payload["session"]["public_token"], public_token)
        self.assertEqual(resume_payload["session"]["visitor_name"], "Alicia")
        self.assertEqual(resume_payload["session"]["visitor_language"], "zh-hans")

    def test_api_session_detail_and_messages_flow(self):
        session = ChatSession.objects.create(visitor_language="en", operator_language="zh-hans")
        create_message(session=session, sender_type=ChatMessage.SenderType.VISITOR, text="Hello")
        create_message(session=session, sender_type=ChatMessage.SenderType.OPERATOR, text="你好")

        detail_response = self.client.get(f"{API_ROOT}sessions/{session.public_token}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["session"]["public_token"], session.public_token)

        messages_response = self.client.get(f"{API_ROOT}sessions/{session.public_token}/messages", {"after": 0})
        self.assertEqual(messages_response.status_code, 200)
        messages = messages_response.json()["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["sender_type"], "visitor")

    def test_api_send_message_and_mark_read(self):
        csrf_token = self._prime_csrf()
        session = ChatSession.objects.create(visitor_language="en", operator_language="zh-hans")

        send_response = self.client.post(
            f"{API_ROOT}sessions/{session.public_token}/messages/send",
            data='{"text":"Need help"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(send_response.status_code, 200)
        self.assertEqual(send_response.json()["message"]["text"], "Need help")
        session.refresh_from_db()
        self.assertEqual(session.status, ChatSession.Status.WAITING_OPERATOR)

        read_response = self.client.post(
            f"{API_ROOT}sessions/{session.public_token}/read",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(read_response.status_code, 200)
        self.assertTrue(read_response.json()["ok"])
        session.refresh_from_db()
        self.assertIsNotNone(session.last_seen_by_visitor_at)

    def test_api_send_persists_contact_updates(self):
        csrf_token = self._prime_csrf()
        session = ChatSession.objects.create(visitor_language="en", operator_language="zh-hans")

        response = self.client.post(
            f"{API_ROOT}sessions/{session.public_token}/messages/send",
            data='{"text":"Need help","visitor_name":"Amy","visitor_email":"amy@example.com"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )

        self.assertEqual(response.status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.visitor_name, "Amy")
        self.assertEqual(session.visitor_email, "amy@example.com")
        self.assertTrue(response.json()["session"]["has_contact_details"])

    def test_api_post_endpoints_require_csrf(self):
        session = ChatSession.objects.create(visitor_language="en", operator_language="zh-hans")

        response = self.client.post(
            f"{API_ROOT}sessions/{session.public_token}/messages/send",
            data='{"text":"Need help"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)

    def test_api_rejects_invalid_after_and_closed_session(self):
        session = ChatSession.objects.create(status=ChatSession.Status.CLOSED)
        csrf_token = self._prime_csrf()

        invalid_after_response = self.client.get(f"{API_ROOT}sessions/{session.public_token}/messages", {"after": "abc"})
        self.assertEqual(invalid_after_response.status_code, 400)
        self.assertEqual(invalid_after_response.json()["error"], "Invalid 'after' parameter.")

        closed_response = self.client.post(
            f"{API_ROOT}sessions/{session.public_token}/messages/send",
            data='{"text":"Hello"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(closed_response.status_code, 409)
        self.assertIn("conversation has ended", closed_response.json()["error"])

    def test_api_rate_limits_session_endpoint(self):
        csrf_token = self._prime_csrf()
        with override_settings(CHAT_RATE_LIMIT_WINDOW_SECONDS=60, CHAT_SESSION_RATE_LIMIT=1):
            first = self.client.post(
                f"{API_ROOT}sessions",
                data='{"language":"en"}',
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf_token,
            )
            second = self.client.post(
                f"{API_ROOT}sessions",
                data='{"language":"en"}',
                content_type="application/json",
                HTTP_X_CSRFTOKEN=csrf_token,
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Too many chat session requests", second.json()["error"])

    def test_admin_api_requires_staff(self):
        response = self.client.get(f"{API_ROOT}admin/sessions")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Forbidden")

    def test_staff_admin_api_list_reply_messages_and_close(self):
        user = get_user_model().objects.create_user(username="staff", password="pass", is_staff=True, is_superuser=True)
        session = ChatSession.objects.create(visitor_language="en", operator_language="zh-hans", visitor_name="Amy")
        create_message(session=session, sender_type=ChatMessage.SenderType.VISITOR, text="Hello there")
        self.client.force_login(user)
        csrf_token = self._prime_csrf()

        list_response = self.client.get(f"{API_ROOT}admin/sessions", {"status": session.status, "visitor_name": "Amy", "limit": 5})
        self.assertEqual(list_response.status_code, 200)
        sessions = list_response.json()["sessions"]
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], session.id)

        messages_response = self.client.get(f"{API_ROOT}admin/sessions/{session.id}/messages", {"after": 0})
        self.assertEqual(messages_response.status_code, 200)
        self.assertEqual(len(messages_response.json()["messages"]), 1)

        reply_response = self.client.post(
            f"{API_ROOT}admin/sessions/{session.id}/messages/send",
            data='{"text":"你好"}',
            content_type="application/json",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(reply_response.status_code, 200)
        self.assertEqual(reply_response.json()["message"]["text"], "你好")

        close_response = self.client.post(
            f"{API_ROOT}admin/sessions/{session.id}/close",
            HTTP_X_CSRFTOKEN=csrf_token,
        )
        self.assertEqual(close_response.status_code, 200)
        self.assertTrue(close_response.json()["ok"])
        session.refresh_from_db()
        self.assertEqual(session.status, ChatSession.Status.CLOSED)

    def test_staff_admin_api_rejects_invalid_limit(self):
        user = get_user_model().objects.create_user(username="staff2", password="pass", is_staff=True, is_superuser=True)
        self.client.force_login(user)

        response = self.client.get(f"{API_ROOT}admin/sessions", {"limit": "abc"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Invalid 'limit' parameter.")
