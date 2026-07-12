import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.db.models.functions import ExtractDay, ExtractWeekDay, TruncDate
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.mensagens_defaults import (
    DEFAULT_MSG_BOLETO_INTRO,
    DEFAULT_MSG_CADASTRO_NAO_LOCALIZADO,
    DEFAULT_MSG_CPF_INVALIDO,
    DEFAULT_MSG_CPF_NAO_BATE,
    DEFAULT_MSG_DB_DESATUALIZADA,
    DEFAULT_MSG_INSISTIU_HUMANO,
    DEFAULT_MSG_NEUTRA_PADRAO,
    DEFAULT_MSG_PEDIR_CPF,
    DEFAULT_MSG_QUITACAO_GARANTIA,
    DEFAULT_MSG_RENOVACAO_PROXIMO_VENCIMENTO,
    DEFAULT_MSG_SAUDACAO,
    DEFAULT_MSG_SEM_CONTRATOS_ATIVOS,
    DEFAULT_MSG_SEM_INFO_FAQ,
    DEFAULT_MSG_SEGUNDA_VIA_CONFIRMA,
    DEFAULT_MSG_SOLICITACAO_CRIADA,
    DEFAULT_MSG_VERIFICACAO_FALHOU,
    DEFAULT_MSG_VERIFICACAO_OK,
    DEFAULT_SYSTEM_PROMPT,
)
from core.models import Boleto, BotConfig, Cliente, Conversa, ContratoPenhor, FAQ, Mensagem, MensagensConfig, Solicitacao
from ia.services import extrair_intencao
from whatsapp.tasks import HISTORICO_TAMANHO

from .forms import BotConfigForm, FAQForm, FAQRespostaFormSet, MensagensConfigForm

logger = logging.getLogger(__name__)

DIAS_SEMANA_PT = {1: "Domingo", 2: "Segunda", 3: "Terça", 4: "Quarta", 5: "Quinta", 6: "Sexta", 7: "Sábado"}

SIMULADOR_SESSION_KEY = "simulador_ia"

MENSAGENS_DEFAULTS = {
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "msg_saudacao": DEFAULT_MSG_SAUDACAO,
    "msg_cadastro_nao_localizado": DEFAULT_MSG_CADASTRO_NAO_LOCALIZADO,
    "msg_pedir_cpf": DEFAULT_MSG_PEDIR_CPF,
    "msg_cpf_invalido": DEFAULT_MSG_CPF_INVALIDO,
    "msg_cpf_nao_bate": DEFAULT_MSG_CPF_NAO_BATE,
    "msg_verificacao_ok": DEFAULT_MSG_VERIFICACAO_OK,
    "msg_verificacao_falhou": DEFAULT_MSG_VERIFICACAO_FALHOU,
    "msg_sem_info_faq": DEFAULT_MSG_SEM_INFO_FAQ,
    "msg_db_desatualizada": DEFAULT_MSG_DB_DESATUALIZADA,
    "msg_sem_contratos_ativos": DEFAULT_MSG_SEM_CONTRATOS_ATIVOS,
    "msg_solicitacao_criada": DEFAULT_MSG_SOLICITACAO_CRIADA,
    "msg_boleto_intro": DEFAULT_MSG_BOLETO_INTRO,
    "msg_renovacao_proximo_vencimento": DEFAULT_MSG_RENOVACAO_PROXIMO_VENCIMENTO,
    "msg_quitacao_garantia": DEFAULT_MSG_QUITACAO_GARANTIA,
    "msg_segunda_via_confirma": DEFAULT_MSG_SEGUNDA_VIA_CONFIRMA,
    "msg_insistiu_humano": DEFAULT_MSG_INSISTIU_HUMANO,
    "msg_neutra_padrao": DEFAULT_MSG_NEUTRA_PADRAO,
}

# Campos do novo fluxo exibidos genericamente na tela de Mensagens & Prompt.
NOVOS_CAMPOS = [
    ("msg_saudacao", "Saudação (desconhecido)", "Saudação inicial p/ contatos não salvos. Use {saudacao}."),
    ("msg_cpf_invalido", "CPF inválido", "Cliente digitou um CPF com checksum inválido."),
    ("msg_cpf_nao_bate", "CPF não bate", "CPF digitado não confere com o do contato salvo/cadastro."),
    ("msg_sem_info_faq", "Sem info na FAQ", "Dúvida geral sem resposta na FAQ: pede CPF e diz que vai verificar."),
    ("msg_db_desatualizada", "Database desatualizada", "Database fora da validade: pede CPF e diz que vai verificar."),
    ("msg_sem_contratos_ativos", "Sem contratos ativos", "Cliente sem contratos ativos no momento."),
    ("msg_solicitacao_criada", "Solicitação criada", "Confirmado: boleto(s) serão gerados e enviados por aqui."),
    ("msg_renovacao_proximo_vencimento", "Renovação: próximo vencimento", "Use {proximo_vencimento}."),
    ("msg_quitacao_garantia", "Quitação: resgate de garantias", "Use {data_resgate}."),
    ("msg_segunda_via_confirma", "2ª via: confirmação", "Use {contratos} e {tipo}."),
    ("msg_insistiu_humano", "Insistiu (humano)", "Cliente refez a mesma pergunta sem resposta: defere."),
]


@staff_member_required
def dashboard(request):
    hoje = timezone.localdate()
    inicio_30 = hoje - timedelta(days=29)
    inicio_180 = hoje - timedelta(days=180)

    # Solicitações por tipo/status
    tipo_labels = dict(Solicitacao.Tipo.choices)
    status_labels = dict(Solicitacao.Status.choices)
    por_tipo = list(Solicitacao.objects.values("tipo").annotate(total=Count("id")).order_by("tipo"))
    for row in por_tipo:
        row["label"] = tipo_labels.get(row["tipo"], row["tipo"])
    por_status = list(Solicitacao.objects.values("status").annotate(total=Count("id")).order_by("status"))
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
        mapa_mensagens.setdefault(row["dia"], {"in": 0, "out": 0})[row["direcao"]] = row["total"]

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
        serie_30_dias.append({
            "dia": dia,
            "recebidas": recebidas,
            "enviadas": enviadas,
            "conversas_novas": mapa_conversas_novas.get(dia, 0),
            "boletos_enviados": mapa_boletos.get(dia, 0),
        })
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

    # Padrões sazonais (janela de 180 dias)
    janela_qs = Mensagem.objects.filter(criado_em__date__gte=inicio_180)
    por_dia_semana_raw = list(
        janela_qs.annotate(dow=ExtractWeekDay("criado_em")).values("dow").annotate(total=Count("id"))
    )
    mapa_semana = {row["dow"]: row["total"] for row in por_dia_semana_raw}
    por_dia_semana = [
        {"label": DIAS_SEMANA_PT[dow], "total": mapa_semana.get(dow, 0)} for dow in range(1, 8)
    ]
    maior_valor_semana = max([row["total"] for row in por_dia_semana] + [1])

    por_dia_mes_raw = list(
        janela_qs.annotate(dom=ExtractDay("criado_em")).values("dom").annotate(total=Count("id"))
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

    context = {
        "active_nav": "dashboard",
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
    }
    return render(request, "painel/dashboard.html", context)


# --- Mensagens & Prompt -------------------------------------------------------


@staff_member_required
def mensagens_config(request):
    config = MensagensConfig.get_solo()

    if request.method == "POST":
        acao = request.POST.get("acao")

        if acao == "restaurar":
            campo = request.POST.get("campo", "")
            if campo in MENSAGENS_DEFAULTS:
                setattr(config, campo, MENSAGENS_DEFAULTS[campo])
                config.save(update_fields=[campo, "atualizado_em"])
                messages.success(request, "Campo restaurado ao padrão.")
            else:
                messages.error(request, "Campo inválido para restaurar.")
            return redirect("painel:mensagens_config")

        form = MensagensConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Mensagens & Prompt atualizados com sucesso.")
            return redirect("painel:mensagens_config")
    else:
        form = MensagensConfigForm(instance=config)

    # Pré-renderiza os campos novos (Django templates não acessam bound fields
    # por nome dinâmico nativamente) -> entregamos o HTML pronto ao template.
    novos_renderizados = [
        {"campo": c, "rotulo": r, "ajuda": a, "html": str(form[c])}
        for c, r, a in NOVOS_CAMPOS
    ]

    return render(request, "painel/mensagens_config.html", {
        "form": form,
        "campos_restauraveis": list(MENSAGENS_DEFAULTS.keys()),
        "novos_campos": novos_renderizados,
        "active_nav": "mensagens",
    })


# --- Configuração do bot ------------------------------------------------------


@staff_member_required
def bot_config(request):
    config = BotConfig.get_solo()
    if request.method == "POST":
        form = BotConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Configuração do bot atualizada.")
            return redirect("painel:bot_config")
    else:
        form = BotConfigForm(instance=config)
    return render(request, "painel/bot_config.html", {
        "form": form,
        "config": config,
        "active_nav": "bot_config",
    })


# --- FAQ --------------------------------------------------------------------


@staff_member_required
def faq_list(request):
    faqs = FAQ.objects.all().order_by("pergunta")
    return render(request, "painel/faq_list.html", {"faqs": faqs, "active_nav": "faqs"})


@staff_member_required
def faq_create(request):
    if request.method == "POST":
        form = FAQForm(request.POST)
        formset = FAQRespostaFormSet(request.POST, request.FILES)
        if form.is_valid() and formset.is_valid():
            faq = form.save()
            formset.instance = faq
            formset.save()
            messages.success(request, "FAQ criada com sucesso.")
            return redirect("painel:faq_list")
    else:
        form = FAQForm()
        formset = FAQRespostaFormSet()
    return render(
        request,
        "painel/faq_form.html",
        {"form": form, "formset": formset, "titulo": "Nova FAQ", "active_nav": "faqs"}
    )


@staff_member_required
def faq_update(request, pk):
    faq = get_object_or_404(FAQ, pk=pk)
    if request.method == "POST":
        form = FAQForm(request.POST, instance=faq)
        formset = FAQRespostaFormSet(request.POST, request.FILES, instance=faq)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, "FAQ atualizada com sucesso.")
            return redirect("painel:faq_list")
    else:
        form = FAQForm(instance=faq)
        formset = FAQRespostaFormSet(instance=faq)
    return render(
        request,
        "painel/faq_form.html",
        {"form": form, "formset": formset, "titulo": "Editar FAQ", "active_nav": "faqs"}
    )


@staff_member_required
def faq_delete(request, pk):
    faq = get_object_or_404(FAQ, pk=pk)
    if request.method == "POST":
        faq.delete()
        messages.success(request, "FAQ excluída.")
        return redirect("painel:faq_list")
    return render(request, "painel/faq_confirm_delete.html", {"faq": faq, "active_nav": "faqs"})


@staff_member_required
@require_POST
def faq_toggle_ativo(request, pk):
    faq = get_object_or_404(FAQ, pk=pk)
    faq.ativo = not faq.ativo
    faq.save(update_fields=["ativo"])
    return redirect("painel:faq_list")


# --- Clientes -----------------------------------------------------------------


@staff_member_required
def cliente_list(request):
    q = request.GET.get("q", "").strip()
    bloqueado = request.GET.get("bloqueado")

    clientes = Cliente.objects.annotate(
        num_telefones=Count("telefones", distinct=True),
        num_conversas=Count("conversas", distinct=True),
    ).order_by("nome")

    if q:
        clientes = clientes.filter(Q(cpf__icontains=q) | Q(nome__icontains=q))
    if bloqueado == "1":
        clientes = clientes.filter(bloqueado_ia=True)

    paginator = Paginator(clientes, 25)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "painel/cliente_list.html", {
        "page_obj": page,
        "q": q,
        "bloqueado": bloqueado,
        "active_nav": "clientes",
    })


@staff_member_required
def cliente_detail(request, cpf):
    cliente = get_object_or_404(
        Cliente.objects.prefetch_related(
            "telefones", "contratos_penhor", "conversas", "solicitacoes__contratos"
        ),
        cpf=cpf,
    )
    conversas = cliente.conversas.order_by("-ultima_interacao")
    solicitacoes = cliente.solicitacoes.all()
    return render(request, "painel/cliente_detail.html", {
        "cliente": cliente,
        "conversas": conversas,
        "solicitacoes": solicitacoes,
        "active_nav": "clientes",
    })


@staff_member_required
@require_POST
def cliente_toggle_bloqueio(request, cpf):
    cliente = get_object_or_404(Cliente, cpf=cpf)
    acao = request.POST.get("acao")
    if acao == "bloquear":
        cliente.bloqueado_ia = True
        cliente.bloqueado_motivo = request.POST.get("motivo", "").strip()
        cliente.bloqueado_em = timezone.now()
        cliente.save(update_fields=["bloqueado_ia", "bloqueado_motivo", "bloqueado_em"])
        messages.success(request, "Cliente bloqueado para respostas automáticas da IA.")
    elif acao == "desbloquear":
        cliente.bloqueado_ia = False
        cliente.bloqueado_motivo = ""
        cliente.bloqueado_em = None
        cliente.save(update_fields=["bloqueado_ia", "bloqueado_motivo", "bloqueado_em"])
        messages.success(request, "Cliente desbloqueado.")
    return redirect("painel:cliente_detail", cpf=cpf)


# --- Atendimentos (conversas) -------------------------------------------------


@staff_member_required
def atendimento_list(request):
    estado = request.GET.get("estado", "")
    revisao = request.GET.get("revisao")
    q = request.GET.get("q", "").strip()

    conversas = Conversa.objects.select_related("cliente").order_by("-ultima_interacao")

    if estado in Conversa.Estado.values:
        conversas = conversas.filter(estado=estado)
    if revisao == "1":
        conversas = conversas.filter(precisa_revisao_humana=True)
    if q:
        conversas = conversas.filter(
            Q(remote_jid__icontains=q) | Q(cliente__cpf__icontains=q) | Q(cliente__nome__icontains=q)
        )

    paginator = Paginator(conversas, 25)
    page = paginator.get_page(request.GET.get("page"))

    return render(request, "painel/atendimento_list.html", {
        "page_obj": page,
        "estado": estado,
        "revisao": revisao,
        "q": q,
        "estados": Conversa.Estado.choices,
        "active_nav": "atendimentos",
    })


@staff_member_required
def atendimento_detail(request, pk):
    conversa = get_object_or_404(Conversa.objects.select_related("cliente"), pk=pk)
    mensagens = conversa.mensagens.all()
    solicitacoes = conversa.solicitacoes.all()
    return render(request, "painel/atendimento_detail.html", {
        "conversa": conversa,
        "mensagens": mensagens,
        "solicitacoes": solicitacoes,
        "active_nav": "atendimentos",
    })


# --- Simulador IA --------------------------------------------------------------


def _simulador_estado(request):
    estado = request.session.get(SIMULADOR_SESSION_KEY)
    if estado is None:
        estado = {"cliente_cpf": None, "turnos": []}
        request.session[SIMULADOR_SESSION_KEY] = estado
    return estado


@staff_member_required
def simulador_chat(request):
    estado = _simulador_estado(request)

    if request.method == "POST":
        acao = request.POST.get("acao")

        if acao == "enviar":
            texto = request.POST.get("mensagem", "").strip()
            if texto:
                cliente = None
                if estado["cliente_cpf"]:
                    cliente = Cliente.buscar_por_cpf(estado["cliente_cpf"])

                historico = [
                    {"direcao": turno["direcao"], "texto": turno["texto"]}
                    for turno in estado["turnos"][-HISTORICO_TAMANHO:]
                ]
                contratos_cliente = []
                if cliente is not None:
                    # Mesmo filtro do bot: só ativos, só campos permitidos.
                    from whatsapp.tasks import _contratos_ativos_values
                    contratos_cliente = _contratos_ativos_values(cliente)
                faqs = list(FAQ.objects.filter(ativo=True).values("id", "pergunta"))

                resultado = extrair_intencao(
                    texto,
                    historico,
                    contratos_cliente,
                    faqs,
                    cpf_verificado=True,
                    db_atualizada=True,
                    contato_tipo="cliente",
                    cliente_cpf=cliente.cpf if cliente else "",
                    cliente_nome=cliente.nome if cliente else "",
                )

                estado["turnos"].append({"direcao": "in", "texto": texto})
                estado["turnos"].append({
                    "direcao": "out",
                    "texto": resultado.resposta_sugerida,
                    "debug": {
                        "tipo_intencao": resultado.tipo_intencao.value,
                        "precisa_humano": resultado.precisa_humano,
                        "solicitacoes": [s.model_dump() for s in resultado.solicitacoes],
                        "pronto_para_criar_solicitacao": resultado.pronto_para_criar_solicitacao,
                        "cpf_extraido": resultado.cpf_extraido,
                        "duvida_cliente": resultado.duvida_cliente,
                    },
                })
                request.session.modified = True

        elif acao == "reiniciar":
            estado["turnos"] = []
            request.session.modified = True

        elif acao == "selecionar_cliente":
            cpf = request.POST.get("cpf", "").strip()
            cli_obj = Cliente.buscar_por_cpf(cpf) if cpf else None
            if cli_obj:
                estado["cliente_cpf"] = cli_obj.cpf
                estado["turnos"] = []
                request.session.modified = True

        elif acao == "remover_cliente":
            estado["cliente_cpf"] = None
            estado["turnos"] = []
            request.session.modified = True

        return redirect("painel:simulador_chat")

    cliente = None
    if estado["cliente_cpf"]:
        cliente = Cliente.buscar_por_cpf(estado["cliente_cpf"])

    q = request.GET.get("q", "").strip()
    resultados_busca = []
    if cliente is None and q:
        resultados_busca = Cliente.objects.filter(
            Q(cpf__icontains=q) | Q(nome__icontains=q)
        ).order_by("nome")[:10]

    return render(request, "painel/simulador.html", {
        "cliente": cliente,
        "turnos": estado["turnos"],
        "q": q,
        "resultados_busca": resultados_busca,
        "active_nav": "simulador",
    })
