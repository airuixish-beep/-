from base64 import b64decode

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from products.models import Category, Product, ProductFeature, ProductImage, ProductVariant


PNG_PLACEHOLDER = b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9WnV0uoAAAAASUVORK5CYII="
)


CATALOG = [
    {
        "category": {"slug": "ritual-fragrance", "name": "仪式香氛", "description": "围绕空间、停顿与感知展开的香氛类商品。"},
        "products": [
            {
                "slug": "stillness-incense-oil",
                "name": "Stillness 香氛精油",
                "sku": "XUANOR-SPU-001",
                "subtitle": "Quiet Scent",
                "short_description": "以沉静木质与微弱花香构成的日常仪式香气。",
                "description": "Stillness 适合用于工作、冥想与收束时刻。香气不直接宣告存在，而是在空间中留下轻微却持续的感知。",
                "specification": "容量：50ml\n香调：木质 / 微花香 / 琥珀",
                "usage_notes": "建议滴于扩香石、香薰炉或布面物件表层。避免直接接触眼部。",
                "seo_title": "Stillness 香氛精油 | XUANOR",
                "seo_description": "XUANOR Stillness 香氛精油，以沉静木质调带来日常仪式感。",
                "is_featured": True,
                "sort_order": 10,
                "features": [
                    ("安静入场", "前调克制，适合长时间共处。"),
                    ("空间留白", "不覆盖环境，而是与空间慢慢融合。"),
                ],
                "images": [
                    ("stillness-main", ProductImage.ImageType.PRIMARY),
                    ("stillness-gallery-1", ProductImage.ImageType.GALLERY),
                    ("stillness-detail-1", ProductImage.ImageType.DETAIL),
                ],
                "variants": [
                    {"sku": "XUANOR-SKU-001-A", "option_summary": "50ml / 白瓷瓶", "price": "299.00", "original_price": "329.00", "stock_quantity": 12, "safety_stock": 2, "sort_order": 10},
                    {"sku": "XUANOR-SKU-001-B", "option_summary": "100ml / 黑瓷瓶", "price": "459.00", "original_price": "499.00", "stock_quantity": 6, "safety_stock": 2, "sort_order": 20},
                ],
            },
            {
                "slug": "night-altar-candle",
                "name": "Night Altar 仪式蜡烛",
                "sku": "XUANOR-SPU-002",
                "subtitle": "Soft Flame",
                "short_description": "为夜间停顿时刻设计的柔光蜡烛。",
                "description": "Night Altar 用微弱火光重新划定夜晚的节奏，让空间在照明之外拥有更慢的层次。",
                "specification": "燃烧时长：42h\n材质：植物蜡 / 陶瓷杯",
                "usage_notes": "首次点燃建议保持 2 小时以上，以形成均匀蜡池。",
                "seo_title": "Night Altar 仪式蜡烛 | XUANOR",
                "seo_description": "适合夜晚静心时刻的 XUANOR 仪式蜡烛。",
                "is_featured": False,
                "sort_order": 20,
                "features": [
                    ("柔和火光", "适合卧室、书桌与安静会客区。"),
                ],
                "images": [
                    ("night-altar-main", ProductImage.ImageType.PRIMARY),
                    ("night-altar-gallery-1", ProductImage.ImageType.GALLERY),
                ],
                "variants": [
                    {"sku": "XUANOR-SKU-002-A", "option_summary": "标准款 / 180g", "price": "219.00", "original_price": "249.00", "stock_quantity": 18, "safety_stock": 3, "sort_order": 10},
                ],
            },
        ],
    },
    {
        "category": {"slug": "ritual-object", "name": "空间器物", "description": "为现代居住场景准备的安静器物。"},
        "products": [
            {
                "slug": "trace-stone-diffuser",
                "name": "Trace 扩香石",
                "sku": "XUANOR-SPU-003",
                "subtitle": "Quiet Object",
                "short_description": "用于承接香气与时间痕迹的桌面器物。",
                "description": "Trace 以简洁体量容纳气味、停顿与手感，让日常桌面拥有可感知的静默中心。",
                "specification": "材质：矿物复合石\n尺寸：8cm x 8cm",
                "usage_notes": "每次滴入 3-5 滴香氛精油，待香气自然扩散。",
                "seo_title": "Trace 扩香石 | XUANOR",
                "seo_description": "适配居家与办公场景的 XUANOR 扩香石。",
                "is_featured": True,
                "sort_order": 30,
                "features": [
                    ("低干预", "不依赖电力或复杂装置。"),
                    ("适配多场景", "桌面、床头、玄关都可使用。"),
                ],
                "images": [
                    ("trace-main", ProductImage.ImageType.PRIMARY),
                    ("trace-gallery-1", ProductImage.ImageType.GALLERY),
                ],
                "variants": [
                    {"sku": "XUANOR-SKU-003-A", "option_summary": "米白 / 单枚", "price": "139.00", "original_price": "159.00", "stock_quantity": 24, "safety_stock": 4, "sort_order": 10},
                    {"sku": "XUANOR-SKU-003-B", "option_summary": "炭黑 / 单枚", "price": "139.00", "original_price": "159.00", "stock_quantity": 9, "safety_stock": 2, "sort_order": 20},
                ],
            }
        ],
    },
]


class Command(BaseCommand):
    help = "Seed idempotent demo product data for XUANOR storefront previews."

    def handle(self, *args, **options):
        category_count = 0
        product_count = 0
        variant_count = 0
        image_count = 0

        for category_payload in CATALOG:
            category_defaults = {
                "name": category_payload["category"]["name"],
                "description": category_payload["category"]["description"],
                "is_active": True,
            }
            category, created = Category.objects.update_or_create(
                slug=category_payload["category"]["slug"],
                defaults=category_defaults,
            )
            category_count += int(created)

            for product_payload in category_payload["products"]:
                product_defaults = {
                    "name": product_payload["name"],
                    "sku": product_payload["sku"],
                    "category": category,
                    "subtitle": product_payload["subtitle"],
                    "short_description": product_payload["short_description"],
                    "description": product_payload["description"],
                    "specification": product_payload["specification"],
                    "usage_notes": product_payload["usage_notes"],
                    "seo_title": product_payload["seo_title"],
                    "seo_description": product_payload["seo_description"],
                    "currency": Product.Currency.CNY,
                    "is_featured": product_payload["is_featured"],
                    "is_active": True,
                    "sort_order": product_payload["sort_order"],
                }
                product, created = Product.objects.update_or_create(
                    slug=product_payload["slug"],
                    defaults=product_defaults,
                )
                product_count += int(created)

                self._ensure_placeholder_image(product, field_name="hero_image", file_stub=f"{product.slug}-hero")

                ProductFeature.objects.filter(product=product).exclude(title__in=[title for title, _description in product_payload["features"]]).delete()
                for index, (title, description) in enumerate(product_payload["features"], start=1):
                    ProductFeature.objects.update_or_create(
                        product=product,
                        title=title,
                        defaults={"description": description, "sort_order": index * 10},
                    )

                keep_image_keys = []
                for index, (stub, image_type) in enumerate(product_payload["images"], start=1):
                    alt_text = f"{product.name} {index}"
                    image, created = ProductImage.objects.get_or_create(
                        product=product,
                        alt_text=alt_text,
                        defaults={"image_type": image_type, "sort_order": index * 10},
                    )
                    image.image_type = image_type
                    image.sort_order = index * 10
                    self._ensure_placeholder_image(image, field_name="image", file_stub=stub)
                    image.save(update_fields=["image_type", "sort_order", "updated_at"])
                    keep_image_keys.append(alt_text)
                    image_count += int(created)
                ProductImage.objects.filter(product=product).exclude(alt_text__in=keep_image_keys).delete()

                keep_variant_skus = []
                for variant_payload in product_payload["variants"]:
                    variant, created = ProductVariant.objects.update_or_create(
                        sku=variant_payload["sku"],
                        defaults={
                            "product": product,
                            "option_summary": variant_payload["option_summary"],
                            "price": variant_payload["price"],
                            "original_price": variant_payload["original_price"],
                            "stock_quantity": variant_payload["stock_quantity"],
                            "safety_stock": variant_payload["safety_stock"],
                            "is_active": True,
                            "sort_order": variant_payload["sort_order"],
                        },
                    )
                    keep_variant_skus.append(variant.sku)
                    variant_count += int(created)
                ProductVariant.objects.filter(product=product).exclude(sku__in=keep_variant_skus).delete()
                product.refresh_commerce_fields_from_variants()

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo catalog ready: {category_count} new categories, {product_count} new products, {variant_count} new variants, {image_count} new gallery images."
            )
        )

    def _ensure_placeholder_image(self, instance, *, field_name, file_stub):
        image_field = getattr(instance, field_name)
        if image_field:
            return
        image_field.save(f"{file_stub}.png", ContentFile(PNG_PLACEHOLDER), save=True)
