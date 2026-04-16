from django.contrib import admin

from .models import Product, ProductFeature


class ProductFeatureInline(admin.TabularInline):
    model = ProductFeature
    extra = 1


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "sku",
        "price",
        "currency",
        "stock_quantity",
        "is_active",
        "is_purchasable",
        "is_featured",
        "sort_order",
        "updated_at",
    )
    list_filter = ("is_active", "is_purchasable", "is_featured", "currency")
    list_editable = ("price", "stock_quantity", "is_active", "is_purchasable", "is_featured", "sort_order")
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "sku", "subtitle", "short_description")
    inlines = [ProductFeatureInline]
    fieldsets = (
        ("基础信息", {"fields": ("name", "slug", "sku", "subtitle", "short_description", "description", "hero_image")}),
        ("销售设置", {"fields": ("price", "currency", "stock_quantity", "is_purchasable", "is_active", "is_featured", "sort_order")}),
        ("物流尺寸", {"fields": ("weight", "length", "width", "height")}),
    )
