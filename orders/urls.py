from django.urls import path

from .views import checkout, order_detail, order_lookup

app_name = "orders"

urlpatterns = [
    path("lookup/", order_lookup, name="lookup"),
    path("checkout/<slug:slug>/", checkout, name="checkout"),
    path("<uuid:public_token>/", order_detail, name="detail"),
]
