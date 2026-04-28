from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from orders.models import Order, OrderItem
from pages.models import FiveElementOption, FiveElementProfile, FiveElementQuestion, FiveElementQuiz, FiveElementSubmission
from payments.models import Payment
from products.models import Product
from shipping.models import Shipment
from transactions.engine import TransactionEngine
from transactions.models import Refund
from transactions.refunds import RefundCenter
from transactions.services import get_or_create_purchase_transaction

from .services import build_dashboard_context, build_quiz_dashboard_context, parse_dashboard_filters


class AnalyticsDashboardAccessTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="password123",
            is_staff=True,
        )
        self.regular_user = user_model.objects.create_user(
            username="regular",
            email="regular@example.com",
            password="password123",
        )

    def test_staff_user_can_access_dashboard(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("analytics_dashboard:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "经营驾驶舱")
        self.assertContains(response, "营销与漏斗数据（待接入）")

    def test_anonymous_user_is_redirected(self):
        response = self.client.get(reverse("analytics_dashboard:index"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_non_staff_user_cannot_access_dashboard(self):
        self.client.force_login(self.regular_user)

        response = self.client.get(reverse("analytics_dashboard:index"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin:login"), response["Location"])

    def test_dashboard_renders_with_empty_database(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("analytics_dashboard:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "经营驾驶舱")
        self.assertContains(response, "支付记录分析")
        self.assertContains(response, "发货状态分析")
        self.assertContains(response, "当前时间范围暂无支付记录。")
        self.assertContains(response, "当前没有低库存可售商品。")


class QuizDashboardServiceTests(TestCase):
    def setUp(self):
        self.quiz = FiveElementQuiz.objects.create(
            name="五行情绪人格测试",
            slug="five-elements",
            title="测试你的五行人格与当下仪式路径",
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
            primary_symbol_title="绿幽灵吊坠 / 项链",
            ritual_object_title="书写本 / Journal",
            ambient_object_title="扩香木 / 木系精油",
        )
        self.fire = FiveElementProfile.objects.create(
            quiz=self.quiz,
            code=FiveElementProfile.ElementCode.FIRE,
            name="火",
            theme_word="回温",
            emotion_title="你现在需要慢慢回温。",
            emotion_body="不是再被点燃一次，而是让身体和心重新有温度。",
            result_title="你的主导五行是火",
            primary_symbol_title="石榴石吊坠 / 项链",
            ritual_object_title="肉桂精油",
            ambient_object_title="扩香木 / 香气仪式物",
        )
        self.question = FiveElementQuestion.objects.create(quiz=self.quiz, prompt="当你卡住时，你最想先做什么？")
        self.option_wood = FiveElementOption.objects.create(question=self.question, label="先写下来。")
        self.option_fire = FiveElementOption.objects.create(question=self.question, label="先让自己暖起来。")
        self.submission_one = FiveElementSubmission.objects.create(
            quiz=self.quiz,
            primary_profile=self.wood,
            secondary_profile=self.fire,
            respondent_email="amy@example.com",
            score_snapshot={"wood": 5, "fire": 3},
        )
        self.submission_two = FiveElementSubmission.objects.create(
            quiz=self.quiz,
            primary_profile=self.fire,
            respondent_email="jane@example.com",
            score_snapshot={"fire": 4, "wood": 2},
        )

    def test_quiz_dashboard_context_aggregates_submissions_leads_and_attribution(self):
        self.submission_one.utm_source = "instagram"
        self.submission_one.utm_medium = "paid-social"
        self.submission_one.utm_campaign = "spring-launch"
        self.submission_one.save(update_fields=["utm_source", "utm_medium", "utm_campaign", "updated_at"])
        filters = parse_dashboard_filters(QueryDict("range=30d&currency=USD"))

        context = build_quiz_dashboard_context(filters)

        self.assertEqual(context["quiz_summary"]["total_submissions"], 2)
        self.assertEqual(context["quiz_summary"]["lead_count"], 2)
        self.assertEqual(context["quiz_summary"]["lead_rate"], 100.0)
        self.assertEqual(context["quiz_summary"]["result_counts"]["木"], 1)
        self.assertEqual(context["quiz_summary"]["result_counts"]["火"], 1)
        self.assertEqual(len(context["quiz_summary"]["recent_submissions"]), 2)
        self.assertEqual(context["quiz_attribution"]["sources"][0]["label"], "instagram")
        self.assertEqual(context["quiz_attribution"]["sources"][0]["count"], 1)


class QuizDashboardNavigationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="staff-nav",
            email="staff-nav@example.com",
            password="password123",
            is_staff=True,
        )

    def test_admin_index_links_to_quiz_dashboard(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("analytics_dashboard:quiz"))
        self.assertContains(response, "五行测试统计")


class QuizDashboardViewTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="staff-quiz",
            email="staff-quiz@example.com",
            password="password123",
            is_staff=True,
        )

    def test_staff_user_can_access_quiz_dashboard(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("analytics_dashboard:quiz"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "五行测试提交统计")
        self.assertContains(response, "测试提交数")
        self.assertContains(response, "主导结果分布")
        self.assertContains(response, "来源归因")
        self.assertContains(response, "查看对应提交")


class AnalyticsDashboardServiceTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.paid_product = Product.objects.create(
            name="热销戒指",
            slug="hot-ring",
            sku="RING-001",
            price=Decimal("100.00"),
            currency=Product.Currency.USD,
            stock_quantity=3,
            is_active=True,
            is_purchasable=True,
        )
        self.secondary_product = Product.objects.create(
            name="项链",
            slug="necklace",
            sku="NECK-001",
            price=Decimal("80.00"),
            currency=Product.Currency.USD,
            stock_quantity=20,
            is_active=True,
            is_purchasable=True,
        )
        self.unpaid_product = Product.objects.create(
            name="未支付商品",
            slug="pending-product",
            sku="PEND-001",
            price=Decimal("60.00"),
            currency=Product.Currency.USD,
            stock_quantity=10,
            is_active=True,
            is_purchasable=True,
        )

        self.delivered_order = self._create_order(
            customer_name="Alice",
            customer_email="alice@example.com",
            shipping_city="Shanghai",
            shipping_country="CN",
            shipping_amount=Decimal("10.00"),
            items=[
                (self.paid_product, 1),
                (self.secondary_product, 1),
            ],
            mark_paid=True,
            provider=Payment.Provider.STRIPE,
            shipment_status=Shipment.Status.DELIVERED,
            paid_at=self.now - timedelta(days=1),
        )
        self.in_transit_order = self._create_order(
            customer_name="Bob",
            customer_email="bob@example.com",
            shipping_city="Beijing",
            shipping_country="CN",
            shipping_amount=Decimal("5.00"),
            items=[(self.paid_product, 1)],
            mark_paid=True,
            provider=Payment.Provider.PAYPAL,
            shipment_status=Shipment.Status.IN_TRANSIT,
            paid_at=self.now,
        )
        self.failed_order = self._create_order(
            customer_name="Carol",
            customer_email="carol@example.com",
            shipping_city="New York",
            shipping_country="US",
            shipping_amount=Decimal("8.00"),
            items=[(self.unpaid_product, 1)],
            mark_paid=False,
            provider=Payment.Provider.STRIPE,
            payment_status=Payment.Status.FAILED,
        )

        refund_transaction = self.delivered_order.transactions.first()
        refund = RefundCenter.create_request(
            refund_transaction,
            amount=Decimal("20.00"),
            currency="USD",
            reason="analytics refund",
        )
        refund.status = Refund.Status.SUCCEEDED
        refund.provider_refund_id = "re_analytics_1"
        refund.save(update_fields=["status", "provider_refund_id", "updated_at"])
        TransactionEngine.mark_refund_succeeded(
            refund,
            source="analytics.test",
            idempotency_key="analytics-refund:1",
            provider_refund_id="re_analytics_1",
            payload={"source": "analytics.test"},
        )

    def test_dashboard_context_aggregates_paid_orders_and_shipping_metrics(self):
        filters = parse_dashboard_filters(QueryDict("range=30d&currency=USD"))

        context = build_dashboard_context(filters)

        self.assertEqual(context["kpis"]["order_count"], 3)
        self.assertEqual(context["kpis"]["paid_order_count"], 2)
        self.assertEqual(context["kpis"]["gmv"], Decimal("295.00"))
        self.assertEqual(context["kpis"]["refund_total"], Decimal("20.00"))
        self.assertEqual(context["kpis"]["net_revenue"], Decimal("275.00"))
        self.assertEqual(context["kpis"]["average_order_value"], Decimal("147.50"))
        self.assertEqual(context["kpis"]["payment_conversion_rate"], 66.7)
        self.assertEqual(float(context["kpis"]["refund_rate"]), 6.8)
        self.assertEqual(context["kpis"]["shipping_in_progress_count"], 1)
        self.assertEqual(context["kpis"]["delivered_order_count"], 1)

        payment_rows = {row["provider"]: row for row in context["payment_summary"]["providers"]}
        self.assertEqual(payment_rows[Payment.Provider.STRIPE]["paid_count"], 1)
        self.assertEqual(payment_rows[Payment.Provider.PAYPAL]["paid_count"], 1)
        self.assertEqual(context["payment_summary"]["failed_count"], 1)
        self.assertEqual(context["financial_summary"]["gross_total"], Decimal("295.00"))
        self.assertEqual(context["financial_summary"]["refund_total"], Decimal("20.00"))
        self.assertEqual(context["financial_summary"]["fee_total"], Decimal("0.00"))
        self.assertEqual(context["financial_summary"]["net_revenue"], Decimal("275.00"))

    def test_product_leaderboard_only_counts_paid_items(self):
        filters = parse_dashboard_filters(QueryDict("range=30d&currency=USD"))

        context = build_dashboard_context(filters)

        top_quantity_names = [row["product_name_snapshot"] for row in context["product_summary"]["top_by_quantity"]]
        top_sales_names = [row["product_name_snapshot"] for row in context["product_summary"]["top_by_sales"]]
        low_stock_names = [product.name for product in context["product_summary"]["low_stock_products"]]
        country_rows = {row["shipping_country"]: row for row in context["geo_summary"]["countries"]}

        self.assertIn("热销戒指", top_quantity_names)
        self.assertIn("项链", top_sales_names)
        self.assertNotIn("未支付商品", top_quantity_names)
        self.assertIn("热销戒指", low_stock_names)
        self.assertEqual(country_rows["CN"]["order_count"], 2)
        self.assertEqual(country_rows["CN"]["sales_total"], Decimal("295.00"))

    def test_dashboard_uses_current_shipment_per_paid_order(self):
        filters = parse_dashboard_filters(QueryDict("range=30d&currency=USD"))
        stale_shipment = self.in_transit_order.shipments.first()
        stale_shipment.status = Shipment.Status.IN_TRANSIT
        stale_shipment.save(update_fields=["status", "updated_at"])
        Shipment.objects.create(
            order=self.in_transit_order,
            provider=Shipment.Provider.MANUAL,
            status=Shipment.Status.DELIVERED,
        )

        context = build_dashboard_context(filters)

        self.assertEqual(context["kpis"]["shipping_in_progress_count"], 0)
        self.assertEqual(context["kpis"]["delivered_order_count"], 2)
        shipping_rows = {row["value"]: row for row in context["shipping_summary"]["rows"]}
        self.assertEqual(shipping_rows[Shipment.Status.DELIVERED]["count"], 2)
        self.assertEqual(shipping_rows[Shipment.Status.IN_TRANSIT]["count"], 0)

    def test_dashboard_uses_distinct_time_semantics_for_orders_payments_and_shipping(self):
        out_of_range_day = timezone.localdate() - timedelta(days=45)
        in_range_day = timezone.localdate() - timedelta(days=2)

        created_in_range_paid_outside = self._create_order(
            customer_name="Dana",
            customer_email="dana@example.com",
            shipping_city="Shenzhen",
            shipping_country="CN",
            shipping_amount=Decimal("12.00"),
            items=[(self.secondary_product, 1)],
            mark_paid=False,
            provider=Payment.Provider.STRIPE,
        )
        created_in_range_paid_outside.created_at = timezone.make_aware(datetime.combine(in_range_day, time.min))
        created_in_range_paid_outside.save(update_fields=["created_at"])
        created_in_range_paid_outside.payment_status = Order.PaymentStatus.PAID
        created_in_range_paid_outside.paid_at = timezone.make_aware(datetime.combine(out_of_range_day, time.min))
        created_in_range_paid_outside.save(update_fields=["payment_status", "paid_at", "updated_at"])
        created_in_range_paid_outside_payment = created_in_range_paid_outside.payments.first()
        created_in_range_paid_outside_payment.status = Payment.Status.PAID
        created_in_range_paid_outside_payment.paid_at = created_in_range_paid_outside.paid_at
        created_in_range_paid_outside_payment.created_at = timezone.make_aware(datetime.combine(in_range_day, time.min))
        created_in_range_paid_outside_payment.external_payment_id = f"ext-{created_in_range_paid_outside.order_number}"
        created_in_range_paid_outside_payment.save(update_fields=["status", "paid_at", "created_at", "external_payment_id", "updated_at"])
        transaction_obj = created_in_range_paid_outside.transactions.first()
        transaction_obj.status = transaction_obj.Status.PAID
        transaction_obj.paid_at = created_in_range_paid_outside.paid_at
        transaction_obj.amount = created_in_range_paid_outside.total_amount
        transaction_obj.save(update_fields=["status", "paid_at", "amount", "updated_at"])
        TransactionEngine.post_payment_ledger_entries(transaction_obj, created_in_range_paid_outside_payment)
        Shipment.objects.create(
            order=created_in_range_paid_outside,
            provider=Shipment.Provider.MANUAL,
            status=Shipment.Status.DELIVERED,
        )

        created_outside_paid_in_range = self._create_order(
            customer_name="Ethan",
            customer_email="ethan@example.com",
            shipping_city="Hangzhou",
            shipping_country="CN",
            shipping_amount=Decimal("9.00"),
            items=[(self.secondary_product, 1)],
            mark_paid=True,
            provider=Payment.Provider.STRIPE,
            shipment_status=Shipment.Status.SHIPPED,
            paid_at=timezone.make_aware(datetime.combine(in_range_day, time.min)),
        )
        created_outside_paid_in_range.created_at = timezone.make_aware(datetime.combine(out_of_range_day, time.min))
        created_outside_paid_in_range.save(update_fields=["created_at"])
        created_outside_paid_in_range_payment = created_outside_paid_in_range.payments.first()
        created_outside_paid_in_range_payment.created_at = timezone.make_aware(datetime.combine(out_of_range_day, time.min))
        created_outside_paid_in_range_payment.save(update_fields=["created_at", "updated_at"])
        shipment = created_outside_paid_in_range.shipments.first()
        shipment.created_at = timezone.make_aware(datetime.combine(out_of_range_day, time.min))
        shipment.save(update_fields=["created_at", "updated_at"])

        filters = parse_dashboard_filters(
            QueryDict(f"range=custom&start_date={in_range_day.isoformat()}&end_date={in_range_day.isoformat()}&currency=USD")
        )
        context = build_dashboard_context(filters)

        self.assertEqual(context["kpis"]["order_count"], 1)
        self.assertEqual(context["kpis"]["paid_order_count"], 1)
        self.assertEqual(context["kpis"]["gmv"], created_outside_paid_in_range.total_amount)
        self.assertEqual(context["kpis"]["shipping_in_progress_count"], 1)
        self.assertEqual(context["kpis"]["delivered_order_count"], 0)
        self.assertEqual(context["payment_summary"]["failed_count"], 0)

        trend_row = context["order_trends"]["rows"][0]
        self.assertEqual(trend_row["order_count"], 1)
        self.assertEqual(trend_row["paid_count"], 1)
        self.assertEqual(trend_row["paid_amount"], created_outside_paid_in_range.total_amount)

        payment_rows = {row["provider"]: row for row in context["payment_summary"]["providers"]}
        self.assertEqual(payment_rows[Payment.Provider.STRIPE]["total_count"], 1)
        self.assertEqual(payment_rows[Payment.Provider.STRIPE]["paid_count"], 1)

    def _create_order(
        self,
        *,
        customer_name,
        customer_email,
        shipping_city,
        shipping_country,
        shipping_amount,
        items,
        mark_paid,
        provider,
        shipment_status=None,
        paid_at=None,
        payment_status=Payment.Status.PENDING,
    ):
        order = Order.objects.create(
            customer_name=customer_name,
            customer_email=customer_email,
            shipping_country=shipping_country,
            shipping_city=shipping_city,
            shipping_postal_code="200000",
            shipping_address_line1="1 Example Road",
            shipping_amount=shipping_amount,
            currency=Product.Currency.USD,
        )
        for product, quantity in items:
            OrderItem.objects.create(
                order=order,
                product=product,
                product_name_snapshot=product.name,
                sku_snapshot=product.sku,
                unit_price=product.price,
                quantity=quantity,
            )
        order.recalculate_totals()

        if mark_paid:
            paid_at = paid_at or self.now
            order.mark_paid(paid_at=paid_at)
            payment = Payment.objects.create(
                order=order,
                provider=provider,
                status=Payment.Status.PAID,
                amount=order.total_amount,
                currency=order.currency,
                paid_at=paid_at,
                external_payment_id=f"ext-{order.order_number}",
            )
            transaction_obj = get_or_create_purchase_transaction(order, payment)
            TransactionEngine.confirm_payment_succeeded(
                payment,
                source="analytics.test",
                idempotency_key=f"analytics-paid:{payment.id}",
                external_payment_id=payment.external_payment_id,
                payload={"source": "analytics.test"},
                paid_at=paid_at,
            )
            Shipment.objects.create(
                order=order,
                provider=Shipment.Provider.MANUAL,
                status=shipment_status or Shipment.Status.PENDING,
            )
            order.sync_fulfillment_from_shipment_status(shipment_status or Shipment.Status.PENDING)
        else:
            payment = Payment.objects.create(
                order=order,
                provider=provider,
                status=payment_status,
                amount=order.total_amount,
                currency=order.currency,
            )
            get_or_create_purchase_transaction(order, payment)
            if payment_status == Payment.Status.FAILED:
                order.mark_payment_failed()

        return order
