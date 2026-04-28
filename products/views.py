from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render

from .models import Category, Product, ProductImage, ProductVariant
from .services import get_recommended_products


def product_list(request):
    selected_category_slug = (request.GET.get("category") or "").strip()
    selected_featured = request.GET.get("featured") == "1"
    selected_available = request.GET.get("available") == "1"

    categories = list(
        Category.objects.filter(is_active=True, parent__isnull=True).order_by("sort_order", "id")
    )
    products = Product.objects.filter(is_active=True).select_related("category")

    if selected_category_slug:
        products = products.filter(category__slug=selected_category_slug)
    if selected_featured:
        products = products.filter(is_featured=True)
    if selected_available:
        products = products.filter(is_purchasable=True, stock_quantity__gt=0)

    has_filters = bool(selected_category_slug or selected_featured or selected_available)
    recommended_products = [] if has_filters else get_recommended_products(limit=3)
    selected_category = next((category for category in categories if category.slug == selected_category_slug), None)

    return render(
        request,
        "products/product_list.html",
        {
            "products": products,
            "recommended_products": recommended_products,
            "categories": categories,
            "selected_category": selected_category,
            "selected_category_slug": selected_category_slug,
            "selected_featured": selected_featured,
            "selected_available": selected_available,
            "has_filters": has_filters,
        },
    )


def product_detail(request, slug):
    product_queryset = Product.objects.select_related("category").prefetch_related(
        "features",
        Prefetch("images", queryset=ProductImage.objects.order_by("sort_order", "id")),
        Prefetch("variants", queryset=ProductVariant.objects.order_by("sort_order", "id")),
    )
    product = get_object_or_404(product_queryset, slug=slug, is_active=True)
    recommended_products = get_recommended_products(exclude_product=product, limit=4)
    return render(request, "products/product_detail.html", {"product": product, "recommended_products": recommended_products})
