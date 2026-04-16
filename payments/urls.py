from django.urls import path

from .views import cancel, stripe_webhook, success

app_name = "payments"

urlpatterns = [
    path("success/<uuid:public_token>/", success, name="success"),
    path("cancel/<uuid:public_token>/", cancel, name="cancel"),
    path("webhooks/stripe/", stripe_webhook, name="stripe_webhook"),
]
