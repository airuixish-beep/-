from django.shortcuts import get_object_or_404, render

from .models import Product


def product_list(request):
    products = Product.objects.filter(is_active=True)
    return render(request, "products/product_list.html", {"products": products})


def product_detail(request, slug):
    product = get_object_or_404(Product.objects.prefetch_related("features"), slug=slug, is_active=True)
    return render(request, "products/product_detail.html", {"product": product})
