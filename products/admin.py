from django.contrib import admin
from django.db.models import Count

from .models import Category, InventoryRecord, Product, ProductFeature, ProductImage, ProductVariant


class ProductFeatureInline(admin.TabularInline):
    model = ProductFeature
    extra = 0
    fields = ("title", "description", "sort_order")
    ordering = ("sort_order", "id")
    classes = ("collapse",)


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    fields = ("image", "image_type", "alt_text", "sort_order")
    ordering = ("sort_order", "id")
    show_change_link = True
    classes = ("collapse",)


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    fields = (
        "sku",
        "option_summary",
        "price",
        "original_price",
        "stock_quantity",
        "safety_stock",
        "is_active",
        "sort_order",
    )
    ordering = ("sort_order", "id")
    show_change_link = True


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent", "sort_order", "is_active", "slug", "updated_at")
    list_filter = ("is_active", "parent")
    list_editable = ("sort_order", "is_active")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    fieldsets = (
        ("基础信息", {"fields": ("name", "slug", "parent")}),
        ("展示内容", {"fields": ("description", "cover_image")}),
        ("显示设置", {"fields": ("sort_order", "is_active")}),
    )


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "display_sku",
        "category",
        "display_price_summary",
        "variant_count",
        "stock_quantity",
        "stock_status",
        "is_active",
        "is_purchasable",
        "is_featured",
        "sort_order",
        "updated_at",
    )
    list_filter = ("category", "currency", "is_active", "is_purchasable", "is_featured", "updated_at")
    list_editable = ("is_active", "is_purchasable", "is_featured", "sort_order")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "sku", "subtitle", "short_description", "slug", "variants__sku")
    readonly_fields = ("display_sku", "display_price_summary", "stock_status", "created_at", "updated_at")
    autocomplete_fields = ("category",)
    inlines = [ProductFeatureInline, ProductImageInline, ProductVariantInline]
    actions = ["mark_as_published", "mark_as_unpublished", "mark_as_purchasable", "mark_as_not_purchasable"]
    fieldsets = (
        (
            "商品识别",
            {
                "fields": (
                    "name",
                    "slug",
                    "sku",
                    "display_sku",
                    "category",
                    "subtitle",
                    "short_description",
                )
            },
        ),
        ("内容与展示", {"fields": ("description", "specification", "usage_notes", "hero_image")}),
        (
            "销售指挥",
            {
                "fields": (
                    "display_price_summary",
                    "price",
                    "currency",
                    "stock_quantity",
                    "stock_status",
                    "is_purchasable",
                    "is_active",
                    "is_featured",
                    "sort_order",
                )
            },
        ),
        ("SEO", {"classes": ("collapse",), "fields": ("seo_title", "seo_description")}),
        ("物流尺寸", {"classes": ("collapse",), "fields": ("weight", "length", "width", "height")}),
        ("时间与审计", {"classes": ("collapse",), "fields": ("created_at", "updated_at")}),
    )
    list_select_related = ("category",)
    date_hierarchy = "updated_at"
    save_on_top = True

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.annotate(variant_total=Count("variants", distinct=True))

    def changelist_view(self, request, extra_context=None):
        return super().changelist_view(
            request,
            extra_context={
                **(extra_context or {}),
                "title": "Products",
                "subtitle": "维护商品资料、上下架状态、库存与商品结构。",
            },
        )

    def add_view(self, request, form_url="", extra_context=None):
        return super().add_view(
            request,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "新增商品",
                "subtitle": "创建商品主档、价格、库存与展示信息。",
            },
        )

    def change_view(self, request, object_id, form_url="", extra_context=None):
        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context={
                **(extra_context or {}),
                "title": "编辑商品",
                "subtitle": "维护商品详情、价格、库存、图片和变体信息。",
            },
        )

    @admin.display(description="商品编码")
    def display_sku(self, obj):
        if not obj or not getattr(obj, "pk", None):
            return "-"
        return obj.display_sku or "-"

    @admin.display(description="售价")
    def display_price_summary(self, obj):
        if not obj:
            return "-"
        min_price, max_price = obj.price_range
        if min_price is None:
            return "-"
        if max_price is not None and min_price != max_price:
            return f"{obj.currency} {min_price} - {max_price}"
        return f"{obj.currency} {min_price}"

    @admin.display(description="库存状态")
    def stock_status(self, obj):
        if not obj:
            return "-"
        return obj.stock_status_label

    @admin.display(description="SKU 数")
    def variant_count(self, obj):
        return getattr(obj, "variant_total", 0)

    @admin.action(description="批量上架")
    def mark_as_published(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="批量下架")
    def mark_as_unpublished(self, request, queryset):
        queryset.update(is_active=False)

    @admin.action(description="批量设为可购买")
    def mark_as_purchasable(self, request, queryset):
        queryset.update(is_purchasable=True)

    @admin.action(description="批量设为不可购买")
    def mark_as_not_purchasable(self, request, queryset):
        queryset.update(is_purchasable=False)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        form.instance.refresh_commerce_fields_from_variants()


@admin.register(ProductVariant)
class ProductVariantAdmin(admin.ModelAdmin):
    list_display = (
        "sku",
        "product",
        "option_summary",
        "price",
        "original_price",
        "stock_quantity",
        "safety_stock",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "product__category")
    search_fields = ("sku", "product__name", "product__sku", "option_summary")
    list_editable = ("price", "original_price", "stock_quantity", "safety_stock", "is_active")
    ordering = ("product", "sort_order", "id")


@admin.register(InventoryRecord)
class InventoryRecordAdmin(admin.ModelAdmin):
    list_display = (
        "variant",
        "product_name",
        "change_type",
        "quantity_change",
        "before_quantity",
        "after_quantity",
        "created_at",
    )
    list_filter = ("change_type", "created_at", "variant__product__category")
    search_fields = ("variant__sku", "variant__product__name", "note")
    readonly_fields = (
        "variant",
        "change_type",
        "quantity_change",
        "before_quantity",
        "after_quantity",
        "note",
        "created_at",
    )

    @admin.display(description="商品")
    def product_name(self, obj):
        return obj.variant.product.name

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
