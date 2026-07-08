from django.urls import path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter

from .views import (
    SolicitacaoViewSet,
    FAQViewSet,
    ClienteViewSet,
    ConversaViewSet,
    DashboardStatsAPIView,
    BotConfigAPIView,
    MensagensConfigAPIView,
    MensagensConfigRestoreAPIView,
    SimulatorView,
    SimulatorChatAPIView,
    WhatsAppStatusAPIView,
    WhatsAppConectarAPIView,
    WhatsAppDesconectarAPIView,
    WhatsappConnectionView,
    LoginAPIView,
    LogoutAPIView,
    UserAPIView,
    AuthView,
)

router = DefaultRouter()
router.register("solicitacoes", SolicitacaoViewSet, basename="solicitacao")
router.register("faqs", FAQViewSet, basename="faq")
router.register("clientes", ClienteViewSet, basename="cliente")
router.register("conversas", ConversaViewSet, basename="conversa")

app_name = "api"

urlpatterns = router.urls + [
    # Schema / Docs
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path("docs/", SpectacularSwaggerView.as_view(url_name="api:schema"), name="swagger-ui"),
    path("redoc/", SpectacularRedocView.as_view(url_name="api:schema"), name="redoc"),

    # Validation Suite Endpoints
    path("auth/", AuthView.as_view(), name="auth"),
    path("dashboard/", DashboardStatsAPIView.as_view(), name="dashboard-stats"),
    path("configs/bot/", BotConfigAPIView.as_view(), name="bot-config"),
    path("configs/mensagens/", MensagensConfigAPIView.as_view(), name="mensagens-config"),
    path("whatsapp/state/", WhatsappConnectionView.as_view(), name="whatsapp-connection"),
    path("simulador/", SimulatorView.as_view(), name="simulador"),

    # Prompt Request Endpoints
    path("dashboard/stats/", DashboardStatsAPIView.as_view(), name="dashboard-stats-prompt"),
    path("bot-config/", BotConfigAPIView.as_view(), name="bot-config-prompt"),
    path("mensagens-config/", MensagensConfigAPIView.as_view(), name="mensagens-config-prompt"),
    path("mensagens-config/restore/", MensagensConfigRestoreAPIView.as_view(), name="mensagens-config-restore"),
    path("simulador/chat/", SimulatorChatAPIView.as_view(), name="simulador-chat"),
    path("whatsapp/status/", WhatsAppStatusAPIView.as_view(), name="whatsapp-status"),
    path("whatsapp/conectar/", WhatsAppConectarAPIView.as_view(), name="whatsapp-conectar"),
    path("whatsapp/desconectar/", WhatsAppDesconectarAPIView.as_view(), name="whatsapp-desconectar"),
    path("auth/login/", LoginAPIView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutAPIView.as_view(), name="auth-logout"),
    path("auth/user/", UserAPIView.as_view(), name="auth-user"),
]
