from django.urls import path

from .views import about, home, upload_test

app_name = "pages"

urlpatterns = [
    path("", home, name="home"),
    path("about/", about, name="about"),
    path("upload-test/", upload_test, name="upload_test"),
]
