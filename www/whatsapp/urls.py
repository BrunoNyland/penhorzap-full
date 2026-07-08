from django.urls import path

from . import views

app_name = "whatsapp"

urlpatterns = [
    path("webhook/whatsapp/", views.whatsapp_webhook, name="webhook"),
    path("painel/whatsapp-qr/", views.qrcode_view, name="qrcode"),
    path("painel/whatsapp-qr/toggle-bot/", views.toggle_bot, name="toggle_bot"),
]
