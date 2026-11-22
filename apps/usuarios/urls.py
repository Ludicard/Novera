from django.urls import path

from . import views

app_name = "usuarios"

urlpatterns = [
    path("rol/", views.elegir_rol, name="elegir_rol"),
]
