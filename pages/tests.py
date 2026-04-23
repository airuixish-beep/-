from django.test import TestCase, override_settings
from django.urls import reverse


class ChatPageViewTests(TestCase):
    @override_settings(CHAT_WIDGET_ENABLED=True)
    def test_chat_page_renders_standalone_chat_without_floating_widget(self):
        response = self.client.get(reverse("pages:chat"))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/chat.html")
        self.assertContains(response, 'id="support-chat-page"')
        self.assertContains(response, 'data-role="initial-message"')
        self.assertContains(response, "js/support_chat_shared.js")
        self.assertContains(response, "js/support_chat_page.js")
        self.assertNotContains(response, 'id="support-chat-widget"')
