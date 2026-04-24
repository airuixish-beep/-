from django.urls import path

from .views import about, chat, contact, home, privacy_policy, refund_policy, shipping_policy, terms_of_service, upload_test

app_name = "pages"

urlpatterns = [
    path("", home, name="home"),
    path("about/", about, name="about"),
    path("contact/", contact, name="contact"),
    path("refund-policy/", refund_policy, name="refund_policy"),
    path("shipping-policy/", shipping_policy, name="shipping_policy"),
    path("privacy-policy/", privacy_policy, name="privacy_policy"),
    path("terms-of-service/", terms_of_service, name="terms_of_service"),
    path("chat/", chat, name="chat"),
    path("upload-test/", upload_test, name="upload_test"),
]
