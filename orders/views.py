from decimal import Decimal

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from payments.models import Payment
from payments.services import PaymentGatewayError, create_payment_redirect
from products.models import Product

from .forms import CheckoutForm
from .models import Order, OrderItem


def _mark_payment_attempt_failed(order, payment):
    payment.status = Payment.Status.FAILED
    payment.save(update_fields=["status", "updated_at"])
    order.mark_payment_failed()



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
            unit_price=product.price or Decimal("0.00"),
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
            _mark_payment_attempt_failed(order, payment)
            form.add_error(None, "支付初始化失败，请稍后重试。")
        else:
            order.mark_payment_pending()
            return redirect(redirect_url)

    context = {
        "product": product,
        "form": form,
        "shipping_amount": form.shipping_amount(),
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


@require_POST
def retry_payment(request, public_token):
    order = get_object_or_404(Order, public_token=public_token)
    if not order.can_retry_payment:
        messages.error(request, "当前订单不支持重新支付。")
        return redirect("orders:detail", public_token=order.public_token)

    latest_payment = order.payments.order_by("-created_at", "-id").first()
    if latest_payment is None:
        messages.error(request, "当前订单暂无可重试的支付记录。")
        return redirect("orders:detail", public_token=order.public_token)

    payment = Payment.objects.create(
        order=order,
        provider=latest_payment.provider,
        amount=order.total_amount,
        currency=order.currency,
    )

    try:
        redirect_url = create_payment_redirect(payment, request)
    except (PaymentGatewayError, Exception):
        _mark_payment_attempt_failed(order, payment)
        messages.error(request, "重新发起支付失败，请稍后再试。")
        return redirect("orders:detail", public_token=order.public_token)

    order.mark_payment_pending()
    return redirect(redirect_url)


def order_detail(request, public_token):
    order = get_object_or_404(Order.objects.prefetch_related("items"), public_token=public_token)
    latest_payment = order.payments.order_by("-created_at", "-id").first()
    latest_shipment = order.shipments.order_by("-created_at", "-id").first()
    shipment_events = latest_shipment.events.all() if latest_shipment else []
    return render(
        request,
        "orders/order_detail.html",
        {
            "order": order,
            "latest_payment": latest_payment,
            "latest_shipment": latest_shipment,
            "shipment_events": shipment_events,
        },
    )
