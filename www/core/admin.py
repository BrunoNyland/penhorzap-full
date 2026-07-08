from django.contrib import admin

from .models import (
    AgenciaPenhor,
    Boleto,
    BotConfig,
    Cliente,
    Conversa,
    ContratoPenhor,
    FAQ,
    FAQResposta,
    Licitacao,
    Mensagem,
    MensagensConfig,
    Solicitacao,
    Telefone,
)


class TelefoneInline(admin.TabularInline):
    model = Telefone
    extra = 0


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("cpf", "nome", "cidade", "situacao_cpf", "situacao_cadastro", "boleto_emitido", "bloqueado_ia")
    list_filter = ("situacao_cpf", "situacao_cadastro", "cidade", "bloqueado_ia")
    search_fields = ("cpf", "nome")
    inlines = [TelefoneInline]


@admin.register(ContratoPenhor)
class ContratoPenhorAdmin(admin.ModelAdmin):
    list_display = (
        "contrato",
        "cliente",
        "situacao",
        "situacao_codigo",
        "vlr_emprestimo",
        "vlr_liquido",
        "data_emissao",
        "atraso",
    )
    list_filter = ("situacao_codigo", "modalidade", "parcelado")
    search_fields = ("contrato", "cliente__cpf", "cliente__nome")
    autocomplete_fields = ["cliente"]


@admin.register(AgenciaPenhor)
class AgenciaPenhorAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nome", "uf", "cidade", "situacao")
    list_filter = ("uf", "situacao", "tipo")
    search_fields = ("codigo", "nome")


@admin.register(Licitacao)
class LicitacaoAdmin(admin.ModelAdmin):
    list_display = ("numero", "situacao", "uf", "data")


@admin.register(Conversa)
class ConversaAdmin(admin.ModelAdmin):
    list_display = ("id", "remote_jid", "cliente", "estado", "precisa_revisao_humana", "ultima_interacao")
    list_filter = ("estado", "precisa_revisao_humana")
    search_fields = ("remote_jid", "cliente__cpf", "cliente__nome")


@admin.register(Mensagem)
class MensagemAdmin(admin.ModelAdmin):
    list_display = ("id", "conversa", "direcao", "texto", "criado_em")
    list_filter = ("direcao",)
    search_fields = ("texto", "wa_message_id", "conversa__remote_jid")


@admin.register(Solicitacao)
class SolicitacaoAdmin(admin.ModelAdmin):
    list_display = ("id", "cliente", "tipo", "escopo", "status", "precisa_humano", "criado_em")
    list_filter = ("tipo", "status", "escopo", "precisa_humano")
    search_fields = ("cliente__cpf", "cliente__nome")
    filter_horizontal = ("contratos",)


@admin.register(Boleto)
class BoletoAdmin(admin.ModelAdmin):
    list_display = ("id", "solicitacao", "arquivo", "linha_digitavel", "enviado_em", "criado_em")
    list_filter = ("enviado_em",)


class FAQRespostaInline(admin.TabularInline):
    model = FAQResposta
    extra = 1


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ("pergunta", "ativo")
    list_filter = ("ativo",)
    search_fields = ("pergunta",)
    inlines = [FAQRespostaInline]


@admin.register(BotConfig)
class BotConfigAdmin(admin.ModelAdmin):
    list_display = ("ativo", "atualizado_em")

    def has_add_permission(self, request):
        return not BotConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MensagensConfig)
class MensagensConfigAdmin(admin.ModelAdmin):
    list_display = ("__str__", "atualizado_em")

    def has_add_permission(self, request):
        return not MensagensConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
