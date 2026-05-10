from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


class HealthCheckViewTests(TestCase):
    def test_health_live_returns_ok(self):
        response = self.client.get(reverse("health_live"))

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"ok": True, "service": "live"})

    def test_health_ready_returns_ok_when_realtime_disabled(self):
        response = self.client.get(reverse("health_ready"))

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "ok": True,
                "service": "ready",
                "checks": {"database": "ok", "cache": "ok", "realtime": "disabled"},
            },
        )

    @override_settings(
        CHAT_REALTIME_ENABLED=True,
        CHANNEL_LAYER_BACKEND="memory",
        CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}},
    )
    def test_health_ready_checks_realtime_when_enabled(self):
        response = self.client.get(reverse("health_ready"))

        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(
            response.content,
            {
                "ok": True,
                "service": "ready",
                "checks": {"database": "ok", "cache": "ok", "realtime": "ok"},
            },
        )


class ContentOSAccessTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="content-staff",
            email="content-staff@example.com",
            password="password123",
            is_staff=True,
        )
        self.regular_user = user_model.objects.create_user(
            username="content-regular",
            email="content-regular@example.com",
            password="password123",
        )

    def test_staff_user_can_access_content_os(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("content_os"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "内容中枢")
        self.assertContains(response, "内容生产（AI / 人工）")
        self.assertContains(response, "素材资产库（DAM）")
        self.assertContains(response, "页面管理（CMS）")
        self.assertContains(response, "渠道分发（广告 / 社媒）")
        self.assertContains(response, "数据分析（CTR / ROI）")
        self.assertContains(response, "爆款资产沉淀（复用系统）")
        self.assertContains(response, "当前接入观察")
        self.assertContains(response, "下一阶段待接入")

    def test_admin_index_links_to_content_os(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("content_os"))
        self.assertContains(response, "内容中枢")

    def test_anonymous_user_is_redirected_to_login(self):
        response = self.client.get(reverse("content_os"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_non_staff_user_is_redirected_to_login(self):
        self.client.force_login(self.regular_user)

        response = self.client.get(reverse("content_os"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])
