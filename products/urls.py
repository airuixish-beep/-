from django.urls import path

from .views import product_detail, product_list

app_name = "products"

urlpatterns = [
    path("", product_list, name="list"),
    path("<slug:slug>/", product_detail, name="detail"),
]
