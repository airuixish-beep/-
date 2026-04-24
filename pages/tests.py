from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import SiteConfig


class PublicPageViewTests(TestCase):
    def test_public_information_pages_render(self):
        cases = [
            ("pages:contact", "pages/contact.html"),
            ("pages:refund_policy", "pages/refund_policy.html"),
            ("pages:shipping_policy", "pages/shipping_policy.html"),
            ("pages:privacy_policy", "pages/privacy_policy.html"),
            ("pages:terms_of_service", "pages/terms_of_service.html"),
        ]

        for route_name, template_name in cases:
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, template_name)

    def test_contact_page_shows_site_config_contact_details(self):
        SiteConfig.objects.create(
            contact_email="hello@xuanor.com",
            contact_phone="123-456-7890",
            address="Shanghai",
        )

        response = self.client.get(reverse("pages:contact"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "hello@xuanor.com")
        self.assertContains(response, "123-456-7890")
        self.assertContains(response, "Shanghai")

    def test_footer_contains_public_information_links(self):
        response = self.client.get(reverse("pages:about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("pages:contact"))
        self.assertContains(response, reverse("pages:refund_policy"))
        self.assertContains(response, reverse("pages:shipping_policy"))
        self.assertContains(response, reverse("pages:privacy_policy"))
        self.assertContains(response, reverse("pages:terms_of_service"))


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
        self.assertContains(response, 'name="related_order_no"')
        self.assertNotContains(response, 'id="support-chat-widget"')

    def test_chat_page_prefills_contact_context_from_querystring(self):
        response = self.client.get(reverse("pages:chat"), {"name": "Amy", "email": "amy@example.com", "order_no": "XO123"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'value="Amy"')
        self.assertContains(response, 'value="amy@example.com"')
        self.assertContains(response, 'value="XO123"')
