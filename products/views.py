from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, render

from .models import Product, ProductImage, ProductVariant
from .services import get_recommended_products


def product_list(request):
    products = Product.objects.filter(is_active=True).select_related("category")
    recommended_products = get_recommended_products(limit=3)
    return render(request, "products/product_list.html", {"products": products, "recommended_products": recommended_products})


def product_detail(request, slug):
    product_queryset = Product.objects.select_related("category").prefetch_related(
        "features",
        Prefetch("images", queryset=ProductImage.objects.order_by("sort_order", "id")),
        Prefetch("variants", queryset=ProductVariant.objects.order_by("sort_order", "id")),
    )
    product = get_object_or_404(product_queryset, slug=slug, is_active=True)
    recommended_products = get_recommended_products(exclude_product=product, limit=4)
    return render(request, "products/product_detail.html", {"product": product, "recommended_products": recommended_products})
