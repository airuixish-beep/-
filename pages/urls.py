from django.urls import path

from .views import about, chat, home, upload_test

app_name = "pages"

urlpatterns = [
    path("", home, name="home"),
    path("about/", about, name="about"),
    path("chat/", chat, name="chat"),
    path("upload-test/", upload_test, name="upload_test"),
]
