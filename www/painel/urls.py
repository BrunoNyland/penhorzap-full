from django.urls import path

from . import views

app_name = "painel"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    path("mensagens/", views.mensagens_config, name="mensagens_config"),
    path("bot/", views.bot_config, name="bot_config"),

    path("faqs/", views.faq_list, name="faq_list"),
    path("faqs/novo/", views.faq_create, name="faq_create"),
    path("faqs/<int:pk>/editar/", views.faq_update, name="faq_update"),
    path("faqs/<int:pk>/excluir/", views.faq_delete, name="faq_delete"),
    path("faqs/<int:pk>/toggle/", views.faq_toggle_ativo, name="faq_toggle"),

    path("clientes/", views.cliente_list, name="cliente_list"),
    path("clientes/<str:cpf>/", views.cliente_detail, name="cliente_detail"),
    path("clientes/<str:cpf>/toggle-bloqueio/", views.cliente_toggle_bloqueio, name="cliente_toggle_bloqueio"),

    path("atendimentos/", views.atendimento_list, name="atendimento_list"),
    path("atendimentos/<int:pk>/", views.atendimento_detail, name="atendimento_detail"),

    path("simulador/", views.simulador_chat, name="simulador_chat"),
]
