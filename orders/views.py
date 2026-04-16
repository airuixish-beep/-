from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from payments.models import Payment
from payments.services import create_payment_redirect
from products.models import Product

from .forms import CheckoutForm
from .models import Order, OrderItem


def checkout(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    form = CheckoutForm(request.POST or None, product=product)

    if request.method == "POST" and form.is_valid():
        order = Order.objects.create(
            customer_name=form.cleaned_data["customer_name"],
            customer_email=form.cleaned_data["customer_email"],
            customer_phone=form.cleaned_data["customer_phone"],
            shipping_country=form.cleaned_data["shipping_country"].upper(),
            shipping_state=form.cleaned_data["shipping_state"],
            shipping_city=form.cleaned_data["shipping_city"],
            shipping_postal_code=form.cleaned_data["shipping_postal_code"],
            shipping_address_line1=form.cleaned_data["shipping_address_line1"],
            shipping_address_line2=form.cleaned_data["shipping_address_line2"],
            shipping_amount=form.shipping_amount(),
            currency=product.currency,
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            product_name_snapshot=product.name,
            sku_snapshot=product.sku or "",
            unit_price=product.price or 0,
            quantity=form.cleaned_data["quantity"],
        )
        order.recalculate_totals()
        payment = Payment.objects.create(
            order=order,
            provider=form.cleaned_data["payment_provider"],
            amount=order.total_amount,
            currency=order.currency,
        )
        try:
            redirect_url = create_payment_redirect(payment, request)
        except Exception:
            payment.status = Payment.Status.FAILED
            payment.save(update_fields=["status", "updated_at"])
            form.add_error(None, "支付初始化失败，请稍后重试。")
        else:
            return redirect(redirect_url)

    context = {
        "product": product,
        "form": form,
        "shipping_amount": form.shipping_amount(),
        "default_currency": settings.DEFAULT_CURRENCY,
    }
    return render(request, "orders/checkout.html", context)


def order_lookup(request):
    if request.method == "POST":
        order_number = request.POST.get("order_number", "").strip()
        customer_email = request.POST.get("customer_email", "").strip()
        order = Order.objects.filter(order_number=order_number, customer_email__iexact=customer_email).first()
        if order:
            return redirect("orders:detail", public_token=order.public_token)
        messages.error(request, "未找到匹配订单，请检查订单号和邮箱。")
    return render(request, "orders/order_lookup.html")


def order_detail(request, public_token):
    order = get_object_or_404(Order.objects.prefetch_related("items__product", "payments", "shipments__events"), public_token=public_token)
    return render(request, "orders/order_detail.html", {"order": order, "latest_payment": order.payments.first(), "latest_shipment": order.shipments.first()})
