from django.urls import path

from . import views

app_name = "configuracion"

urlpatterns = [
    path("", views.configuracion, name="empresa"),
    path("logo/", views.logo, name="logo"),
]
