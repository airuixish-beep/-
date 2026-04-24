from django.db import models
from django.db.models import Min, Sum
from django.urls import reverse


class Category(models.Model):
    name = models.CharField("类目名称", max_length=120)
    slug = models.SlugField("访问标识", unique=True)
    parent = models.ForeignKey(
        "self",
        verbose_name="父类目",
        on_delete=models.CASCADE,
        related_name="children",
        blank=True,
        null=True,
    )
    description = models.TextField("类目描述", blank=True)
    cover_image = models.ImageField("封面图", upload_to="categories/", blank=True, null=True)
    sort_order = models.PositiveIntegerField("排序值", default=0)
    is_active = models.BooleanField("是否启用", default=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "商品类目"
        verbose_name_plural = "商品类目"

    def __str__(self):
        return self.name if not self.parent else f"{self.parent.name} / {self.name}"


class Product(models.Model):
    class Currency(models.TextChoices):
        USD = "USD", "美元"
        CNY = "CNY", "人民币"
        EUR = "EUR", "欧元"

    name = models.CharField("商品名称", max_length=150)
    slug = models.SlugField("访问标识", unique=True)
    sku = models.CharField("商品编码（SPU）", max_length=64, unique=True, blank=True, null=True)
    category = models.ForeignKey(
        Category,
        verbose_name="所属类目",
        on_delete=models.SET_NULL,
        related_name="products",
        blank=True,
        null=True,
    )
    subtitle = models.CharField("副标题", max_length=200, blank=True)
    short_description = models.CharField("短描述", max_length=255, blank=True)
    description = models.TextField("详细描述", blank=True)
    specification = models.TextField("参数说明", blank=True)
    usage_notes = models.TextField("使用说明", blank=True)
    seo_title = models.CharField("SEO 标题", max_length=150, blank=True)
    seo_description = models.CharField("SEO 描述", max_length=255, blank=True)
    hero_image = models.ImageField("主图", upload_to="products/", blank=True, null=True)
    price = models.DecimalField("售价", max_digits=10, decimal_places=2, blank=True, null=True)
    currency = models.CharField("币种", max_length=3, choices=Currency.choices, default=Currency.USD)
    stock_quantity = models.PositiveIntegerField("库存数量", default=0)
    is_featured = models.BooleanField("是否精选", default=False)
    is_active = models.BooleanField("是否上架", default=True)
    is_purchasable = models.BooleanField("是否可购买", default=False)
    sort_order = models.PositiveIntegerField("排序值", default=0)
    weight = models.DecimalField("重量", max_digits=8, decimal_places=2, blank=True, null=True)
    length = models.DecimalField("长度", max_digits=8, decimal_places=2, blank=True, null=True)
    width = models.DecimalField("宽度", max_digits=8, decimal_places=2, blank=True, null=True)
    height = models.DecimalField("高度", max_digits=8, decimal_places=2, blank=True, null=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["sort_order", "-created_at"]
        verbose_name = "商品"
        verbose_name_plural = "商品"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("products:detail", kwargs={"slug": self.slug})

    @property
    def in_stock(self):
        return self.stock_quantity > 0

    @property
    def can_purchase(self):
        return self.is_active and self.is_purchasable and self.price is not None and self.in_stock

    @property
    def primary_image(self):
        if self.hero_image:
            return self.hero_image
        for image in self.ordered_images:
            if image.image:
                return image.image
        return None

    @property
    def ordered_images(self):
        if hasattr(self, "_prefetched_objects_cache") and "images" in self._prefetched_objects_cache:
            images = sorted(self._prefetched_objects_cache["images"], key=lambda image: (image.sort_order, image.id))
        else:
            images = list(self.images.order_by("sort_order", "id"))
        return [image for image in images if image.image]

    @property
    def active_variants(self):
        if hasattr(self, "_prefetched_objects_cache") and "variants" in self._prefetched_objects_cache:
            return [variant for variant in self._prefetched_objects_cache["variants"] if variant.is_active]
        return list(self.variants.filter(is_active=True).order_by("sort_order", "id"))

    @property
    def display_sku(self):
        variants = self.active_variants
        if self.sku:
            return self.sku
        if len(variants) == 1:
            return variants[0].sku
        return ""

    @property
    def price_range(self):
        prices = [variant.price for variant in self.active_variants if variant.price is not None]
        if not prices:
            return (self.price, self.price) if self.price is not None else (None, None)
        return min(prices), max(prices)

    @property
    def has_variant_price_range(self):
        min_price, max_price = self.price_range
        return min_price is not None and max_price is not None and min_price != max_price

    @property
    def display_price(self):
        min_price, _max_price = self.price_range
        return min_price

    @property
    def stock_status_label(self):
        if self.stock_quantity <= 0:
            return "暂时缺货"
        if self.stock_quantity <= 5:
            return "库存紧张"
        return "现货可购"

    def refresh_commerce_fields_from_variants(self, save=True):
        all_variants = self.variants.all()
        if not all_variants.exists():
            return

        active_variants = all_variants.filter(is_active=True)
        fields_to_update = []

        if active_variants.exists():
            aggregates = active_variants.aggregate(min_price=Min("price"), total_stock=Sum("stock_quantity"))
            min_price = aggregates["min_price"]
            total_stock = aggregates["total_stock"] or 0
            is_purchasable = active_variants.filter(price__isnull=False, stock_quantity__gt=0).exists()

            if min_price is not None and self.price != min_price:
                self.price = min_price
                fields_to_update.append("price")
            if self.stock_quantity != total_stock:
                self.stock_quantity = total_stock
                fields_to_update.append("stock_quantity")
            if self.is_purchasable != is_purchasable:
                self.is_purchasable = is_purchasable
                fields_to_update.append("is_purchasable")
        else:
            if self.stock_quantity != 0:
                self.stock_quantity = 0
                fields_to_update.append("stock_quantity")
            if self.is_purchasable:
                self.is_purchasable = False
                fields_to_update.append("is_purchasable")

        if save and fields_to_update:
            self.save(update_fields=[*fields_to_update, "updated_at"])


class ProductFeature(models.Model):
    product = models.ForeignKey(Product, verbose_name="所属商品", on_delete=models.CASCADE, related_name="features")
    title = models.CharField("卖点标题", max_length=100)
    description = models.CharField("卖点说明", max_length=255, blank=True)
    sort_order = models.PositiveIntegerField("排序值", default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "商品卖点"
        verbose_name_plural = "商品卖点"

    def __str__(self):
        return f"{self.product.name} - {self.title}"


class ProductImage(models.Model):
    class ImageType(models.TextChoices):
        PRIMARY = "primary", "主图"
        GALLERY = "gallery", "轮播图"
        DETAIL = "detail", "详情图"

    product = models.ForeignKey(Product, verbose_name="所属商品", on_delete=models.CASCADE, related_name="images")
    image = models.ImageField("图片", upload_to="products/gallery/")
    image_type = models.CharField("图片类型", max_length=20, choices=ImageType.choices, default=ImageType.GALLERY)
    alt_text = models.CharField("替代文本", max_length=150, blank=True)
    sort_order = models.PositiveIntegerField("排序值", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "商品图片"
        verbose_name_plural = "商品图片"

    def __str__(self):
        return f"{self.product.name} - {self.get_image_type_display()}"


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, verbose_name="所属商品", on_delete=models.CASCADE, related_name="variants")
    sku = models.CharField("SKU 编码", max_length=64, unique=True)
    option_summary = models.CharField("规格组合", max_length=255)
    image = models.ImageField("SKU 图片", upload_to="products/variants/", blank=True, null=True)
    price = models.DecimalField("售价", max_digits=10, decimal_places=2, blank=True, null=True)
    original_price = models.DecimalField("划线价", max_digits=10, decimal_places=2, blank=True, null=True)
    cost_price = models.DecimalField("成本价", max_digits=10, decimal_places=2, blank=True, null=True)
    stock_quantity = models.PositiveIntegerField("库存数量", default=0)
    safety_stock = models.PositiveIntegerField("安全库存", default=0)
    is_active = models.BooleanField("是否启用", default=True)
    sort_order = models.PositiveIntegerField("排序值", default=0)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "商品 SKU"
        verbose_name_plural = "商品 SKU"

    def __str__(self):
        return f"{self.product.name} - {self.option_summary}"

    @property
    def in_stock(self):
        return self.stock_quantity > 0

    def save(self, *args, **kwargs):
        previous_stock = None
        is_new = self._state.adding
        if not is_new:
            previous_stock = type(self).objects.only("stock_quantity").get(pk=self.pk).stock_quantity

        super().save(*args, **kwargs)

        if is_new and self.stock_quantity > 0:
            InventoryRecord.objects.create(
                variant=self,
                change_type=InventoryRecord.ChangeType.INITIAL_STOCK,
                quantity_change=self.stock_quantity,
                before_quantity=0,
                after_quantity=self.stock_quantity,
                note="初始化 SKU 库存",
            )
        elif previous_stock is not None and previous_stock != self.stock_quantity:
            InventoryRecord.objects.create(
                variant=self,
                change_type=InventoryRecord.ChangeType.MANUAL_ADJUSTMENT,
                quantity_change=self.stock_quantity - previous_stock,
                before_quantity=previous_stock,
                after_quantity=self.stock_quantity,
                note="后台调整 SKU 库存",
            )

        self.product.refresh_commerce_fields_from_variants()

    def delete(self, *args, **kwargs):
        product = self.product
        super().delete(*args, **kwargs)
        product.refresh_commerce_fields_from_variants()


class InventoryRecord(models.Model):
    class ChangeType(models.TextChoices):
        INITIAL_STOCK = "initial_stock", "初始化库存"
        MANUAL_ADJUSTMENT = "manual_adjustment", "人工调整"
        ORDER_DEDUCTION = "order_deduction", "订单扣减"
        ORDER_RESTOCK = "order_restock", "退款回补"

    variant = models.ForeignKey(
        ProductVariant,
        verbose_name="关联 SKU",
        on_delete=models.CASCADE,
        related_name="inventory_records",
    )
    change_type = models.CharField("变动类型", max_length=30, choices=ChangeType.choices)
    quantity_change = models.IntegerField("变动数量")
    before_quantity = models.PositiveIntegerField("变动前库存")
    after_quantity = models.PositiveIntegerField("变动后库存")
    note = models.CharField("备注", max_length=255, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "库存流水"
        verbose_name_plural = "库存流水"

    def __str__(self):
        return f"{self.variant.sku} - {self.get_change_type_display()}"
