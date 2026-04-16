from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt

from orders.models import Order

from .models import Payment
from .services import PayPalService, StripeService


def success(request, public_token):
    order = get_object_or_404(Order.objects.prefetch_related("payments", "shipments"), public_token=public_token)
    payment = order.payments.first()
    capture_error = ""

    if payment and payment.provider == Payment.Provider.PAYPAL and payment.status != Payment.Status.PAID:
        token = request.GET.get("token", "")
        if token and token == payment.checkout_token_or_session_id:
            try:
                PayPalService.capture_order(payment)
                order.refresh_from_db()
                payment.refresh_from_db()
            except Exception:
                capture_error = "PayPal 支付回写失败，请稍后刷新订单页面或联系管理员。"

    return render(request, "payments/success.html", {"order": order, "payment": payment, "capture_error": capture_error})


def cancel(request, public_token):
    order = get_object_or_404(Order.objects.prefetch_related("payments"), public_token=public_token)
    payment = order.payments.first()
    if payment and payment.status == Payment.Status.REQUIRES_ACTION:
        payment.status = Payment.Status.CANCELLED
        payment.save(update_fields=["status", "updated_at"])
        order.status = Order.Status.CANCELLED
        order.payment_status = Order.PaymentStatus.CANCELLED
        order.save(update_fields=["status", "payment_status", "updated_at"])
    return render(request, "payments/cancel.html", {"order": order, "payment": payment})


@csrf_exempt
def stripe_webhook(request):
    signature = request.headers.get("Stripe-Signature", "")
    try:
        payment_event, created = StripeService.handle_webhook(request.body, signature)
    except Exception as exc:
        return HttpResponseBadRequest(str(exc))
    return JsonResponse({"ok": True, "created": created, "event_id": payment_event.event_id})
