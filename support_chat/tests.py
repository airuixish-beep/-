from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ChatMessage, ChatSession
from .services import create_message, create_or_resume_session


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
