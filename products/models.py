from django.db import models
from django.urls import reverse


class Product(models.Model):
    class Currency(models.TextChoices):
        USD = "USD", "美元"
        CNY = "CNY", "人民币"
        EUR = "EUR", "欧元"

    name = models.CharField("商品名称", max_length=150)
    slug = models.SlugField("访问标识", unique=True)
    sku = models.CharField("商品编码", max_length=64, unique=True, blank=True, null=True)
    subtitle = models.CharField("副标题", max_length=200, blank=True)
    short_description = models.CharField("短描述", max_length=255, blank=True)
    description = models.TextField("详细描述", blank=True)
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
