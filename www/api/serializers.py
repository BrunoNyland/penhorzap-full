from django.contrib.auth.models import User
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.models import (
    Boleto,
    Cliente,
    ContratoPenhor,
    Mensagem,
    Solicitacao,
    BotConfig,
    MensagensConfig,
    FAQ,
    FAQResposta,
    Telefone,
    Conversa,
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
            "horario_encerramento",
            "responder_desconhecidos",
            "dias_resgate_garantia",
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
            "msg_cadastro_nao_localizado",
            "msg_pedir_cpf",
            "msg_cpf_invalido",
            "msg_cpf_nao_bate",
            "msg_verificacao_ok",
            "msg_verificacao_falhou",
            "msg_sem_info_faq",
            "msg_db_desatualizada",
            "msg_sem_contratos_ativos",
            "msg_solicitacao_criada",
            "msg_boleto_intro",
            "msg_renovacao_proximo_vencimento",
            "msg_quitacao_garantia",
            "msg_segunda_via_confirma",
            "msg_insistiu_humano",
            "msg_neutra_padrao",
            "atualizado_em",
        ]
        read_only_fields = ["atualizado_em"]


class WritableFileField(serializers.FileField):
    def to_internal_value(self, data):
        if isinstance(data, str):
            cleaned = data
            for prefix in ["/media/", "media/"]:
                if cleaned.startswith(prefix):
                    cleaned = cleaned[len(prefix):]
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
        ]


class BoletoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Boleto
        fields = ["id", "arquivo", "linha_digitavel", "enviado_em", "criado_em"]
        read_only_fields = ["enviado_em", "criado_em"]


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
        return MensagemMiniSerializer(msgs, many=True).data

    @extend_schema_field(serializers.ListField(child=serializers.JSONField()))
    def get_solicitacoes(self, obj):
        return SolicitacaoSerializer(obj.solicitacoes.all(), many=True).data


class ClienteListSerializer(serializers.ModelSerializer):
    num_telefones = serializers.IntegerField(read_only=True, default=0)
    num_conversas = serializers.IntegerField(read_only=True, default=0)

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
