from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import SiteConfig
from products.models import Category, Product

from .models import (
    FiveElementOption,
    FiveElementOptionScore,
    FiveElementProfile,
    FiveElementProfileProduct,
    FiveElementQuestion,
    FiveElementQuiz,
    FiveElementSubmission,
)
from .services import evaluate_five_element_result, get_profile_recommendations


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
            estimated_minutes=3,
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
        self.wood_option_1 = FiveElementOption.objects.create(question=self.question_1, label="先写下来，让混乱慢慢长出方向。", sort_order=1)
        self.fire_option_1 = FiveElementOption.objects.create(question=self.question_1, label="先让自己暖起来，再重新进入状态。", sort_order=2)
        self.wood_option_2 = FiveElementOption.objects.create(question=self.question_2, label="一个允许我慢慢展开的空间。", sort_order=1)
        self.fire_option_2 = FiveElementOption.objects.create(question=self.question_2, label="一种能让我回温的陪伴。", sort_order=2)
        FiveElementOptionScore.objects.create(option=self.wood_option_1, profile=self.wood, score=2)
        FiveElementOptionScore.objects.create(option=self.wood_option_1, profile=self.fire, score=1)
        FiveElementOptionScore.objects.create(option=self.fire_option_1, profile=self.fire, score=2)
        FiveElementOptionScore.objects.create(option=self.wood_option_2, profile=self.wood, score=2)
        FiveElementOptionScore.objects.create(option=self.fire_option_2, profile=self.fire, score=2)

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
    def test_evaluate_five_element_result_returns_ranked_profiles(self):
        evaluation = evaluate_five_element_result(
            quiz=self.quiz,
            option_ids=[self.wood_option_1.id, self.wood_option_2.id],
        )

        self.assertEqual(evaluation["primary_profile"], self.wood)
        self.assertEqual(evaluation["secondary_profile"], self.fire)
        self.assertFalse(evaluation["is_close_match"])
        self.assertEqual(evaluation["score_snapshot"]["wood"], 4)
        self.assertEqual(evaluation["score_snapshot"]["fire"], 1)

    def test_evaluate_five_element_result_marks_close_scores_as_close_match(self):
        evaluation = evaluate_five_element_result(
            quiz=self.quiz,
            option_ids=[self.fire_option_1.id, self.wood_option_2.id],
        )

        self.assertEqual(evaluation["primary_profile"], self.wood)
        self.assertEqual(evaluation["secondary_profile"], self.fire)
        self.assertTrue(evaluation["is_close_match"])
        self.assertEqual(evaluation["score_snapshot"]["wood"], 2)
        self.assertEqual(evaluation["score_snapshot"]["fire"], 2)

    def test_get_profile_recommendations_returns_three_distinct_roles(self):
        recommendations = get_profile_recommendations(self.wood)

        self.assertEqual(len(recommendations), 3)
        self.assertEqual(recommendations[0]["role"], FiveElementProfileProduct.ProductRole.PRIMARY_SYMBOL)
        self.assertEqual(recommendations[1]["role"], FiveElementProfileProduct.ProductRole.RITUAL_OBJECT)
        self.assertEqual(recommendations[2]["role"], FiveElementProfileProduct.ProductRole.AMBIENT_OBJECT)
        self.assertEqual(recommendations[0]["product"], self.wood_symbol)
        self.assertEqual(recommendations[1]["product"], self.wood_ritual)
        self.assertEqual(recommendations[2]["product"], self.wood_ambient)


class FiveElementQuizViewTests(FiveElementQuizTestCase):
    def test_home_page_exposes_quiz_entry(self):
        response = self.client.get(reverse("pages:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("pages:five_element_quiz_landing", kwargs={"slug": self.quiz.slug}))
        self.assertContains(response, "先识别你此刻最需要被怎样对待")

    def test_quiz_landing_page_renders(self):
        response = self.client.get(reverse("pages:five_element_quiz_landing", kwargs={"slug": self.quiz.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/five_element_quiz_landing.html")
        self.assertContains(response, self.quiz.title)
        self.assertContains(response, self.wood.theme_word)
        self.assertContains(response, self.fire.theme_word)

    def test_quiz_take_page_renders_questions(self):
        response = self.client.get(reverse("pages:five_element_quiz_take", kwargs={"slug": self.quiz.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/five_element_quiz_take.html")
        self.assertContains(response, self.question_1.prompt)
        self.assertContains(response, self.wood_option_1.label)

    def test_quiz_submission_creates_result_and_redirects(self):
        response = self.client.post(
            reverse("pages:five_element_quiz_take", kwargs={"slug": self.quiz.slug}),
            {
                "respondent_name": "Amy",
                "respondent_email": "amy@example.com",
                f"question_{self.question_1.id}": str(self.wood_option_1.id),
                f"question_{self.question_2.id}": str(self.wood_option_2.id),
            },
        )

        submission = FiveElementSubmission.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(submission.primary_profile, self.wood)
        self.assertEqual(submission.respondent_email, "amy@example.com")
        self.assertEqual(submission.score_snapshot["wood"], 4)

    def test_result_page_renders_emotion_first_copy_and_recommendations(self):
        submission = FiveElementSubmission.objects.create(
            quiz=self.quiz,
            primary_profile=self.wood,
            secondary_profile=self.fire,
            respondent_email="amy@example.com",
            answers_json=[{"question": self.question_1.prompt, "option": self.wood_option_1.label}],
            score_snapshot={"wood": 4, "fire": 3},
        )

        response = self.client.get(
            reverse("pages:five_element_quiz_result", kwargs={"slug": self.quiz.slug, "token": submission.token})
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/five_element_quiz_result.html")
        self.assertContains(response, self.wood.emotion_title)
        self.assertContains(response, self.wood.primary_symbol_title)
        self.assertContains(response, self.wood_symbol.name)
        self.assertContains(response, self.wood_ritual.name)
        self.assertContains(response, self.wood_ambient.name)
