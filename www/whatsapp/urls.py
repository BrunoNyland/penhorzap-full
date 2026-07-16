from django.urls import path

from . import views

app_name = "whatsapp"

urlpatterns = [
    path("webhook/whatsapp/", views.whatsapp_webhook, name="webhook"),
]
