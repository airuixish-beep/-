from django.core.files.storage import default_storage
from django.shortcuts import render

from products.models import Product
from products.services import get_recommended_products


def home(request):
    recommended_products = get_recommended_products(limit=4)
    return render(request, "pages/home.html", {"recommended_products": recommended_products})


def about(request):
    return render(request, "pages/about.html")


def chat(request):
    consultation_product = Product.objects.filter(is_active=True, hero_image__isnull=False).order_by("sort_order", "-created_at").first()
    return render(
        request,
        "pages/chat.html",
        {
            "hide_support_chat_widget": True,
            "consultation_product": consultation_product,
        },
    )


def upload_test(request):
    upload_result = None

    if request.method == "POST" and request.FILES.get("test_file"):
        uploaded_file = request.FILES["test_file"]
        saved_path = default_storage.save(f"uploads/{uploaded_file.name}", uploaded_file)
        upload_result = {
            "name": uploaded_file.name,
            "path": saved_path,
            "url": default_storage.url(saved_path),
            "size": uploaded_file.size,
            "content_type": uploaded_file.content_type,
        }

    return render(request, "pages/upload_test.html", {"upload_result": upload_result})
