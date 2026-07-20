from django.contrib.auth.models import User
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.models import (
    FAQ,
    Boleto,
    BotConfig,
    Cliente,
    ContratoPenhor,
    Conversa,
    FAQResposta,
    FAQSugerida,
    Mensagem,
    MensagensConfig,
    Solicitacao,
    Telefone,
)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "first_name", "last_name"]


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)


class BotConfigSerializer(serializers.ModelSerializer):
    database_atualizada = serializers.SerializerMethodField()

    class Meta:
        model = BotConfig
        fields = [
            "ativo",
            "ultima_atualizacao_dados",
            "freshness_horas",
            "debounce_segundos",
            "horario_encerramento",
            "responder_desconhecidos",
            "dias_resgate_garantia",
            "enviar_respostas_faq_ia",
            "database_atualizada",
            "atualizado_em",
        ]
        read_only_fields = ["ultima_atualizacao_dados", "database_atualizada", "atualizado_em"]

    def get_database_atualizada(self, obj):
        return obj.database_atualizada()


class MensagensConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = MensagensConfig
        fields = [
            "system_prompt",
            "msg_saudacao",
            "msg_saudacao_com_pedido",
            "msg_cadastro_nao_localizado",
            "msg_pedir_cpf",
            "msg_cpf_invalido",
            "msg_cpf_nao_bate",
            "msg_db_desatualizada",
            "msg_sem_contratos_ativos",
            "msg_solicitacao_criada",
            "msg_boleto_intro",
            "msg_renovacao_proximo_vencimento",
            "msg_quitacao_garantia",
            "msg_segunda_via_confirma",
            "msg_neutra_padrao",
            "tpl_saudacao_cliente",
            "tpl_saudacao_cliente_com_pedido",
            "tpl_contrato_vencimento",
            "tpl_contrato_renovacao",
            "tpl_contrato_quitacao",
            "tpl_contrato_parcela",
            "tpl_contrato_resumo",
            "tpl_contrato_laudo",
            "tpl_lista_header",
            "tpl_intro_vencimento",
            "tpl_intro_renovacao",
            "tpl_intro_quitacao",
            "tpl_intro_parcela",
            "tpl_intro_lista",
            "tpl_intro_laudo",
            "tpl_totalizador",
            "tpl_totalizador_geral",
            "msg_fallback_sem_resposta",
            "msg_info_negada_desconhecido",
            "msg_midia_nao_suportada",
            "msg_duvida_anotada",
            "msg_pedir_campo_valor_filtro",
            "atualizado_em",
        ]
        read_only_fields = ["atualizado_em"]


class WritableFileField(serializers.FileField):
    def to_internal_value(self, data):
        if isinstance(data, str):
            cleaned = data
            for prefix in ["/media/", "media/"]:
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix) :]
            return cleaned
        return super().to_internal_value(data)


class FAQRespostaSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    arquivo = WritableFileField(required=False, allow_null=True)
    arquivo_url = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = FAQResposta
        fields = ["id", "ordem", "texto", "arquivo", "arquivo_url"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_arquivo_url(self, obj):
        if obj.arquivo:
            return obj.arquivo.url
        return None


class FAQSerializer(serializers.ModelSerializer):
    respostas = FAQRespostaSerializer(many=True, required=False)

    class Meta:
        model = FAQ
        fields = ["id", "pergunta", "ativo", "respostas"]

    def create(self, validated_data):
        respostas_data = validated_data.pop("respostas", [])
        faq = FAQ.objects.create(**validated_data)
        for resp_data in respostas_data:
            resp_data.pop("id", None)
            FAQResposta.objects.create(faq=faq, **resp_data)
        return faq

    def update(self, instance, validated_data):
        respostas_data = validated_data.pop("respostas", None)
        instance.pergunta = validated_data.get("pergunta", instance.pergunta)
        instance.ativo = validated_data.get("ativo", instance.ativo)
        instance.save()

        if respostas_data is not None:
            instance.respostas.all().delete()
            for r_data in respostas_data:
                r_data.pop("id", None)
                FAQResposta.objects.create(faq=instance, **r_data)
        return instance


class FAQSugeridaSerializer(serializers.ModelSerializer):
    revisado_por_nome = serializers.CharField(
        source="revisado_por.username", read_only=True, default=""
    )

    class Meta:
        model = FAQSugerida
        fields = [
            "id",
            "pergunta",
            "pergunta_original",
            "conversa",
            "ocorrencias",
            "status",
            "faq_criada",
            "revisado_por",
            "revisado_por_nome",
            "revisado_em",
            "criado_em",
        ]
        read_only_fields = [
            "pergunta_original",
            "conversa",
            "ocorrencias",
            "status",
            "faq_criada",
            "revisado_por",
            "revisado_em",
            "criado_em",
        ]


class FAQSugeridaAprovarRespostaSerializer(serializers.Serializer):
    ordem = serializers.IntegerField(required=False, default=0)
    texto = serializers.CharField(allow_blank=True, required=False, default="")


class FAQSugeridaAprovarSerializer(serializers.Serializer):
    pergunta_final = serializers.CharField(required=False, allow_blank=True)
    respostas = FAQSugeridaAprovarRespostaSerializer(many=True, required=False)


class ClienteMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cliente
        fields = ["cpf", "nome", "cidade"]


class TelefoneSerializer(serializers.ModelSerializer):
    class Meta:
        model = Telefone
        fields = ["id", "numero", "numero_bruto"]


class ContratoPenhorMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContratoPenhor
        fields = [
            "contrato",
            "situacao",
            "situacao_codigo",
            "vlr_liquido",
            "vlr_parcela_atualizada",
            "data_vencimento",
            "atraso",
            "laudo",
            "peso",
            "vlr_avaliacao",
            "vlr_emprestimo",
        ]


class ContratoPenhorSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContratoPenhor
        fields = "__all__"


class MensagemMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Mensagem
        fields = ["id", "direcao", "texto", "criado_em"]


class MensagemSerializer(serializers.ModelSerializer):
    possui_midia = serializers.SerializerMethodField()
    tipo_midia = serializers.SerializerMethodField()
    legenda = serializers.SerializerMethodField()

    class Meta:
        model = Mensagem
        fields = [
            "id",
            "direcao",
            "texto",
            "wa_message_id",
            "push_name",
            "payload_bruto",
            "criado_em",
            "possui_midia",
            "tipo_midia",
            "legenda",
        ]

    def _get_media_message_node(self, obj):
        from whatsapp.views import desembrulhar_no_mensagem

        payload = obj.payload_bruto or {}
        data = payload.get("data", {})
        message = desembrulhar_no_mensagem(data.get("message", {}))
        if not message:
            return None, None
        for key in ["imageMessage", "audioMessage", "documentMessage", "videoMessage"]:
            if key in message:
                return key, message[key]
        return None, None

    def get_possui_midia(self, obj) -> bool:
        media_type, _ = self._get_media_message_node(obj)
        return media_type is not None

    def get_tipo_midia(self, obj) -> str:
        media_type, _ = self._get_media_message_node(obj)
        if media_type == "imageMessage":
            return "image"
        elif media_type == "audioMessage":
            return "audio"
        elif media_type == "documentMessage":
            return "document"
        elif media_type == "videoMessage":
            return "video"
        return "text"

    def get_legenda(self, obj) -> str:
        _, media_node = self._get_media_message_node(obj)
        if media_node:
            return media_node.get("caption") or ""
        return ""


class MensagemPainelSerializer(serializers.ModelSerializer):
    """Serializer usado pelo painel (ConversaDetailSerializer.get_mensagens).
    Sem `payload_bruto` na saída (evita vazar o payload bruto da Evolution
    pro frontend). `tipo_midia`/`possui_midia`/`legenda` preferem o campo
    persistido `Mensagem.tipo_midia` (Fase 0); mensagens legadas sem esse
    campo caem no parse do payload_bruto, igual ao MensagemSerializer."""

    possui_midia = serializers.SerializerMethodField()
    tipo_midia = serializers.SerializerMethodField()
    legenda = serializers.SerializerMethodField()

    class Meta:
        model = Mensagem
        fields = [
            "id",
            "direcao",
            "texto",
            "wa_message_id",
            "push_name",
            "criado_em",
            "possui_midia",
            "tipo_midia",
            "legenda",
            "arquivo",
            "enviado_ok",
        ]

    def _get_media_message_node(self, obj):
        from whatsapp.views import desembrulhar_no_mensagem

        payload = obj.payload_bruto or {}
        data = payload.get("data", {})
        message = desembrulhar_no_mensagem(data.get("message", {}))
        if not message:
            return None, None
        for key in ["imageMessage", "audioMessage", "documentMessage", "videoMessage"]:
            if key in message:
                return key, message[key]
        return None, None

    def get_tipo_midia(self, obj) -> str:
        if obj.tipo_midia:
            return obj.tipo_midia
        # Fallback para mensagens legadas (anteriores à Fase 0) sem o campo persistido.
        media_type, _ = self._get_media_message_node(obj)
        mapa = {
            "imageMessage": "image",
            "audioMessage": "audio",
            "documentMessage": "document",
            "videoMessage": "video",
        }
        return mapa.get(media_type, "")

    def get_possui_midia(self, obj) -> bool:
        if obj.arquivo:
            return True
        return bool(self.get_tipo_midia(obj))

    def get_legenda(self, obj) -> str:
        # `texto` já guarda a legenda/caption (webhook extrai para `texto` em
        # _extrair_conteudo; operador digita a legenda em `texto` no envio de
        # arquivo). Fallback ao parse do payload só para mídia legada sem
        # `texto` preenchido (ex.: videoMessage com caption, extraído só
        # depois da Fase 0).
        if obj.texto:
            return obj.texto
        _, media_node = self._get_media_message_node(obj)
        if media_node:
            return media_node.get("caption") or ""
        return ""


class BoletoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Boleto
        fields = ["id", "arquivo", "linha_digitavel", "enviado_em", "criado_em"]
        read_only_fields = ["enviado_em", "criado_em"]


class BoletoDadosInputSerializer(serializers.Serializer):
    """Campos que `core.boleto_pdf.make_html` precisa pra montar o PDF do
    boleto — mesmos 8 campos que o brilhante já extrai do SIPEN via
    `liquidacao_funcoes.py`/`renovacao_funcoes.py`. Usado quando o brilhante
    manda os DADOS do boleto (em vez do PDF pronto) em
    `SolicitacaoViewSet.boletos`."""

    linha_digitavel = serializers.CharField(max_length=80)
    numero_documento = serializers.CharField(max_length=40)
    nosso_numero = serializers.CharField(max_length=40)
    vencimento = serializers.CharField(max_length=20)
    valor = serializers.CharField(max_length=30)
    nome = serializers.CharField(max_length=200)
    cpf = serializers.CharField(max_length=20)
    endereco = serializers.CharField(max_length=300, allow_blank=True, required=False, default="")


class SolicitacaoSerializer(serializers.ModelSerializer):
    cliente = ClienteMiniSerializer(read_only=True)
    contratos = ContratoPenhorMiniSerializer(many=True, read_only=True)
    boletos = BoletoSerializer(many=True, read_only=True)
    historico_mensagens = serializers.SerializerMethodField()

    class Meta:
        model = Solicitacao
        fields = [
            "id",
            "cliente",
            "conversa",
            "tipo",
            "escopo",
            "contratos",
            "prazo_dias",
            "status",
            "resposta_ia",
            "precisa_humano",
            "boletos",
            "historico_mensagens",
            "criado_em",
            "atualizado_em",
        ]
        read_only_fields = [f for f in fields if f != "status"]

    @extend_schema_field(MensagemMiniSerializer(many=True))
    def get_historico_mensagens(self, obj):
        if not obj.conversa_id:
            return []
        mensagens = obj.conversa.mensagens.order_by("-criado_em")[:10]
        return MensagemMiniSerializer(reversed(mensagens), many=True).data


class SolicitacaoUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Solicitacao
        fields = ["status"]


class ConversaListSerializer(serializers.ModelSerializer):
    cliente_nome = serializers.CharField(source="cliente.nome", read_only=True)
    cliente_cpf = serializers.CharField(source="cliente.cpf", read_only=True)
    num_contratos_ativos = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Conversa
        fields = [
            "id",
            "remote_jid",
            "estado",
            "tipo_contato",
            "nome_salvo",
            "cpf_verificado",
            "precisa_revisao_humana",
            "ultima_interacao",
            "cliente_nome",
            "cliente_cpf",
            "num_contratos_ativos",
        ]


class ConversaDetailSerializer(serializers.ModelSerializer):
    cliente = ClienteMiniSerializer(read_only=True)
    mensagens = serializers.SerializerMethodField()
    solicitacoes = serializers.SerializerMethodField()

    class Meta:
        model = Conversa
        fields = [
            "id",
            "remote_jid",
            "estado",
            "tipo_contato",
            "nome_salvo",
            "cpf_verificado",
            "precisa_revisao_humana",
            "ultima_interacao",
            "cliente",
            "mensagens",
            "solicitacoes",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.JSONField()))
    def get_mensagens(self, obj):
        msgs = obj.mensagens.all().order_by("criado_em")
        return MensagemPainelSerializer(msgs, many=True, context=self.context).data

    @extend_schema_field(serializers.ListField(child=serializers.JSONField()))
    def get_solicitacoes(self, obj):
        return SolicitacaoSerializer(obj.solicitacoes.all(), many=True).data


class ClienteListSerializer(serializers.ModelSerializer):
    num_telefones = serializers.IntegerField(read_only=True, default=0)
    num_conversas = serializers.IntegerField(read_only=True, default=0)
    num_contratos_ativos = serializers.IntegerField(read_only=True, default=0)
    total_emprestimo_ativo = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, default=0
    )
    total_avaliacao_ativo = serializers.DecimalField(
        max_digits=14, decimal_places=2, read_only=True, default=0
    )

    class Meta:
        model = Cliente
        fields = [
            "cpf",
            "nome",
            "cidade",
            "bloqueado_ia",
            "bloqueado_motivo",
            "bloqueado_em",
            "num_telefones",
            "num_conversas",
            "limite_especial",
            "num_contratos_ativos",
            "total_emprestimo_ativo",
            "total_avaliacao_ativo",
        ]


class ClienteDetailSerializer(serializers.ModelSerializer):
    telefones = TelefoneSerializer(many=True, read_only=True)
    contratos_penhor = ContratoPenhorMiniSerializer(many=True, read_only=True)
    conversas = serializers.SerializerMethodField()
    solicitacoes = serializers.SerializerMethodField()

    class Meta:
        model = Cliente
        fields = [
            "cpf",
            "nome",
            "situacao_cpf",
            "situacao_cadastro",
            "logradouro",
            "bairro",
            "cidade",
            "cep",
            "aniversario",
            "bloqueado_ia",
            "bloqueado_motivo",
            "bloqueado_em",
            "telefones",
            "contratos_penhor",
            "conversas",
            "solicitacoes",
        ]

    @extend_schema_field(serializers.ListField(child=serializers.JSONField()))
    def get_conversas(self, obj):
        return ConversaListSerializer(obj.conversas.all(), many=True).data

    @extend_schema_field(serializers.ListField(child=serializers.JSONField()))
    def get_solicitacoes(self, obj):
        return SolicitacaoSerializer(obj.solicitacoes.all(), many=True).data
