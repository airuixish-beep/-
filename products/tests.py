from decimal import Decimal

from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from orders.models import Order, OrderItem

from .models import Category, InventoryRecord, Product, ProductImage, ProductVariant
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

    def test_product_list_context_includes_top_level_active_categories(self):
        active_top = Category.objects.create(name="Active Top", slug="active-top", is_active=True)
        Category.objects.create(name="Inactive Top", slug="inactive-top", is_active=False)
        Category.objects.create(name="Child", slug="child", is_active=True, parent=active_top)

        response = self.client.get(reverse("products:list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["categories"]), [active_top])

    def test_product_list_filters_by_category_slug(self):
        fragrance = Category.objects.create(name="Fragrance", slug="fragrance", is_active=True)
        object_category = Category.objects.create(name="Object", slug="object", is_active=True)
        matching = self.create_product("Matching Product", category=fragrance)
        self.create_product("Other Product", category=object_category)

        response = self.client.get(reverse("products:list"), {"category": fragrance.slug})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["products"]), [matching])
        self.assertEqual(response.context["selected_category_slug"], fragrance.slug)
        self.assertTrue(response.context["has_filters"])
        self.assertEqual(response.context["recommended_products"], [])

    def test_product_list_category_filter_keeps_inactive_products_hidden(self):
        category = Category.objects.create(name="Fragrance", slug="fragrance", is_active=True)
        visible = self.create_product("Visible Product", category=category)
        self.create_product("Hidden Product", category=category, is_active=False)

        response = self.client.get(reverse("products:list"), {"category": category.slug})

        self.assertEqual(list(response.context["products"]), [visible])

    def test_product_list_featured_filter(self):
        featured = self.create_product("Featured Product", is_featured=True)
        self.create_product("Regular Product", is_featured=False)

        response = self.client.get(reverse("products:list"), {"featured": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["products"]), [featured])
        self.assertTrue(response.context["selected_featured"])
        self.assertTrue(response.context["has_filters"])
        self.assertEqual(response.context["recommended_products"], [])

    def test_product_list_available_filter(self):
        available = self.create_product("Available Product", is_purchasable=True, stock_quantity=5)
        self.create_product("No Stock Product", is_purchasable=True, stock_quantity=0)
        self.create_product("Not Purchasable Product", is_purchasable=False, stock_quantity=5)

        response = self.client.get(reverse("products:list"), {"available": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["products"]), [available])
        self.assertTrue(response.context["selected_available"])
        self.assertTrue(response.context["has_filters"])
        self.assertEqual(response.context["recommended_products"], [])

    def test_product_detail_context_includes_related_products(self):
        product = self.create_product("Current Product")
        related = self.create_product("Related Product", is_featured=True)

        response = self.client.get(reverse("products:detail", kwargs={"slug": product.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertIn("recommended_products", response.context)
        self.assertIn(related, response.context["recommended_products"])
        self.assertNotIn(product, response.context["recommended_products"])


class ProductVariantModelTests(TestCase):
    def test_variant_updates_product_price_stock_and_purchasable(self):
        product = Product.objects.create(
            name="Variant Product",
            slug="variant-product",
            currency=Product.Currency.USD,
            is_active=True,
        )

        ProductVariant.objects.create(
            product=product,
            sku="SKU-001",
            option_summary="50ml / 白色",
            price=Decimal("199.00"),
            stock_quantity=8,
            is_active=True,
        )
        ProductVariant.objects.create(
            product=product,
            sku="SKU-002",
            option_summary="100ml / 黑色",
            price=Decimal("259.00"),
            stock_quantity=0,
            is_active=True,
        )

        product.refresh_from_db()

        self.assertEqual(product.price, Decimal("199.00"))
        self.assertEqual(product.stock_quantity, 8)
        self.assertTrue(product.is_purchasable)

    def test_variant_stock_changes_create_inventory_records(self):
        product = Product.objects.create(
            name="Inventory Product",
            slug="inventory-product",
            currency=Product.Currency.USD,
        )

        variant = ProductVariant.objects.create(
            product=product,
            sku="SKU-003",
            option_summary="默认款",
            price=Decimal("99.00"),
            stock_quantity=5,
        )

        initial_record = InventoryRecord.objects.get(variant=variant)
        self.assertEqual(initial_record.change_type, InventoryRecord.ChangeType.INITIAL_STOCK)
        self.assertEqual(initial_record.before_quantity, 0)
        self.assertEqual(initial_record.after_quantity, 5)

        variant.stock_quantity = 9
        variant.save()

        adjustment_record = InventoryRecord.objects.filter(variant=variant).order_by("-id").first()
        self.assertEqual(adjustment_record.change_type, InventoryRecord.ChangeType.MANUAL_ADJUSTMENT)
        self.assertEqual(adjustment_record.quantity_change, 4)
        self.assertEqual(adjustment_record.before_quantity, 5)
        self.assertEqual(adjustment_record.after_quantity, 9)

    def test_product_display_helpers_use_active_variants(self):
        category = Category.objects.create(name="香氛", slug="fragrance")
        product = Product.objects.create(
            name="Display Product",
            slug="display-product",
            category=category,
            currency=Product.Currency.CNY,
            is_active=True,
        )

        ProductVariant.objects.create(
            product=product,
            sku="SKU-DISPLAY-1",
            option_summary="50ml / 白色",
            price=Decimal("199.00"),
            stock_quantity=3,
            is_active=True,
        )
        ProductVariant.objects.create(
            product=product,
            sku="SKU-DISPLAY-2",
            option_summary="100ml / 黑色",
            price=Decimal("299.00"),
            stock_quantity=9,
            is_active=True,
        )

        self.assertEqual(product.display_sku, "")
        self.assertEqual(product.price_range, (Decimal("199.00"), Decimal("299.00")))
        self.assertTrue(product.has_variant_price_range)
        self.assertEqual(product.display_price, Decimal("199.00"))
        self.assertEqual(product.stock_status_label, "现货可购")

    def test_product_ordered_images_include_gallery_images(self):
        product = Product.objects.create(name="Image Product", slug="image-product")
        image_late = ProductImage.objects.create(product=product, alt_text="late", sort_order=20)
        image_late.image.save("late.png", ContentFile(b"late"), save=True)
        image_early = ProductImage.objects.create(product=product, alt_text="early", sort_order=10)
        image_early.image.save("early.png", ContentFile(b"early"), save=True)

        self.assertEqual(product.ordered_images, [image_early, image_late])


class DemoSeedCommandTests(TestCase):
    def test_seed_product_demo_is_idempotent(self):
        call_command("seed_product_demo")
        first_counts = {
            "categories": Category.objects.count(),
            "products": Product.objects.count(),
            "variants": ProductVariant.objects.count(),
            "images": ProductImage.objects.count(),
        }

        call_command("seed_product_demo")
        second_counts = {
            "categories": Category.objects.count(),
            "products": Product.objects.count(),
            "variants": ProductVariant.objects.count(),
            "images": ProductImage.objects.count(),
        }

        self.assertEqual(first_counts, second_counts)
        seeded_product = Product.objects.get(slug="stillness-incense-oil")
        self.assertEqual(seeded_product.currency, Product.Currency.CNY)
        self.assertTrue(seeded_product.is_purchasable)
        self.assertGreater(seeded_product.stock_quantity, 0)
