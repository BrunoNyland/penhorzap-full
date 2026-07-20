import json
import logging
import os
import tempfile
from datetime import timedelta

from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.functions import ExtractDay, ExtractWeekDay, TruncDate
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from django_q.tasks import async_task
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.authtoken.models import Token
from rest_framework.decorators import action
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import exception_handler

from core.models import (
    FAQ,
    SITUACOES_LIQUIDADAS_COD,
    Boleto,
    BotConfig,
    Cliente,
    Conversa,
    FAQResposta,
    FAQSugerida,
    ImportDataJob,
    Mensagem,
    MensagensConfig,
    Solicitacao,
)
from core.services import importar_sqlite_arquivo
from ia.services import extrair_intencao
from whatsapp.evolution_client import get_client

from .serializers import (
    BoletoSerializer,
    BotConfigSerializer,
    ClienteDetailSerializer,
    ClienteListSerializer,
    ConversaDetailSerializer,
    ConversaListSerializer,
    FAQSerializer,
    FAQSugeridaAprovarSerializer,
    FAQSugeridaSerializer,
    LoginSerializer,
    MensagemPainelSerializer,
    MensagensConfigSerializer,
    SolicitacaoSerializer,
    SolicitacaoUpdateSerializer,
    UserSerializer,
)

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None and response.status_code == 401:
        request = context.get("request")
        if request and (not request.user or not request.user.is_authenticated):
            response.status_code = 403
    return response


@method_decorator(ensure_csrf_cookie, name="dispatch")
class AuthView(GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = serializers.Serializer

    @extend_schema(
        request=inline_serializer(
            name="AuthLegacyRequest",
            fields={
                "action": serializers.CharField(required=False),
                "username": serializers.CharField(required=False),
                "password": serializers.CharField(required=False),
            },
        ),
        responses={
            200: inline_serializer(
                name="AuthLegacyResponse",
                fields={
                    "authenticated": serializers.BooleanField(),
                    "username": serializers.CharField(required=False),
                    "is_staff": serializers.BooleanField(required=False),
                },
            )
        },
    )
    def get(self, request):
        if request.user and request.user.is_authenticated:
            return Response(
                {
                    "authenticated": True,
                    "username": request.user.username,
                    "is_staff": request.user.is_staff,
                }
            )
        return Response({"authenticated": False})

    def post(self, request):
        action_param = request.data.get("action")
        if action_param == "login":
            username = request.data.get("username")
            password = request.data.get("password")
            user = authenticate(request, username=username, password=password)
            if user is not None:
                if not user.is_staff:
                    return Response(
                        {"detail": "Acesso restrito a administradores."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
                login(request, user)
                return Response(
                    {"authenticated": True, "username": user.username, "is_staff": user.is_staff}
                )
            return Response(
                {"detail": "Usuário ou senha incorretos."}, status=status.HTTP_401_UNAUTHORIZED
            )
        elif action_param == "logout":
            logout(request)
            return Response({"authenticated": False})
        else:
            return Response({"detail": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)


class LoginAPIView(GenericAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = LoginSerializer

    @extend_schema(
        request=LoginSerializer,
        responses={
            200: inline_serializer(
                name="LoginResponse",
                fields={
                    "token": serializers.CharField(),
                    "user": UserSerializer(),
                },
            )
        },
    )
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            token, _ = Token.objects.get_or_create(user=user)
            return Response({"token": token.key, "user": UserSerializer(user).data})
        else:
            return Response(
                {"detail": "Credenciais inválidas."}, status=status.HTTP_401_UNAUTHORIZED
            )


class LogoutAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="LogoutResponse", fields={"detail": serializers.CharField()}
            )
        },
    )
    def post(self, request):
        if request.auth:
            request.auth.delete()
        logout(request)
        return Response({"detail": "Logout efetuado com sucesso."})


class UserAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = UserSerializer

    @extend_schema(responses={200: UserSerializer})
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class DashboardStatsAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer

    @extend_schema(
        responses={
            200: inline_serializer(
                name="DashboardStatsResponse",
                fields={
                    "por_tipo": serializers.ListField(child=serializers.JSONField()),
                    "por_status": serializers.ListField(child=serializers.JSONField()),
                    "serie_30_dias": serializers.ListField(child=serializers.JSONField()),
                    "maior_valor_serie": serializers.IntegerField(),
                    "total_clientes": serializers.IntegerField(),
                    "clientes_com_telefone": serializers.IntegerField(),
                    "clientes_com_conversa": serializers.IntegerField(),
                    "clientes_bloqueados": serializers.IntegerField(),
                    "total_solicitacoes": serializers.IntegerField(),
                    "solicitacoes_precisa_humano": serializers.IntegerField(),
                    "taxa_solicitacoes_humano": serializers.FloatField(),
                    "total_conversas": serializers.IntegerField(),
                    "conversas_precisa_revisao": serializers.IntegerField(),
                    "taxa_conversas_revisao": serializers.FloatField(),
                    "total_boletos": serializers.IntegerField(),
                    "boletos_enviados": serializers.IntegerField(),
                    "por_dia_semana": serializers.ListField(child=serializers.JSONField()),
                    "maior_valor_semana": serializers.IntegerField(),
                    "buckets_dia_mes": serializers.JSONField(),
                    "maior_valor_bucket": serializers.IntegerField(),
                    "faqs_sugeridas_pendentes": serializers.IntegerField(),
                },
            )
        }
    )
    def get(self, request):
        hoje = timezone.localdate()
        inicio_30 = hoje - timedelta(days=29)
        inicio_180 = hoje - timedelta(days=180)

        # Solicitações por tipo/status
        tipo_labels = dict(Solicitacao.Tipo.choices)
        status_labels = dict(Solicitacao.Status.choices)
        por_tipo = list(
            Solicitacao.objects.values("tipo").annotate(total=Count("id")).order_by("tipo")
        )
        for row in por_tipo:
            row["label"] = tipo_labels.get(row["tipo"], row["tipo"])
        por_status = list(
            Solicitacao.objects.values("status").annotate(total=Count("id")).order_by("status")
        )
        for row in por_status:
            row["label"] = status_labels.get(row["status"], row["status"])

        # Volume de mensagens/conversas/boletos por dia (últimos 30 dias)
        mensagens_raw = list(
            Mensagem.objects.filter(criado_em__date__gte=inicio_30)
            .annotate(dia=TruncDate("criado_em"))
            .values("dia", "direcao")
            .annotate(total=Count("id"))
        )
        mapa_mensagens = {}
        for row in mensagens_raw:
            mapa_mensagens.setdefault(row["dia"], {"in": 0, "out": 0})[row["direcao"]] = row[
                "total"
            ]

        conversas_novas_raw = list(
            Conversa.objects.filter(criado_em__date__gte=inicio_30)
            .annotate(dia=TruncDate("criado_em"))
            .values("dia")
            .annotate(total=Count("id"))
        )
        mapa_conversas_novas = {row["dia"]: row["total"] for row in conversas_novas_raw}

        boletos_raw = list(
            Boleto.objects.filter(enviado_em__date__gte=inicio_30, enviado_em__isnull=False)
            .annotate(dia=TruncDate("enviado_em"))
            .values("dia")
            .annotate(total=Count("id"))
        )
        mapa_boletos = {row["dia"]: row["total"] for row in boletos_raw}

        serie_30_dias = []
        maior_valor_serie = 1
        for i in range(30):
            dia = inicio_30 + timedelta(days=i)
            msgs = mapa_mensagens.get(dia, {})
            recebidas = msgs.get("in", 0)
            enviadas = msgs.get("out", 0)
            serie_30_dias.append(
                {
                    "dia": dia.isoformat(),
                    "recebidas": recebidas,
                    "enviadas": enviadas,
                    "conversas_novas": mapa_conversas_novas.get(dia, 0),
                    "boletos_enviados": mapa_boletos.get(dia, 0),
                }
            )
            maior_valor_serie = max(maior_valor_serie, recebidas, enviadas)

        # Cobertura de clientes
        total_clientes = Cliente.objects.count()
        clientes_com_telefone = Cliente.objects.filter(telefones__isnull=False).distinct().count()
        clientes_com_conversa = Cliente.objects.filter(conversas__isnull=False).distinct().count()
        clientes_bloqueados = Cliente.objects.filter(bloqueado_ia=True).count()

        # Qualidade da IA
        total_solicitacoes = Solicitacao.objects.count()
        solicitacoes_precisa_humano = Solicitacao.objects.filter(precisa_humano=True).count()
        taxa_solicitacoes_humano = (
            solicitacoes_precisa_humano / total_solicitacoes * 100 if total_solicitacoes else 0
        )
        total_conversas = Conversa.objects.count()
        conversas_precisa_revisao = Conversa.objects.filter(precisa_revisao_humana=True).count()
        taxa_conversas_revisao = (
            conversas_precisa_revisao / total_conversas * 100 if total_conversas else 0
        )

        # Boletos
        total_boletos = Boleto.objects.count()
        boletos_enviados = Boleto.objects.filter(enviado_em__isnull=False).count()

        # FAQs sugeridas pendentes de curadoria (fallback do bot novo, WS-A/WS-B)
        faqs_sugeridas_pendentes = FAQSugerida.objects.filter(
            status=FAQSugerida.Status.PENDENTE
        ).count()

        # Padrões sazonais (janela de 180 dias)
        janela_qs = Mensagem.objects.filter(criado_em__date__gte=inicio_180)
        por_dia_semana_raw = list(
            janela_qs.annotate(dow=ExtractWeekDay("criado_em"))
            .values("dow")
            .annotate(total=Count("id"))
        )
        DIAS_SEMANA_PT = {
            1: "Domingo",
            2: "Segunda",
            3: "Terça",
            4: "Quarta",
            5: "Quinta",
            6: "Sexta",
            7: "Sábado",
        }
        mapa_semana = {row["dow"]: row["total"] for row in por_dia_semana_raw}
        por_dia_semana = [
            {"label": DIAS_SEMANA_PT[dow], "total": mapa_semana.get(dow, 0)} for dow in range(1, 8)
        ]
        maior_valor_semana = max([row["total"] for row in por_dia_semana] + [1])

        por_dia_mes_raw = list(
            janela_qs.annotate(dom=ExtractDay("criado_em"))
            .values("dom")
            .annotate(total=Count("id"))
        )
        buckets = {"1-7": 0, "8-15": 0, "16-23": 0, "24-31": 0}
        for row in por_dia_mes_raw:
            dom = row["dom"]
            if dom <= 7:
                buckets["1-7"] += row["total"]
            elif dom <= 15:
                buckets["8-15"] += row["total"]
            elif dom <= 23:
                buckets["16-23"] += row["total"]
            else:
                buckets["24-31"] += row["total"]
        maior_valor_bucket = max(list(buckets.values()) + [1])

        data = {
            "por_tipo": por_tipo,
            "por_status": por_status,
            "serie_30_dias": serie_30_dias,
            "maior_valor_serie": maior_valor_serie,
            "total_clientes": total_clientes,
            "clientes_com_telefone": clientes_com_telefone,
            "clientes_com_conversa": clientes_com_conversa,
            "clientes_bloqueados": clientes_bloqueados,
            "total_solicitacoes": total_solicitacoes,
            "solicitacoes_precisa_humano": solicitacoes_precisa_humano,
            "taxa_solicitacoes_humano": taxa_solicitacoes_humano,
            "total_conversas": total_conversas,
            "conversas_precisa_revisao": conversas_precisa_revisao,
            "taxa_conversas_revisao": taxa_conversas_revisao,
            "total_boletos": total_boletos,
            "boletos_enviados": boletos_enviados,
            "por_dia_semana": por_dia_semana,
            "maior_valor_semana": maior_valor_semana,
            "buckets_dia_mes": buckets,
            "maior_valor_bucket": maior_valor_bucket,
            "faqs_sugeridas_pendentes": faqs_sugeridas_pendentes,
        }
        return Response(data)


class BotConfigAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = BotConfigSerializer

    @extend_schema(responses={200: BotConfigSerializer})
    def get(self, request):
        config = BotConfig.get_solo()
        serializer = BotConfigSerializer(config)
        return Response(serializer.data)

    @extend_schema(request=BotConfigSerializer, responses={200: BotConfigSerializer})
    def patch(self, request):
        config = BotConfig.get_solo()
        serializer = BotConfigSerializer(config, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MensagensConfigAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = MensagensConfigSerializer

    @extend_schema(responses={200: MensagensConfigSerializer})
    def get(self, request):
        config = MensagensConfig.get_solo()
        serializer = MensagensConfigSerializer(config)
        return Response(serializer.data)

    @extend_schema(request=MensagensConfigSerializer, responses={200: MensagensConfigSerializer})
    def patch(self, request):
        config = MensagensConfig.get_solo()
        serializer = MensagensConfigSerializer(config, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        request=inline_serializer(
            name="RestoreRequestInline", fields={"campo": serializers.CharField(required=True)}
        ),
        responses={200: MensagensConfigSerializer},
    )
    def post(self, request):
        config = MensagensConfig.get_solo()
        campo = request.data.get("campo", "").strip()
        defaults = MensagensConfig.get_defaults_map()

        if campo in defaults:
            setattr(config, campo, defaults[campo])
            config.save(update_fields=[campo, "atualizado_em"])
            serializer = MensagensConfigSerializer(config)
            return Response(serializer.data)
        else:
            return Response(
                {"detail": "Campo inválido para restauração."}, status=status.HTTP_400_BAD_REQUEST
            )


class MensagensConfigRestoreAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = MensagensConfigSerializer

    @extend_schema(
        request=inline_serializer(
            name="RestoreRequest", fields={"campo": serializers.CharField(required=False)}
        ),
        responses={200: MensagensConfigSerializer},
    )
    def post(self, request):
        config = MensagensConfig.get_solo()
        campo = request.data.get("campo", "").strip()
        defaults = MensagensConfig.get_defaults_map()

        if campo in defaults:
            setattr(config, campo, defaults[campo])
            config.save(update_fields=[campo, "atualizado_em"])
            serializer = MensagensConfigSerializer(config)
            return Response(serializer.data)
        elif campo == "all" or not campo:
            for key, val in defaults.items():
                setattr(config, key, val)
            config.save()
            serializer = MensagensConfigSerializer(config)
            return Response(serializer.data)
        else:
            return Response(
                {"detail": f"Campo '{campo}' inválido para restauração."},
                status=status.HTTP_400_BAD_REQUEST,
            )


class FAQViewSet(viewsets.ModelViewSet):
    queryset = FAQ.objects.prefetch_related("respostas").all()
    serializer_class = FAQSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None

    def get_queryset(self):
        return self.queryset.order_by("pergunta")

    def get_serializer(self, *args, **kwargs):
        # Handle custom multipart form-data where "faq" is a JSON string
        # and file fields are sent separately as "arquivo_X" where X is the index
        if "faq" in self.request.data:
            try:
                data = json.loads(self.request.data["faq"])
                # Clean up empty/null string fields in answers representing files,
                # but preserve valid path strings for WritableFileField
                if "respostas" in data:
                    for resp in data["respostas"]:
                        if "arquivo" in resp and isinstance(resp["arquivo"], str):
                            val = resp["arquivo"].strip()
                            if not val or val == "null":
                                resp.pop("arquivo")

                # Attach file objects from request.FILES or request.data
                files_source = self.request.FILES if self.request.FILES else self.request.data
                for key, value in files_source.items():
                    if key.startswith("arquivo_"):
                        try:
                            idx = int(key.split("_")[1])
                            if "respostas" in data and idx < len(data["respostas"]):
                                data["respostas"][idx]["arquivo"] = value
                        except (ValueError, IndexError):
                            pass
                kwargs["data"] = data
            except (ValueError, TypeError):
                pass
        return super().get_serializer(*args, **kwargs)

    @action(detail=True, methods=["post"])
    def toggle(self, request, pk=None):
        faq = self.get_object()
        faq.ativo = not faq.ativo
        faq.save(update_fields=["ativo"])
        return Response(FAQSerializer(faq).data)


class FAQSugeridaViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Curadoria de perguntas que o bot não conseguiu responder pela FAQ
    existente (fallback determinístico do motor novo, `FAQSugerida.registrar`
    em `core/models.py`). O operador edita a pergunta, aprova (vira FAQ real
    com respostas) ou rejeita."""

    queryset = FAQSugerida.objects.select_related("conversa", "faq_criada", "revisado_por")
    serializer_class = FAQSugeridaSerializer
    permission_classes = [permissions.IsAdminUser]
    http_method_names = ["get", "patch", "delete", "post", "head", "options"]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs

    @action(detail=True, methods=["post"])
    def aprovar(self, request, pk=None):
        """Cria a FAQ (+ respostas) a partir da sugestão e marca como aprovada."""
        sugestao = self.get_object()
        payload_serializer = FAQSugeridaAprovarSerializer(data=request.data)
        payload_serializer.is_valid(raise_exception=True)
        dados = payload_serializer.validated_data
        pergunta_final = (dados.get("pergunta_final") or "").strip() or sugestao.pergunta
        respostas = dados.get("respostas") or []

        with transaction.atomic():
            faq = FAQ.objects.create(pergunta=pergunta_final, ativo=True)
            for resp in respostas:
                FAQResposta.objects.create(
                    faq=faq,
                    ordem=resp.get("ordem", 0),
                    texto=resp.get("texto", ""),
                )
            sugestao.status = FAQSugerida.Status.APROVADA
            sugestao.faq_criada = faq
            sugestao.revisado_por = request.user
            sugestao.revisado_em = timezone.now()
            sugestao.save(update_fields=["status", "faq_criada", "revisado_por", "revisado_em"])

        return Response(FAQSugeridaSerializer(sugestao).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def rejeitar(self, request, pk=None):
        sugestao = self.get_object()
        sugestao.status = FAQSugerida.Status.REJEITADA
        sugestao.revisado_por = request.user
        sugestao.revisado_em = timezone.now()
        sugestao.save(update_fields=["status", "revisado_por", "revisado_em"])
        return Response(FAQSugeridaSerializer(sugestao).data)


class ClienteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Cliente.objects.prefetch_related("telefones", "contratos_penhor").all()
    permission_classes = [permissions.IsAdminUser]
    lookup_field = "cpf"
    lookup_url_kwarg = "pk"
    lookup_value_regex = "[^/]+"
    pagination_class = None

    def get_object(self):
        from django.http import Http404

        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        cpf_raw = self.kwargs[lookup_url_kwarg]

        cpf_digits = "".join(filter(str.isdigit, cpf_raw))
        if cpf_digits == "00000000000":
            raise Http404("Cliente não encontrado.")

        obj = Cliente.buscar_por_cpf(cpf_raw)
        if not obj:
            raise Http404("Cliente não encontrado.")

        self.check_object_permissions(self.request, obj)

        from django.db.models import prefetch_related_objects

        prefetch_related_objects(
            [obj],
            "telefones",
            "contratos_penhor",
            "conversas",
            "solicitacoes",
            "solicitacoes__contratos",
            "solicitacoes__boletos",
            "solicitacoes__conversa__mensagens",
        )
        return obj

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ClienteDetailSerializer
        return ClienteListSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # Ocultar o cliente reservado/especial com CPF 000.000.000-00 ou 00000000000
        qs = qs.exclude(cpf__in=["000.000.000-00", "00000000000"])

        # Filtrar apenas clientes com pelo menos um contrato ativo se solicitado
        ativos_somente = self.request.query_params.get("ativos_somente")
        if ativos_somente == "1":
            qs = (
                qs.filter(contratos_penhor__isnull=False)
                .filter(
                    ~Q(contratos_penhor__situacao_codigo__in=SITUACOES_LIQUIDADAS_COD)
                    & ~Q(contratos_penhor__situacao__icontains="Liquidado")
                )
                .distinct()
            )

        if self.action == "list":
            qs = qs.annotate(
                num_telefones=Count("telefones", distinct=True),
                num_conversas=Count("conversas", distinct=True),
                num_contratos_ativos=Count(
                    "contratos_penhor",
                    filter=~Q(contratos_penhor__situacao_codigo__in=SITUACOES_LIQUIDADAS_COD)
                    & ~Q(contratos_penhor__situacao__icontains="Liquidado"),
                    distinct=True,
                ),
                total_emprestimo_ativo=Sum(
                    "contratos_penhor__vlr_emprestimo",
                    filter=~Q(contratos_penhor__situacao_codigo__in=SITUACOES_LIQUIDADAS_COD)
                    & ~Q(contratos_penhor__situacao__icontains="Liquidado"),
                ),
                total_avaliacao_ativo=Sum(
                    "contratos_penhor__vlr_avaliacao",
                    filter=~Q(contratos_penhor__situacao_codigo__in=SITUACOES_LIQUIDADAS_COD)
                    & ~Q(contratos_penhor__situacao__icontains="Liquidado"),
                ),
            )
        q = self.request.query_params.get("q", "").strip()
        if q:
            qs = qs.filter(Q(cpf__icontains=q) | Q(nome__icontains=q))
        bloqueado = self.request.query_params.get("bloqueado")
        if bloqueado == "1":
            qs = qs.filter(bloqueado_ia=True)
        return qs.order_by("nome")

    @action(detail=True, methods=["post"], url_path="toggle-bloqueio")
    def toggle_bloqueio(self, request, pk=None):
        cliente = self.get_object()
        bloquear = request.data.get("bloquear")
        acao = request.data.get("acao")
        motivo = request.data.get("motivo", "").strip()

        should_block = None
        if bloquear is not None:
            should_block = bool(bloquear)
        elif acao is not None:
            should_block = acao == "bloquear"
        else:
            should_block = not cliente.bloqueado_ia

        if should_block:
            cliente.bloqueado_ia = True
            cliente.bloqueado_motivo = motivo
            cliente.bloqueado_em = timezone.now()
        else:
            cliente.bloqueado_ia = False
            cliente.bloqueado_motivo = ""
            cliente.bloqueado_em = None

        cliente.save(update_fields=["bloqueado_ia", "bloqueado_motivo", "bloqueado_em"])
        return Response(ClienteDetailSerializer(cliente).data)

    @action(detail=True, methods=["post"], url_path="toggle-ia")
    def toggle_ia(self, request, pk=None):
        return self.toggle_bloqueio(request, pk=pk)


class ConversaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Conversa.objects.all()
    permission_classes = [permissions.IsAdminUser]
    pagination_class = None

    # Extensões aceitas no envio manual de arquivo pelo operador (WS-B item 3).
    _EXTENSOES_ANEXO_PERMITIDAS = {
        "jpg",
        "jpeg",
        "png",
        "webp",
        "gif",
        "mp3",
        "ogg",
        "opus",
        "m4a",
        "mp4",
        "pdf",
        "doc",
        "docx",
        "xls",
        "xlsx",
    }
    _TAMANHO_MAXIMO_ANEXO_BYTES = 16 * 1024 * 1024  # 16MB, teto prático do WhatsApp.

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ConversaDetailSerializer
        return ConversaListSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "retrieve":
            qs = qs.select_related("cliente").prefetch_related(
                "mensagens",
                "solicitacoes",
                "solicitacoes__contratos",
                "solicitacoes__boletos",
                "solicitacoes__conversa__mensagens",
            )
        else:
            qs = qs.select_related("cliente")

        estado = self.request.query_params.get("estado")
        revisao = self.request.query_params.get("revisao")
        tipo_contato = self.request.query_params.get("tipo_contato")
        q = self.request.query_params.get("q", "").strip()

        if estado:
            qs = qs.filter(estado=estado)
        if revisao == "1":
            qs = qs.filter(precisa_revisao_humana=True)
        if tipo_contato:
            qs = qs.filter(tipo_contato=tipo_contato)
        if q:
            qs = qs.filter(
                Q(remote_jid__icontains=q)
                | Q(cliente__cpf__icontains=q)
                | Q(cliente__nome__icontains=q)
                | Q(nome_salvo__icontains=q)
            )

        # Annotate count of active (non-liquidated) penhor contracts for the
        # linked client, if any. 0 when no client or no active contracts.
        qs = qs.annotate(
            num_contratos_ativos=Count(
                "cliente__contratos_penhor",
                filter=(
                    ~Q(cliente__contratos_penhor__situacao_codigo__in=SITUACOES_LIQUIDADAS_COD)
                    & ~Q(cliente__contratos_penhor__situacao__icontains="Liquidado")
                ),
                distinct=True,
            )
        )
        return qs.order_by("-ultima_interacao")

    @action(detail=True, methods=["post"], url_path="toggle-revisao")
    def toggle_revisao(self, request, pk=None):
        conversa = self.get_object()
        conversa.precisa_revisao_humana = not conversa.precisa_revisao_humana
        conversa.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        return Response(ConversaDetailSerializer(conversa).data)

    @action(detail=False, methods=["post"], url_path="limpar-todas")
    def limpar_todas(self, request):
        if not request.user.is_superuser:
            return Response(
                {"detail": "Apenas superusuários podem limpar todas as conversas."},
                status=status.HTTP_403_FORBIDDEN,
            )
        confirmacao = request.data.get("confirmacao")
        if confirmacao != "DELETAR_TUDO":
            return Response(
                {"detail": "Confirmação inválida para limpar todas as conversas."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        Conversa.objects.all().delete()
        return Response({"message": "Todas as conversas foram limpas com sucesso!"})

    @action(detail=True, methods=["post"], url_path="enviar")
    def enviar_mensagem(self, request, pk=None):
        """Permite ao operador responder uma conversa diretamente pelo painel.
        Persiste a mensagem como OUT e envia via Evolution API."""
        conversa = self.get_object()
        texto = (request.data.get("texto") or "").strip()
        if not texto:
            return Response(
                {"detail": "Campo 'texto' é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from whatsapp.tasks import _remote_jid_para_numero

        numero = _remote_jid_para_numero(conversa.remote_jid)
        if not numero:
            return Response(
                {"detail": "Não foi possível normalizar o número de destino."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        client = get_client()
        enviado = client.send_text(numero, texto)

        Mensagem.objects.create(
            conversa=conversa,
            direcao=Mensagem.Direcao.OUT,
            texto=texto,
            enviado_ok=enviado,
        )

        update_fields = ["ultima_interacao"]
        if not enviado:
            conversa.precisa_revisao_humana = True
            update_fields.append("precisa_revisao_humana")
        conversa.ultima_interacao = timezone.now()
        conversa.save(update_fields=update_fields)

        return Response(
            {
                "enviado": enviado,
                "mensagens": ConversaDetailSerializer(conversa).data.get("mensagens", []),
            },
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="enviar-arquivo",
        parser_classes=[MultiPartParser, FormParser],
    )
    def enviar_arquivo(self, request, pk=None):
        """Permite ao operador anexar um arquivo (imagem/áudio/vídeo/documento)
        pelo painel. Persiste como Mensagem OUT com `arquivo` preenchido e
        envia via Evolution API (EvolutionClient.send_file, que já cobre os
        4 mediatypes a partir do mimetype)."""
        conversa = self.get_object()
        arquivo = request.FILES.get("arquivo")
        if not arquivo:
            return Response(
                {"detail": "Campo 'arquivo' é obrigatório."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if arquivo.size > self._TAMANHO_MAXIMO_ANEXO_BYTES:
            return Response(
                {"detail": "Arquivo excede o tamanho máximo permitido (16MB)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        extensao = (os.path.splitext(arquivo.name)[1] or "").lstrip(".").lower()
        if extensao not in self._EXTENSOES_ANEXO_PERMITIDAS:
            return Response(
                {"detail": f"Extensão '.{extensao}' não permitida."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        legenda = (request.data.get("legenda") or "").strip()

        import mimetypes

        mimetype = mimetypes.guess_type(arquivo.name)[0] or ""
        if mimetype.startswith("image/"):
            tipo_midia = Mensagem.TipoMidia.IMAGE
        elif mimetype.startswith("video/"):
            tipo_midia = Mensagem.TipoMidia.VIDEO
        elif mimetype.startswith("audio/"):
            tipo_midia = Mensagem.TipoMidia.AUDIO
        else:
            tipo_midia = Mensagem.TipoMidia.DOCUMENT

        from whatsapp.tasks import _remote_jid_para_numero

        numero = _remote_jid_para_numero(conversa.remote_jid)
        if not numero:
            return Response(
                {"detail": "Não foi possível normalizar o número de destino."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        mensagem = Mensagem.objects.create(
            conversa=conversa,
            direcao=Mensagem.Direcao.OUT,
            texto=legenda,
            arquivo=arquivo,
            tipo_midia=tipo_midia,
        )

        client = get_client()
        enviado = client.send_file(numero, mensagem.arquivo.path, arquivo.name, caption=legenda)
        mensagem.enviado_ok = enviado
        mensagem.save(update_fields=["enviado_ok"])

        conversa.ultima_interacao = timezone.now()
        conversa.save(update_fields=["ultima_interacao"])

        return Response(
            MensagemPainelSerializer(mensagem, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="mensagens/(?P<mensagem_id>[^/.]+)/media")
    def baixar_media_mensagem(self, request, pk=None, mensagem_id=None):
        import base64

        import requests
        from django.conf import settings
        from django.http import Http404, HttpResponse

        conversa = self.get_object()
        mensagem = conversa.mensagens.filter(id=mensagem_id).first()
        if not mensagem:
            raise Http404("Mensagem não encontrada nesta conversa.")

        from whatsapp.views import desembrulhar_no_mensagem

        payload = mensagem.payload_bruto or {}
        data_node = payload.get("data", {})
        message_node = data_node.get("message", {})
        if not message_node:
            raise Http404("Mensagem não possui payload de mídia.")

        # Mídia efêmera/"visualização única" vem embrulhada num nó extra
        # (ephemeralMessage/viewOnceMessage*) -- desembrulha só para
        # DETECTAR o tipo/mimetype/filename. A chamada à Evolution API
        # abaixo continua usando `data_node` original (com o embrulho, se
        # houver): é a própria Evolution que desembrulha ao descriptografar.
        message_node_interno = desembrulhar_no_mensagem(message_node)

        # Verifica se possui algum nó de mídia
        media_type = None
        media_node = None
        for key in ["imageMessage", "audioMessage", "documentMessage", "videoMessage"]:
            if key in message_node_interno:
                media_type = key
                media_node = message_node_interno[key]
                break

        if not media_type or not media_node:
            raise Http404("Esta mensagem não é do tipo mídia ou não contém arquivo.")

        # Obtém credenciais da Evolution API da settings
        url = f"{settings.EVOLUTION_API_URL.rstrip('/')}/chat/getBase64FromMediaMessage/{settings.EVOLUTION_INSTANCE}"
        headers = {
            "Content-Type": "application/json",
            "apikey": settings.EVOLUTION_API_KEY,
        }

        # Faz requisição para descriptografar e baixar a mídia
        try:
            resp = requests.post(url, json={"message": data_node}, headers=headers, timeout=20)
            if resp.status_code != 201:
                logger.warning("Evolution API retornou status %s ao obter mídia", resp.status_code)
                return Response(
                    {"detail": "Não foi possível obter a mídia com o gateway do WhatsApp."},
                    status=status.HTTP_502_BAD_GATEWAY,
                )
            res_json = resp.json()
        except requests.RequestException:
            logger.exception("Falha de conexão com a Evolution API ao baixar mídia")
            return Response(
                {"detail": "Falha de conexão com o gateway do WhatsApp."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except ValueError:
            logger.error("Resposta não-JSON da Evolution API ao baixar mídia")
            return Response(
                {"detail": "Resposta inválida do gateway do WhatsApp."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        base64_str = res_json.get("base64")
        if not base64_str:
            return Response(
                {"detail": "Mídia não retornou dados de conteúdo (base64)."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # Decodifica o base64 para binário
        try:
            file_data = base64.b64decode(base64_str)
        except Exception:
            return Response(
                {"detail": "Erro ao descriptografar o conteúdo do arquivo."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        mimetype = (
            res_json.get("mimetype") or media_node.get("mimetype") or "application/octet-stream"
        )

        response = HttpResponse(file_data, content_type=mimetype)
        # Se for um documento/arquivo que o navegador não exibe em tela, adiciona Content-Disposition para download
        if media_type == "documentMessage":
            filename = res_json.get("fileName") or media_node.get("fileName") or "arquivo"
            response["Content-Disposition"] = f'attachment; filename="{filename}"'

        return response


def _montar_resposta_simulador(resultado, cliente, msgs) -> list:
    """Espelha (sem efeitos colaterais em BD) o dispatch sequencial
    multi-ação de `whatsapp.tasks._processar_mensagem_com_lock` para o
    simulador: a partir do WS-A a IA é só classificadora -- o texto de
    exibição vem de templates/renderer em Python, nunca de um campo de
    texto da IA. Não cria Solicitacao real nem envia nada via WhatsApp; é
    só uma prévia do que o bot responderia. O simulador sempre chama
    `extrair_intencao` com `identificado=True, db_atualizada=True` (ver
    `SimulatorView.post`), então os gates de identificação/database do
    dispatch real nunca disparam aqui -- a ordem das ações é a mesma:
    saudação -> FAQs -> infos_contrato -> pagamento -> segunda_via ->
    dúvidas/fallback.

    Retorna uma LISTA de mensagens (paridade com o fan-out real de
    `whatsapp.tasks._enviar_fila`): cada item vira uma bolha/turno separado
    no simulador. Uma FAQResposta com arquivo vira uma entrada
    "📎 {nome}" + o texto da legenda, já que o simulador não envia arquivo
    de verdade."""
    from whatsapp.respostas_contrato import render_template, renderizar_infos_contrato
    from whatsapp.tasks import _montar_pergunta_pagamento_incompleto, _saudacao

    fila: list = []

    if resultado.saudacao:
        tem_pedido_junto = bool(
            resultado.faq_ids
            or resultado.infos_contrato
            or resultado.solicitacoes
            or resultado.segunda_via
            or resultado.duvidas_sem_faq
        )
        if cliente:
            primeiro_nome = (cliente.nome or "").split()[0] if cliente.nome else ""
            tpl = (
                msgs.tpl_saudacao_cliente_com_pedido
                if tem_pedido_junto
                else msgs.tpl_saudacao_cliente
            )
            fila.append(render_template(tpl, saudacao=_saudacao(), nome=primeiro_nome))
        else:
            tpl = msgs.msg_saudacao_com_pedido if tem_pedido_junto else msgs.msg_saudacao
            fila.append(render_template(tpl, saudacao=_saudacao()))

    for faq_id in resultado.faq_ids:
        try:
            faq = FAQ.objects.get(id=faq_id, ativo=True)
        except FAQ.DoesNotExist:
            continue
        for resp in faq.respostas.all().order_by("ordem"):
            if resp.arquivo:
                nome_arquivo = os.path.basename(resp.arquivo.name)
                entrada = f"📎 {nome_arquivo}"
                if resp.texto:
                    entrada = f"{entrada}\n{resp.texto}"
                fila.append(entrada)
            elif resp.texto:
                fila.append(resp.texto)

    if resultado.infos_contrato:
        infos_para_render = []
        pediu_campo_valor = False
        for pedido in resultado.infos_contrato:
            tem_filtro_valor = (
                pedido.filtro_valor_min is not None or pedido.filtro_valor_max is not None
            )
            if tem_filtro_valor and pedido.filtro_valor_campo is None:
                if not pediu_campo_valor:
                    fila.append(msgs.msg_pedir_campo_valor_filtro)
                    pediu_campo_valor = True
                continue
            infos_para_render.append(pedido)
        if infos_para_render:
            fila.extend(renderizar_infos_contrato(cliente, infos_para_render, msgs))

    if resultado.solicitacoes:
        from ia.schemas import TipoPagamento

        tem_indefinido = any(d.tipo == TipoPagamento.INDEFINIDO for d in resultado.solicitacoes)
        if resultado.pronto_para_criar_solicitacao and cliente and not tem_indefinido:
            fila.append(
                f"{msgs.msg_solicitacao_criada}\n\n(simulação: nenhuma solicitação real foi criada)"
            )
        else:
            fila.append(
                _montar_pergunta_pagamento_incompleto(
                    cliente, msgs, resultado.solicitacoes, fila=fila
                )
            )

    if resultado.segunda_via:
        fila.append(
            msgs.msg_segunda_via_confirma.format(contratos="(simulação)", tipo="(simulação)")
        )

    if resultado.duvidas_sem_faq:
        duvidas_txt = "; ".join(resultado.duvidas_sem_faq)
        if fila:
            fila.append(render_template(msgs.msg_duvida_anotada, duvidas=duvidas_txt))
        else:
            fila.append(msgs.msg_fallback_sem_resposta)

    if resultado.nenhuma_acao():
        fila.append(msgs.msg_fallback_sem_resposta)
    elif not fila:
        fila.append(msgs.msg_neutra_padrao)

    return fila


def _debug_resultado_simulador(resultado):
    acoes = []
    if resultado.saudacao:
        acoes.append("saudacao")
    if resultado.faq_ids:
        acoes.append(f"faq:{len(resultado.faq_ids)}")
    if resultado.infos_contrato:
        acoes.append(f"info_contrato:{len(resultado.infos_contrato)}")
    if resultado.solicitacoes:
        acoes.append("pagamento")
    if resultado.segunda_via:
        acoes.append("segunda_via")
    if resultado.duvidas_sem_faq:
        acoes.append(f"duvida_sem_faq:{len(resultado.duvidas_sem_faq)}")

    return {
        "acoes": acoes,
        "precisa_humano": resultado.precisa_humano,
        "faq_ids": resultado.faq_ids,
        "infos_contrato": [i.model_dump() for i in resultado.infos_contrato],
        "solicitacoes": [s.model_dump() for s in resultado.solicitacoes],
        "pronto_para_criar_solicitacao": resultado.pronto_para_criar_solicitacao,
        "duvidas_sem_faq": resultado.duvidas_sem_faq,
        "raw_prompt": getattr(resultado, "_raw_prompt", None),
        "raw_response": getattr(resultado, "_raw_response", None),
    }


class SimulatorView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer

    def _get_estado(self, request):
        from core.mensagens_defaults import SIMULADOR_SESSION_KEY

        estado = request.session.get(SIMULADOR_SESSION_KEY)
        if estado is None:
            estado = {"cliente_cpf": None, "turnos": []}
            request.session[SIMULADOR_SESSION_KEY] = estado
        return estado

    def _response_data(self, request, estado):
        cliente = None
        if estado["cliente_cpf"]:
            cliente = Cliente.buscar_por_cpf(estado["cliente_cpf"])

        cliente_data = None
        if cliente:
            cliente_data = ClienteDetailSerializer(cliente).data

        return {"cliente": cliente_data, "turnos": estado["turnos"]}

    @extend_schema(
        responses={
            200: inline_serializer(
                name="SimulatorGetResponse",
                fields={
                    "cliente": serializers.JSONField(allow_null=True),
                    "turnos": serializers.ListField(child=serializers.JSONField()),
                },
            )
        }
    )
    def get(self, request):
        estado = self._get_estado(request)
        return Response(self._response_data(request, estado))

    @extend_schema(
        request=inline_serializer(
            name="SimulatorPostRequest",
            fields={
                "acao": serializers.CharField(),
                "cpf": serializers.CharField(required=False),
                "mensagem": serializers.CharField(required=False),
            },
        ),
        responses={
            200: inline_serializer(
                name="SimulatorPostResponse",
                fields={
                    "cliente": serializers.JSONField(allow_null=True),
                    "turnos": serializers.ListField(child=serializers.JSONField()),
                },
            )
        },
    )
    def post(self, request):
        estado = self._get_estado(request)
        acao = request.data.get("acao")

        from core.mensagens_defaults import SIMULADOR_SESSION_KEY

        if acao == "selecionar_cliente":
            cpf = request.data.get("cpf", "").strip()
            cli_obj = Cliente.buscar_por_cpf(cpf) if cpf else None
            if cli_obj:
                estado["cliente_cpf"] = cli_obj.cpf
                estado["turnos"] = []
                request.session[SIMULADOR_SESSION_KEY] = estado
                request.session.modified = True

        elif acao == "remover_cliente":
            estado["cliente_cpf"] = None
            estado["turnos"] = []
            request.session[SIMULADOR_SESSION_KEY] = estado
            request.session.modified = True

        elif acao == "reiniciar":
            estado["turnos"] = []
            request.session[SIMULADOR_SESSION_KEY] = estado
            request.session.modified = True

        elif acao == "enviar":
            texto = request.data.get("mensagem", "").strip()
            if texto:
                cliente = None
                if estado["cliente_cpf"]:
                    cliente = Cliente.buscar_por_cpf(estado["cliente_cpf"])

                from whatsapp.tasks import HISTORICO_TAMANHO, _contratos_ativos_values

                historico = [
                    {"direcao": turno["direcao"], "texto": turno["texto"]}
                    for turno in estado["turnos"][-HISTORICO_TAMANHO:]
                ]
                contratos_cliente = []
                if cliente is not None:
                    contratos_cliente = _contratos_ativos_values(cliente)

                faqs = list(FAQ.objects.filter(ativo=True).values("id", "pergunta"))

                resultado = extrair_intencao(
                    texto,
                    historico,
                    contratos_cliente,
                    faqs,
                    identificado=True,
                    db_atualizada=True,
                    contato_tipo="cliente",
                )
                msgs = MensagensConfig.get_solo()
                respostas = _montar_resposta_simulador(resultado, cliente, msgs)
                debug = _debug_resultado_simulador(resultado)

                estado["turnos"].append({"direcao": "in", "texto": texto})
                ultimo_idx = len(respostas) - 1
                for idx, resposta_texto in enumerate(respostas):
                    turno = {"direcao": "out", "texto": resposta_texto}
                    if idx == ultimo_idx:
                        turno["debug"] = debug
                    estado["turnos"].append(turno)
                request.session[SIMULADOR_SESSION_KEY] = estado
                request.session.modified = True

        return Response(self._response_data(request, estado))


class SimulatorChatAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer

    @extend_schema(
        request=inline_serializer(
            name="SimulatorChatRequest",
            fields={
                "mensagem": serializers.CharField(),
                "cliente_cpf": serializers.CharField(required=False, allow_blank=True),
                "historico": serializers.ListField(
                    child=serializers.JSONField(), required=False, allow_null=True
                ),
            },
        ),
        responses={
            200: inline_serializer(
                name="SimulatorChatResponse",
                fields={
                    "resposta_sugerida": serializers.CharField(),
                    "debug": serializers.JSONField(),
                    "historico": serializers.ListField(child=serializers.JSONField()),
                },
            )
        },
    )
    def post(self, request):
        mensagem = request.data.get("mensagem", "").strip()
        cliente_cpf = request.data.get("cliente_cpf", "").strip()
        historico = request.data.get("historico")

        if not mensagem:
            return Response({"detail": "mensagem is required."}, status=status.HTTP_400_BAD_REQUEST)

        cliente = None
        if cliente_cpf:
            cliente = Cliente.buscar_por_cpf(cliente_cpf)

        if historico is None:
            session_state = request.session.get("api_simulador_ia")
            if not session_state or session_state.get("cliente_cpf") != cliente_cpf:
                session_state = {"cliente_cpf": cliente_cpf, "turnos": []}
            historico_turnos = session_state["turnos"]
        else:
            historico_turnos = historico

        from whatsapp.tasks import HISTORICO_TAMANHO, _contratos_ativos_values

        historico_ia = [
            {"direcao": h.get("direcao"), "texto": h.get("texto")}
            for h in historico_turnos[-HISTORICO_TAMANHO:]
        ]

        contratos_cliente = []
        if cliente is not None:
            contratos_cliente = _contratos_ativos_values(cliente)

        faqs = list(FAQ.objects.filter(ativo=True).values("id", "pergunta"))

        resultado = extrair_intencao(
            mensagem,
            historico_ia,
            contratos_cliente,
            faqs,
            identificado=True,
            db_atualizada=True,
            contato_tipo="cliente",
        )
        msgs = MensagensConfig.get_solo()
        respostas = _montar_resposta_simulador(resultado, cliente, msgs)
        debug = _debug_resultado_simulador(resultado)
        # Endpoint legado: mantém `resposta_sugerida` como texto único (join
        # "\n\n") para não quebrar consumidores existentes, mas também expõe
        # `respostas` (lista) com paridade ao fan-out real de `_enviar_fila`.
        texto_resposta = "\n\n".join(respostas)

        new_turn_in = {"direcao": "in", "texto": mensagem}
        new_turn_out = {
            "direcao": "out",
            "texto": texto_resposta,
            "debug": debug,
        }
        historico_turnos.append(new_turn_in)
        historico_turnos.append(new_turn_out)

        if historico is None:
            session_state["turnos"] = historico_turnos
            request.session["api_simulador_ia"] = session_state
            request.session.modified = True

        return Response(
            {
                "resposta_sugerida": texto_resposta,
                "respostas": respostas,
                "debug": debug,
                "historico": historico_turnos,
            }
        )


class WhatsappConnectionView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer

    @extend_schema(
        responses={
            200: inline_serializer(
                name="WhatsappConnectionGetResponse",
                fields={
                    "state": serializers.CharField(),
                    "bot_ativo": serializers.BooleanField(),
                    "qrcode_base64": serializers.CharField(required=False),
                },
            )
        }
    )
    def get(self, request):
        client = get_client()
        state = client.get_connection_state()
        bot_config = BotConfig.get_solo()
        data = {"state": state, "bot_ativo": bot_config.ativo}
        if state != "open":
            data["qrcode_base64"] = client.get_qrcode_base64()
        return Response(data)

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="WhatsappConnectionPostResponse",
                fields={
                    "state": serializers.CharField(),
                    "bot_ativo": serializers.BooleanField(),
                    "qrcode_base64": serializers.CharField(required=False),
                },
            )
        },
    )
    def post(self, request):
        bot_config = BotConfig.get_solo()
        bot_config.ativo = not bot_config.ativo
        bot_config.save(update_fields=["ativo", "atualizado_em"])

        if bot_config.ativo:
            async_task("whatsapp.tasks.sincronizar_contatos")
            async_task("whatsapp.tasks.processar_nao_lidas")

        client = get_client()
        state = client.get_connection_state()
        data = {"state": state, "bot_ativo": bot_config.ativo}
        if state != "open":
            data["qrcode_base64"] = client.get_qrcode_base64()
        return Response(data)


class WhatsAppStatusAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer

    @extend_schema(
        responses={
            200: inline_serializer(
                name="WhatsAppStatusResponse",
                fields={"state": serializers.CharField(), "bot_ativo": serializers.BooleanField()},
            )
        }
    )
    def get(self, request):
        client = get_client()
        state = client.get_connection_state()
        bot_config = BotConfig.get_solo()
        return Response({"state": state, "bot_ativo": bot_config.ativo})


class WhatsAppConectarAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="WhatsAppConectarResponse",
                fields={
                    "state": serializers.CharField(),
                    "qrcode_base64": serializers.CharField(allow_null=True),
                },
            )
        },
    )
    def post(self, request):
        client = get_client()
        state = client.get_connection_state()
        qrcode_base64 = None
        if state != "open":
            qrcode_base64 = client.get_qrcode_base64()
        return Response({"state": state, "qrcode_base64": qrcode_base64})


class WhatsAppDesconectarAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="WhatsAppDesconectarResponse",
                fields={"success": serializers.BooleanField(), "state": serializers.CharField()},
            )
        },
    )
    def post(self, request):
        client = get_client()
        success = client.logout()
        state = client.get_connection_state()
        return Response({"success": success, "state": state})


class SolicitacaoViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Backoffice API: operadores humanos consultam solicitações pendentes,
    mudam status e fazem upload dos boletos que o sistema reenvia ao cliente."""

    queryset = Solicitacao.objects.select_related("cliente", "conversa").prefetch_related(
        "contratos", "boletos"
    )
    http_method_names = ["get", "patch", "post", "head", "options"]
    permission_classes = [permissions.IsAdminUser]
    pagination_class = None

    def get_serializer_class(self):
        if self.action in ("partial_update", "update"):
            return SolicitacaoUpdateSerializer
        return SolicitacaoSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)
        return qs.order_by("-criado_em")

    def partial_update(self, request, *args, **kwargs):
        response = super().partial_update(request, *args, **kwargs)
        instance = self.get_object()
        response.data = SolicitacaoSerializer(instance, context=self.get_serializer_context()).data
        return response

    @action(detail=True, methods=["post"], url_path="boletos")
    def boletos(self, request, pk=None):
        solicitacao = self.get_object()
        arquivos = request.FILES.getlist("arquivo") or (
            [request.FILES["arquivo"]] if "arquivo" in request.FILES else []
        )
        if not arquivos:
            return Response(
                {"detail": "Envie ao menos um PDF no campo 'arquivo'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        linhas = request.POST.getlist("linha_digitavel")

        criados = []
        for i, arquivo in enumerate(arquivos):
            linha_digitavel = linhas[i].strip() if i < len(linhas) else ""
            boleto = Boleto.objects.create(
                solicitacao=solicitacao, arquivo=arquivo, linha_digitavel=linha_digitavel
            )
            criados.append(boleto)

        async_task("api.tasks.enviar_boletos", solicitacao.id)

        return Response(
            BoletoSerializer(criados, many=True).data,
            status=status.HTTP_201_CREATED,
        )


class ImportSqliteAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None

    @extend_schema(
        request=None,
        responses={
            201: inline_serializer(
                name="ImportSqliteResponse",
                fields={
                    "id": serializers.IntegerField(),
                    "status": serializers.CharField(),
                    "arquivo": serializers.CharField(),
                    "criado_em": serializers.DateTimeField(),
                },
            )
        },
    )
    def post(self, request):
        arquivos = request.FILES.getlist("arquivo")
        if not arquivos:
            return Response(
                {"detail": "Envie um arquivo SQLite no campo 'arquivo'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        arquivo = arquivos[0]

        header = arquivo.read(16)
        arquivo.seek(0)
        if header != b"SQLite format 3\x00":
            return Response(
                {"detail": "Arquivo não é um banco SQLite válido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        job = ImportDataJob.objects.create(
            arquivo=arquivo,
            usuario=request.user,
            status=ImportDataJob.Status.PENDING,
        )
        async_task("core.tasks.run_import_job", job.id)

        return Response(
            {
                "id": job.id,
                "status": job.status,
                "arquivo": job.arquivo.name,
                "criado_em": job.criado_em,
            },
            status=status.HTTP_201_CREATED,
        )


class ImportSqliteStatusAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer
    pagination_class = None

    @extend_schema(
        responses={
            200: inline_serializer(
                name="ImportSqliteStatusResponse",
                fields={
                    "id": serializers.IntegerField(),
                    "status": serializers.CharField(),
                    "counts": serializers.JSONField(),
                    "erro": serializers.CharField(),
                    "criado_em": serializers.DateTimeField(),
                    "finalizado_em": serializers.DateTimeField(allow_null=True),
                },
            )
        }
    )
    def get(self, request, pk):
        job = get_object_or_404(ImportDataJob, pk=pk)
        return Response(
            {
                "id": job.id,
                "status": job.status,
                "counts": job.counts,
                "erro": job.erro,
                "arquivo": job.arquivo.name,
                "criado_em": job.criado_em,
                "finalizado_em": job.finalizado_em,
            }
        )


class ImportSqliteLatestAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer
    pagination_class = None

    @extend_schema(
        responses={
            200: inline_serializer(
                name="ImportSqliteLatestResponse",
                fields={"results": serializers.ListField(child=serializers.JSONField())},
            )
        }
    )
    def get(self, request):
        jobs = ImportDataJob.objects.order_by("-criado_em")[:10].values(
            "id", "status", "counts", "erro", "arquivo", "criado_em", "finalizado_em"
        )
        return Response(list(jobs))


_ImportSqliteSyncErrorResponse = inline_serializer(
    name="ImportSqliteSyncErrorResponse",
    fields={"detail": serializers.CharField()},
)


class ImportSqliteSyncAPIView(GenericAPIView):
    permission_classes = [permissions.IsAdminUser]
    serializer_class = serializers.Serializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    pagination_class = None

    @extend_schema(
        request=None,
        responses={
            200: inline_serializer(
                name="ImportSqliteSyncResponse",
                fields={
                    "status": serializers.CharField(),
                    "counts": serializers.JSONField(),
                },
            ),
            400: _ImportSqliteSyncErrorResponse,
            413: _ImportSqliteSyncErrorResponse,
            500: _ImportSqliteSyncErrorResponse,
        },
    )
    def post(self, request):
        arquivos = request.FILES.getlist("arquivo")
        if not arquivos:
            return Response(
                {"detail": "Envie um arquivo SQLite no campo 'arquivo'."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        arquivo = arquivos[0]

        if arquivo.size > 80 * 1024 * 1024:
            return Response(
                {
                    "detail": "Arquivo maior que 80MB. Use o endpoint assíncrono /api/import/sqlite/ para arquivos grandes."
                },
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        header = arquivo.read(16)
        arquivo.seek(0)
        if header != b"SQLite format 3\x00":
            return Response(
                {"detail": "Arquivo não é um banco SQLite válido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with tempfile.NamedTemporaryFile(delete=False, suffix=".sqlite3") as tmp:
            for chunk in arquivo.chunks(64 * 1024):
                tmp.write(chunk)
            temp_path = tmp.name

        job = ImportDataJob.objects.create(
            arquivo=arquivo,
            usuario=request.user,
            status=ImportDataJob.Status.RUNNING,
        )

        try:
            counts = importar_sqlite_arquivo(temp_path)
        except Exception as exc:
            job.status = ImportDataJob.Status.FAILED
            job.erro = str(exc)
            job.finalizado_em = timezone.now()
            job.save(update_fields=["status", "erro", "finalizado_em"])
            return Response(
                {"status": "falhou", "erro": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        else:
            job.status = ImportDataJob.Status.SUCCESS
            job.counts = counts
            job.finalizado_em = timezone.now()
            job.save(update_fields=["status", "counts", "finalizado_em"])
            return Response({"status": "concluido", "counts": counts})
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
