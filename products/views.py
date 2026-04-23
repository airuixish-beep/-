from django.shortcuts import get_object_or_404, render

from .models import Product
from .services import get_recommended_products


def product_list(request):
    products = Product.objects.filter(is_active=True)
    recommended_products = get_recommended_products(limit=3)
    return render(request, "products/product_list.html", {"products": products, "recommended_products": recommended_products})


def product_detail(request, slug):
    product = get_object_or_404(Product.objects.prefetch_related("features"), slug=slug, is_active=True)
    recommended_products = get_recommended_products(exclude_product=product, limit=4)
    return render(request, "products/product_detail.html", {"product": product, "recommended_products": recommended_products})
