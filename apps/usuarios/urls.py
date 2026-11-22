from django.urls import path

from . import views

app_name = "usuarios"

urlpatterns = [
    path("rol/", views.cambiar_rol, name="cambiar_rol"),
]
