from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from orders.models import Order, OrderItem

from .models import Product
from .services import get_recommended_products


class RecommendationServiceTests(TestCase):
    def create_product(self, name, **overrides):
        defaults = {
            "slug": name.lower().replace(" ", "-"),
            "price": Decimal("100.00"),
            "currency": Product.Currency.USD,
            "stock_quantity": 10,
            "is_active": True,
            "is_purchasable": True,
        }
        defaults.update(overrides)
        return Product.objects.create(name=name, **defaults)

    def create_paid_order_item(self, product, *, quantity, line_total):
        order = Order.objects.create(
            customer_name="Test Customer",
            customer_email="test@example.com",
            shipping_country="US",
            shipping_city="New York",
            shipping_postal_code="10001",
            shipping_address_line1="123 Test St",
            currency=product.currency,
            payment_status=Order.PaymentStatus.PAID,
            status=Order.Status.PAID,
            paid_at=timezone.now(),
            total_amount=Decimal(line_total),
            subtotal_amount=Decimal(line_total),
        )
        return OrderItem.objects.create(
            order=order,
            product=product,
            product_name_snapshot=product.name,
            sku_snapshot=product.sku or "",
            unit_price=Decimal(line_total) / quantity,
            quantity=quantity,
        )

    def test_recommendations_exclude_current_product(self):
        current = self.create_product("Current Product")
        featured = self.create_product("Featured Product", is_featured=True)

        recommendations = get_recommended_products(exclude_product=current, limit=4)

        self.assertIn(featured, recommendations)
        self.assertNotIn(current, recommendations)

    def test_recommendations_prioritize_best_sellers(self):
        current = self.create_product("Current Product")
        bestseller = self.create_product("Best Seller")
        featured = self.create_product("Featured Product", is_featured=True)
        self.create_paid_order_item(bestseller, quantity=5, line_total="500.00")

        recommendations = get_recommended_products(exclude_product=current, limit=2)

        self.assertEqual(recommendations[0], bestseller)
        self.assertIn(featured, recommendations)

    def test_recommendations_fallback_to_featured_then_latest(self):
        current = self.create_product("Current Product")
        featured = self.create_product("Featured Product", is_featured=True)
        latest = self.create_product("Latest Product")
        older = self.create_product("Older Product")
        Product.objects.filter(pk=older.pk).update(created_at=timezone.now() - timezone.timedelta(days=2))
        older.refresh_from_db()

        recommendations = get_recommended_products(exclude_product=current, limit=3)

        self.assertEqual(recommendations[0], featured)
        self.assertEqual(recommendations[1], latest)
        self.assertEqual(recommendations[2], older)

    def test_recommendations_prefer_purchasable_in_stock_products(self):
        current = self.create_product("Current Product")
        available = self.create_product("Available Product")
        self.create_product("Out Of Stock Product", stock_quantity=0)
        self.create_product("Inactive Product", is_active=False)
        self.create_product("Not Purchasable Product", is_purchasable=False)

        recommendations = get_recommended_products(exclude_product=current, limit=1)

        self.assertEqual(recommendations, [available])


class RecommendationViewTests(TestCase):
    def create_product(self, name, **overrides):
        defaults = {
            "slug": name.lower().replace(" ", "-"),
            "price": Decimal("100.00"),
            "currency": Product.Currency.USD,
            "stock_quantity": 10,
            "is_active": True,
            "is_purchasable": True,
        }
        defaults.update(overrides)
        return Product.objects.create(name=name, **defaults)

    def test_home_context_includes_recommended_products(self):
        self.create_product("Featured Product", is_featured=True)
        response = self.client.get(reverse("pages:home"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("recommended_products", response.context)
        self.assertTrue(response.context["recommended_products"])

    def test_product_list_context_includes_recommended_products(self):
        self.create_product("Product One")
        response = self.client.get(reverse("products:list"))

        self.assertEqual(response.status_code, 200)
        self.assertIn("recommended_products", response.context)
        self.assertTrue(response.context["recommended_products"])

    def test_product_detail_context_includes_related_products(self):
        product = self.create_product("Current Product")
        related = self.create_product("Related Product", is_featured=True)

        response = self.client.get(reverse("products:detail", kwargs={"slug": product.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertIn("recommended_products", response.context)
        self.assertIn(related, response.context["recommended_products"])
        self.assertNotIn(product, response.context["recommended_products"])
