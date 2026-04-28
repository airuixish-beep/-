from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt

from orders.models import Order

from .models import Payment
from transactions.services import cancel_payment_attempt, mark_payment_failed

from .services import (
    PayPalService,
    PaymentWebhookProcessingError,
    PaymentWebhookValidationError,
    StripeService,
)


def _mark_failed_payment(order, payment):
    mark_payment_failed(
        payment,
        source="payments.success",
        idempotency_key=f"success-failed:{payment.id}",
        payload={"order_id": order.id},
    )


def _get_payment_attempt(order, request):
    attempt = (request.GET.get("attempt") or "").strip()
    token = (request.GET.get("session_id") or request.GET.get("token") or "").strip()
    queryset = order.payments.order_by("-created_at", "-id")

    if attempt:
        payment = queryset.filter(pk=attempt).first()
        if payment is not None:
            if token and payment.checkout_token_or_session_id != token:
                return None
            return payment

    if token:
        return queryset.filter(checkout_token_or_session_id=token).first()
    return None



def success(request, public_token):
    order = get_object_or_404(Order, public_token=public_token)
    payment = _get_payment_attempt(order, request)
    capture_error = ""
    awaiting_confirmation = False

    if payment and payment.provider == Payment.Provider.PAYPAL and payment.status != Payment.Status.PAID:
        try:
            PayPalService.capture_order(payment)
            order.refresh_from_db()
            payment.refresh_from_db()
        except Exception:
            _mark_failed_payment(order, payment)
            order.refresh_from_db()
            payment.refresh_from_db()
            capture_error = "PayPal 支付回写失败，请稍后重试。"
    elif payment and payment.provider == Payment.Provider.STRIPE and payment.status != Payment.Status.PAID:
        awaiting_confirmation = True

    return render(
        request,
        "payments/success.html",
        {
            "order": order,
            "payment": payment,
            "capture_error": capture_error,
            "awaiting_confirmation": awaiting_confirmation,
        },
    )



def cancel(request, public_token):
    order = get_object_or_404(Order, public_token=public_token)
    payment = _get_payment_attempt(order, request)
    if payment and payment.status == Payment.Status.REQUIRES_ACTION:
        cancel_payment_attempt(
            payment,
            source="payments.cancel",
            idempotency_key=f"cancel:{payment.id}",
            payload={"order_id": order.id},
        )
    return render(request, "payments/cancel.html", {"order": order, "payment": payment})



@csrf_exempt
def stripe_webhook(request):
    signature = request.headers.get("Stripe-Signature", "")
    try:
        payment_event, created = StripeService.handle_webhook(request.body, signature)
    except PaymentWebhookValidationError:
        return HttpResponseBadRequest("invalid webhook")
    except PaymentWebhookProcessingError:
        return JsonResponse({"ok": False, "error": "webhook processing failed"}, status=500)
    return JsonResponse({"ok": True, "created": created, "event_id": payment_event.event_id})
