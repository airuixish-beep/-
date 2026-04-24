from django.core.files.storage import default_storage
from django.shortcuts import render

from products.models import Product
from products.services import get_recommended_products


def home(request):
    recommended_products = get_recommended_products(limit=4)
    return render(request, "pages/home.html", {"recommended_products": recommended_products})


def about(request):
    return render(request, "pages/about.html")


def contact(request):
    return render(request, "pages/contact.html")


def refund_policy(request):
    return render(request, "pages/refund_policy.html")


def shipping_policy(request):
    return render(request, "pages/shipping_policy.html")


def privacy_policy(request):
    return render(request, "pages/privacy_policy.html")


def terms_of_service(request):
    return render(request, "pages/terms_of_service.html")


def chat(request):
    consultation_product = Product.objects.filter(is_active=True, hero_image__isnull=False).order_by("sort_order", "-created_at").first()
    return render(
        request,
        "pages/chat.html",
        {
            "hide_support_chat_widget": True,
            "consultation_product": consultation_product,
            "prefill_name": (request.GET.get("name") or "").strip(),
            "prefill_email": (request.GET.get("email") or "").strip(),
            "prefill_order_no": (request.GET.get("order_no") or "").strip(),
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
