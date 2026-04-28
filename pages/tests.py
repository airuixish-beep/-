from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.models import SiteConfig
from products.models import Category, Product

from .admin import FiveElementSubmissionAdmin
from .models import (
    FiveElementOption,
    FiveElementOptionScore,
    FiveElementProfile,
    FiveElementProfileProduct,
    FiveElementQuestion,
    FiveElementQuiz,
    FiveElementSubmission,
)
from .services import build_result_summary, evaluate_five_element_result, get_profile_recommendations


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


class FiveElementQuizTestCase(TestCase):
    def setUp(self):
        self.quiz = FiveElementQuiz.objects.create(
            name="五行情绪测试",
            slug="five-elements",
            title="测试你的五行人格与当下仪式路径",
            subtitle="先理解你的情绪，再推荐适合你的仪式物。",
            intro_title="不是判断你是谁，而是看见你此刻需要什么。",
            intro_body="围绕当下情绪、节奏与恢复方式，找到更适合你的五行路径。",
            estimated_minutes=5,
            is_active=True,
        )
        self.wood = FiveElementProfile.objects.create(
            quiz=self.quiz,
            code=FiveElementProfile.ElementCode.WOOD,
            name="木",
            theme_word="生长",
            emotion_title="你现在需要重新开始生长。",
            emotion_body="你不是缺少努力，而是需要一个允许自己慢慢展开的环境。",
            result_title="你的主导五行是木",
            short_description="把重新开始的意愿带回日常。",
            long_description="木不是更快向前，而是在混乱中恢复生成感。",
            primary_symbol_title="绿幽灵吊坠 / 项链",
            primary_symbol_description="像枝叶与雾气被封存在晶体里，提醒你可以继续展开。",
            ritual_object_title="书写本 / Journal",
            ritual_object_description="让模糊感受被记录，被看见，被慢慢整理。",
            ambient_object_title="扩香木 / 木系精油",
            ambient_object_description="把生长从佩戴延伸到呼吸与空间。",
            sort_order=1,
        )
        self.fire = FiveElementProfile.objects.create(
            quiz=self.quiz,
            code=FiveElementProfile.ElementCode.FIRE,
            name="火",
            theme_word="回温",
            emotion_title="你现在需要把热度慢慢找回来。",
            emotion_body="不是再被点燃一次，而是让身体与心重新有温度。",
            result_title="你的主导五行是火",
            short_description="把生命热度带回身体。",
            long_description="火不是过度燃烧，而是恢复循环与温度。",
            primary_symbol_title="石榴石吊坠 / 项链",
            primary_symbol_description="把成熟、热度与生命力重新召回。",
            ritual_object_title="肉桂精油",
            ritual_object_description="让火从抽象感觉变成身体可感知的温度。",
            ambient_object_title="扩香木 / 香气仪式物",
            ambient_object_description="把温度从个体延伸到空间。",
            sort_order=2,
        )
        self.water = FiveElementProfile.objects.create(
            quiz=self.quiz,
            code=FiveElementProfile.ElementCode.WATER,
            name="水",
            theme_word="深度",
            emotion_title="你现在需要退回内在深处。",
            emotion_body="不是逃开，而是想听见自己。",
            result_title="你的主导五行是水",
            short_description="把自己带回深处。",
            long_description="水不是逃离，而是重新回到内在深处。",
            primary_symbol_title="青金石吊坠 / 项链",
            primary_symbol_description="像夜海与洞察。",
            ritual_object_title="行动日志本",
            ritual_object_description="让洞察显形。",
            ambient_object_title="小号颂钵",
            ambient_object_description="让深度先被听见。",
            sort_order=3,
        )
        self.question_1 = FiveElementQuestion.objects.create(
            quiz=self.quiz,
            prompt="当你感到卡住时，你最想做的第一件事是什么？",
            help_text="请选择此刻最接近你的选项。",
            sort_order=1,
        )
        self.question_2 = FiveElementQuestion.objects.create(
            quiz=self.quiz,
            prompt="最近你更需要哪一种支持？",
            sort_order=2,
        )
        self.question_3 = FiveElementQuestion.objects.create(
            quiz=self.quiz,
            prompt="最近你最想重新找回哪种状态？",
            sort_order=3,
        )
        self.wood_option_1 = FiveElementOption.objects.create(question=self.question_1, label="先写下来，让混乱慢慢长出方向。", sort_order=1)
        self.fire_option_1 = FiveElementOption.objects.create(question=self.question_1, label="先让自己暖起来，再重新进入状态。", sort_order=2)
        self.wood_option_2 = FiveElementOption.objects.create(question=self.question_2, label="一个允许我慢慢展开的空间。", sort_order=1)
        self.fire_option_2 = FiveElementOption.objects.create(question=self.question_2, label="一种能让我回温的陪伴。", sort_order=2)
        self.water_option_3 = FiveElementOption.objects.create(question=self.question_3, label="一个能让我回到深处的安静节奏。", sort_order=1)
        FiveElementOptionScore.objects.create(option=self.wood_option_1, profile=self.wood, score=2)
        FiveElementOptionScore.objects.create(option=self.wood_option_1, profile=self.fire, score=1)
        FiveElementOptionScore.objects.create(option=self.fire_option_1, profile=self.fire, score=2)
        FiveElementOptionScore.objects.create(option=self.wood_option_2, profile=self.wood, score=2)
        FiveElementOptionScore.objects.create(option=self.fire_option_2, profile=self.fire, score=2)
        FiveElementOptionScore.objects.create(option=self.water_option_3, profile=self.water, score=2)

        category = Category.objects.create(name="五行系列", slug="five-elements")
        self.wood_symbol = Product.objects.create(
            name="绿幽灵吊坠",
            slug="green-phantom-pendant",
            category=category,
            short_description="木的主符号。",
            description="帮助你重新进入生成与展开。",
            price="99.00",
            stock_quantity=10,
            is_active=True,
            is_purchasable=True,
            is_featured=True,
            sort_order=1,
        )
        self.wood_ritual = Product.objects.create(
            name="书写本",
            slug="journal-book",
            category=category,
            short_description="木的仪式物。",
            description="让感受被整理，被书写。",
            price="29.00",
            stock_quantity=10,
            is_active=True,
            is_purchasable=True,
            sort_order=2,
        )
        self.wood_ambient = Product.objects.create(
            name="木系精油",
            slug="wood-oil",
            category=category,
            short_description="木的氛围物。",
            description="让生长感延伸到空间。",
            price="39.00",
            stock_quantity=10,
            is_active=True,
            is_purchasable=True,
            sort_order=3,
        )
        self.wood_backup = Product.objects.create(
            name="木主题备用推荐",
            slug="wood-backup",
            category=category,
            short_description="木的备用推荐。",
            description="用于补位。",
            price="19.00",
            stock_quantity=10,
            is_active=True,
            is_purchasable=True,
            sort_order=4,
        )
        FiveElementProfileProduct.objects.create(profile=self.wood, product=self.wood_symbol, role=FiveElementProfileProduct.ProductRole.PRIMARY_SYMBOL, blurb="让生长先被看见。", sort_order=1)
        FiveElementProfileProduct.objects.create(profile=self.wood, product=self.wood_ritual, role=FiveElementProfileProduct.ProductRole.RITUAL_OBJECT, blurb="把内在变化写下来。", sort_order=2)
        FiveElementProfileProduct.objects.create(profile=self.wood, product=self.wood_ambient, role=FiveElementProfileProduct.ProductRole.AMBIENT_OBJECT, blurb="让空间也开始生长。", sort_order=3)
        FiveElementProfileProduct.objects.create(profile=self.wood, product=self.wood_backup, role=FiveElementProfileProduct.ProductRole.BACKUP, sort_order=4)


class FiveElementQuizServiceTests(FiveElementQuizTestCase):
    def test_evaluate_five_element_result_returns_richer_score_data(self):
        evaluation = evaluate_five_element_result(
            quiz=self.quiz,
            option_ids=[self.wood_option_1.id, self.wood_option_2.id, self.water_option_3.id],
        )

        self.assertEqual(evaluation["primary_profile"], self.wood)
        self.assertEqual(evaluation["secondary_profile"], self.water)
        self.assertEqual(evaluation["primary_score"], 4)
        self.assertEqual(evaluation["secondary_score"], 2)
        self.assertEqual(evaluation["score_gap"], 2)
        self.assertEqual(evaluation["total_score"], 7)
        self.assertEqual(evaluation["score_snapshot"]["wood"], 4)
        self.assertEqual(evaluation["score_snapshot"]["fire"], 1)

    def test_get_profile_recommendations_returns_three_distinct_roles(self):
        recommendations = get_profile_recommendations(self.wood)

        self.assertEqual(len(recommendations), 3)
        self.assertEqual(recommendations[0]["role"], FiveElementProfileProduct.ProductRole.PRIMARY_SYMBOL)
        self.assertEqual(recommendations[1]["role"], FiveElementProfileProduct.ProductRole.RITUAL_OBJECT)
        self.assertEqual(recommendations[2]["role"], FiveElementProfileProduct.ProductRole.AMBIENT_OBJECT)
        self.assertEqual(recommendations[0]["product"], self.wood_symbol)
        self.assertEqual(recommendations[1]["product"], self.wood_ritual)
        self.assertEqual(recommendations[2]["product"], self.wood_ambient)

    def test_build_result_summary_returns_reusable_copy(self):
        summary = build_result_summary(self.wood, self.fire)

        self.assertEqual(summary["headline"], self.wood.result_title)
        self.assertEqual(summary["theme_word"], self.wood.theme_word)
        self.assertIn(self.wood.emotion_title, summary["summary_lines"])
        self.assertIn(self.fire.name, summary["summary_lines"][-1])
        self.assertEqual(summary["primary_symbol"]["title"], self.wood.primary_symbol_title)


class FiveElementSubmissionAdminTests(FiveElementQuizTestCase):
    def setUp(self):
        super().setUp()
        self.site = AdminSite()
        self.admin = FiveElementSubmissionAdmin(FiveElementSubmission, self.site)
        self.request_factory = RequestFactory()
        self.staff_user = get_user_model().objects.create_user(
            username="admin-user",
            email="admin@example.com",
            password="password123",
            is_staff=True,
            is_superuser=True,
        )

    def test_export_selected_submissions_outputs_csv_with_lead_fields(self):
        submission = FiveElementSubmission.objects.create(
            quiz=self.quiz,
            primary_profile=self.wood,
            secondary_profile=self.fire,
            respondent_name="Amy",
            respondent_email="amy@example.com",
            answers_json=[{"question": self.question_1.prompt, "option": self.wood_option_1.label}],
            score_snapshot={"wood": 4, "fire": 3},
            utm_source="instagram",
            utm_medium="paid-social",
            utm_campaign="spring-launch",
        )

        request = self.request_factory.post("/admin/pages/fiveelementsubmission/")
        response = self.admin.export_selected_submissions(request, FiveElementSubmission.objects.filter(pk=submission.pk))
        content = response.content.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="five-element-submissions.csv"')
        self.assertIn("respondent_email", content)
        self.assertIn("amy@example.com", content)
        self.assertIn("instagram", content)
        self.assertIn("spring-launch", content)

    def test_submission_admin_list_shows_new_operational_filters_and_columns(self):
        self.client.force_login(self.staff_user)
        FiveElementSubmission.objects.create(
            quiz=self.quiz,
            primary_profile=self.wood,
            secondary_profile=self.fire,
            respondent_name="Amy",
            respondent_email="amy@example.com",
            score_snapshot={"wood": 4, "fire": 3},
            utm_source="instagram",
            utm_medium="paid-social",
            utm_campaign="spring-launch",
        )

        response = self.client.get(reverse("admin:pages_fiveelementsubmission_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "留资状态")
        self.assertContains(response, "是否有来源")
        self.assertContains(response, "次级结果")
        self.assertContains(response, "instagram / paid-social / spring-launch")
        self.assertContains(response, "已留资")


class FiveElementQuizViewTests(FiveElementQuizTestCase):
    def test_home_page_exposes_quiz_entry(self):
        response = self.client.get(reverse("pages:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("pages:five_element_quiz_landing", kwargs={"slug": self.quiz.slug}))
        self.assertContains(response, "先识别你此刻最需要被怎样对待")

    def test_quiz_landing_page_renders_question_count_steps_and_reassurance_copy(self):
        response = self.client.get(reverse("pages:five_element_quiz_landing", kwargs={"slug": self.quiz.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/five_element_quiz_landing.html")
        self.assertContains(response, self.quiz.title)
        self.assertContains(response, "3 道问题")
        self.assertContains(response, "Step 1")
        self.assertContains(response, self.wood.theme_word)
        self.assertContains(response, self.fire.theme_word)
        self.assertContains(response, "先了解你会得到什么")
        self.assertContains(response, "邮箱可以稍后再留")

    def test_quiz_take_page_renders_progressive_stepper_content(self):
        response = self.client.get(reverse("pages:five_element_quiz_take", kwargs={"slug": self.quiz.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/five_element_quiz_take.html")
        self.assertContains(response, self.question_1.prompt)
        self.assertContains(response, "当前进度")
        self.assertContains(response, "进入最后一步")
        self.assertContains(response, "Final step")
        self.assertContains(response, "查看结果与推荐")
        self.assertContains(response, "邮箱只在你愿意继续保持连接时再留")

    def test_quiz_submission_creates_result_and_redirects(self):
        response = self.client.post(
            reverse("pages:five_element_quiz_take", kwargs={"slug": self.quiz.slug}),
            {
                "respondent_name": "Amy",
                "respondent_email": "amy@example.com",
                f"question_{self.question_1.id}": str(self.wood_option_1.id),
                f"question_{self.question_2.id}": str(self.wood_option_2.id),
                f"question_{self.question_3.id}": str(self.water_option_3.id),
            },
        )

        submission = FiveElementSubmission.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(submission.primary_profile, self.wood)
        self.assertEqual(submission.respondent_email, "amy@example.com")
        self.assertEqual(submission.score_snapshot["wood"], 4)

    def test_result_page_renders_emotion_first_copy_score_breakdown_and_recommendations(self):
        submission = FiveElementSubmission.objects.create(
            quiz=self.quiz,
            primary_profile=self.wood,
            secondary_profile=self.fire,
            respondent_email="amy@example.com",
            answers_json=[{"question": self.question_1.prompt, "option": self.wood_option_1.label}],
            score_snapshot={"wood": 4, "fire": 3, "water": 2},
        )

        response = self.client.get(
            reverse("pages:five_element_quiz_result", kwargs={"slug": self.quiz.slug, "token": submission.token})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/five_element_quiz_result.html")
        self.assertContains(response, self.wood.emotion_title)
        self.assertContains(response, "你的结果结构")
        self.assertContains(response, "主导结果")
        self.assertContains(response, self.wood.primary_symbol_title)
        self.assertContains(response, self.wood_symbol.name)
        self.assertContains(response, self.wood_ritual.name)
        self.assertContains(response, self.wood_ambient.name)
        self.assertContains(response, "先从主符号认出自己")
        self.assertContains(response, "查看为什么推荐它")
        self.assertContains(response, "带走这件承接物")

    def test_result_page_renders_post_result_lead_capture_form_when_email_missing(self):
        submission = FiveElementSubmission.objects.create(
            quiz=self.quiz,
            primary_profile=self.wood,
            secondary_profile=self.fire,
            respondent_name="Amy",
            answers_json=[{"question": self.question_1.prompt, "option": self.wood_option_1.label}],
            score_snapshot={"wood": 4, "fire": 3, "water": 2},
        )

        response = self.client.get(
            reverse("pages:five_element_quiz_result", kwargs={"slug": self.quiz.slug, "token": submission.token})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "如果你愿意，可以把这份结果留给未来的自己。")
        self.assertContains(response, "保存这份结果")
        self.assertContains(response, 'name="respondent_email"')

    def test_result_page_post_updates_submission_email_and_redirects(self):
        submission = FiveElementSubmission.objects.create(
            quiz=self.quiz,
            primary_profile=self.wood,
            secondary_profile=self.fire,
            respondent_name="Amy",
            answers_json=[{"question": self.question_1.prompt, "option": self.wood_option_1.label}],
            score_snapshot={"wood": 4, "fire": 3, "water": 2},
        )

        response = self.client.post(
            reverse("pages:five_element_quiz_result", kwargs={"slug": self.quiz.slug, "token": submission.token}),
            {
                "respondent_name": "Amy",
                "respondent_email": "amy@example.com",
            },
        )

        submission.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(submission.respondent_email, "amy@example.com")
