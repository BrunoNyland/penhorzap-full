"""Motor de conversa do bot penhorzap (executado pelo django-q2).

Fluxo por mensagem (process_mensagem):
  0. Lock leve por conversa (`Conversa.processando_desde`): evita que duas
     tasks concorrentes (ex.: replay + webhook) processem a mesma conversa
     ao mesmo tempo. Coalescência: se já existe uma mensagem IN mais nova na
     mesma conversa, esta task aborta sem responder (a mais nova cobre).
  1. Classifica o contato (cliente PHN_/telefone cadastrado / pessoal /
     desconhecido) via Telefone + ContatoSalvo (sync da agenda) + pushName.
     Cliente reconhecido por telefone -> `identificacao="telefone"`, nunca
     expira; primeira interação -> saudação nominal e encerra o turno.
  2. Contato pessoal -> ignora (o dono responde). Desconhecido sem resposta
     prévia -> saúda conforme o horário.
  3. Cliente bloqueado -> armazena, marca humana, sem responder.
  4. Mídia sem texto (áudio/vídeo/etc.) -> mensagem de "não suportado" +
     revisão humana, sem chamar a IA.
  5. Se o cliente digitou um CPF nesta mensagem: valida em Python; se
     inválido pede de novo, se não bate com o cadastro pede o correto, senão
     marca `identificacao="cpf"` (expira em 24h) e segue.
  6. Chama a IA (classificador puro, NUNCA redige texto) com ESTADO
     (identificado, database_atualizada, contato_tipo) e os CONTRATOS ATIVOS
     — que só são passados se identificado E database fresca (garantia dura:
     a IA nunca vê dados desatualizados/de terceiro).
  7. Gates pós-IA em Python: exige identificação p/ info_contrato/pagamento/
     segunda_via; exige database fresca p/ info_contrato/pagamento;
     desconhecido identificado por CPF pedindo info_contrato -> só boleto
     (nega dado fora dele).
  8. Ações determinísticas: cria Solicitação(ões) quando pronto; pergunta de
     slot quando falta dado; renderiza template de contrato; responde FAQ;
     segunda via clona a última solicitação com boleto do dia anterior;
     fallback registra FAQSugerida + marca revisão.
"""
import logging
import os
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.models import (
    BotConfig,
    Cliente,
    ContratoPenhor,
    Conversa,
    ContatoSalvo,
    FAQ,
    FAQResposta,
    FAQSugerida,
    Mensagem,
    MensagensConfig,
    Solicitacao,
    Telefone,
)
from core.utils import normalizar_cpf, normalize_phone_br, parse_nome_salvo, validar_cpf
from ia.schemas import TipoIntencaoV2, TipoPagamento
from ia.services import extrair_intencao

from .evolution_client import get_client
from .respostas_contrato import formatar_data, formatar_moeda, render_template, renderizar_infos_contrato

logger = logging.getLogger(__name__)

HISTORICO_TAMANHO = 10
VERIFICACAO_VALIDADE = timedelta(hours=24)
JANELA_NAO_LIDAS = timedelta(hours=24)
LOCK_TIMEOUT = timedelta(seconds=60)
REAGENDAR_ATRASO = timedelta(seconds=5)
PRAZOS_RENOVACAO = (30, 60, 90, 120, 150, 180)

# Situações (código) que representam contrato liquidado -> não ativo.
SITUACOES_LIQUIDADAS_COD = {"AVAL", "AVCL", "LQ", "LQDE", "LQSD", "LQVL", "OBJA", "SJLQ", "ER", ""}

TIPO_PAGAMENTO_TO_SOLICITACAO = {
    TipoPagamento.RENOVAR: Solicitacao.Tipo.RENOVAR,
    TipoPagamento.QUITAR: Solicitacao.Tipo.QUITAR,
    TipoPagamento.PARCELA: Solicitacao.Tipo.PARCELA,
}


def _remote_jid_para_numero(remote_jid: str) -> str | None:
    numero = remote_jid.split("@", 1)[0] if remote_jid else ""
    return normalize_phone_br(numero)


def _saudacao() -> str:
    h = timezone.localtime().hour
    if h < 12:
        return "Bom dia"
    if h < 18:
        return "Boa tarde"
    return "Boa noite"


def _extrair_cpf_texto(texto: str, permitir_cru: bool = False) -> str:
    """Extrai um token de 11 dígitos (CPF) da mensagem.

    CPF formatado (com pelo menos um "." ou "-") conta SEMPRE. Uma sequência
    "crua" de 11 dígitos (sem nenhuma formatação) só conta como CPF quando
    `permitir_cru=True` -- evita o falso positivo de qualquer número de 11
    dígitos colado na mensagem (telefone, contrato etc.) virar CPF fora do
    fluxo de verificação (o chamador só passa `permitir_cru=True` quando
    `conv.estado == AGUARDANDO_VERIFICACAO`). Não valida o checksum -- só
    detecta que parece um CPF; a validação fica a cargo de `validar_cpf`.
    """
    if not texto:
        return ""
    m = re.search(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}", texto)
    if m:
        bruto = m.group(0)
        digits = re.sub(r"\D", "", bruto)
        if len(digits) == 11:
            formatado = ("." in bruto) or ("-" in bruto)
            if formatado or permitir_cru:
                return digits
    return ""


def _buscar_cliente_por_cpf(cpf_digits: str):
    """Tenta achar um Cliente pelo CPF de forma flexível."""
    return Cliente.buscar_por_cpf(cpf_digits)

def _buscar_telefone_flexivel(numero_normalizado: str):
    """Busca um objeto Telefone de forma flexível, considerando que o número no
    banco de dados ou no WhatsApp pode estar com ou sem o nono dígito (9).

    numero_normalizado exemplo: '+556792330009' ou '+5567992330009'
    """
    if not numero_normalizado:
        return None

    # Remove o prefixo '+' e '55' (se for do Brasil) para analisar DDD e número
    clean = numero_normalizado.lstrip("+")
    if clean.startswith("55"):
        clean = clean[2:]

    # Se não tiver DDD + número (mínimo 10 dígitos), faz busca exata
    if len(clean) not in (10, 11):
        return Telefone.objects.select_related("cliente").filter(numero=numero_normalizado).first()

    ddd = clean[:2]
    local = clean[2:]

    variacoes = [numero_normalizado]

    if len(clean) == 10:
        # WhatsApp sem o 9 (ex: 6792330009). Variação com o 9: +5567992330009
        variacoes.append(f"+55{ddd}9{local}")
    elif len(clean) == 11:
        # WhatsApp com o 9 (ex: 67992330009). Variação sem o 9: +556792330009
        if local.startswith("9"):
            variacoes.append(f"+55{ddd}{local[1:]}")

    # Busca por qualquer uma das variações geradas no banco
    return Telefone.objects.select_related("cliente").filter(numero__in=variacoes).first()


def _classificar_contato(conv: Conversa, push_name: str = ""):
    """Retorna (tipo_contato, nome_salvo, cliente).

    Prioridade: Telefone (match por número flexível) > ContatoSalvo (agenda sincronizada)
    > pushName do webhook. PHN_CPF_NOME no nome salvo = cliente.

    Quando o ContatoSalvo existe mas tem nome vazio (bug conhecido da
    Evolution API v2 que apaga pushName), usa o pushName do webhook como
    nome de exibição, preservando o tipo/classificação do ContatoSalvo."""
    numero = _remote_jid_para_numero(conv.remote_jid)
    tel = _buscar_telefone_flexivel(numero) if numero else None
    cliente = tel.cliente if tel else None
    push = (push_name or "").strip()

    # Se o número de telefone já está no cadastro de clientes, é SEMPRE cliente!
    if cliente:
        cs = ContatoSalvo.objects.filter(remote_jid=conv.remote_jid).first()
        nome_salvo = (cs.nome_salvo if cs else "") or push
        return Conversa.TipoContato.CLIENTE, nome_salvo, cliente

    # Caso contrário, segue os fallbacks baseados na agenda sincronizada
    cs = ContatoSalvo.objects.filter(remote_jid=conv.remote_jid).first()
    if cs:
        # Usa o nome do ContatoSalvo; se vazio (bug da API), usa pushName do webhook.
        nome_salvo = cs.nome_salvo or push
        if cs.tipo == ContatoSalvo.Tipo.PESSOAL:
            return Conversa.TipoContato.PESSOAL, nome_salvo, None
        # CLIENTE (via prefixo PH_ na agenda)
        if cs.cpf:
            cliente = _buscar_cliente_por_cpf(cs.cpf)
        return Conversa.TipoContato.CLIENTE, nome_salvo, cliente

    # fallback: pushName do webhook (nome de perfil / salvo informado no payload)
    cpf_nome, _ = parse_nome_salvo(push)
    if push:
        if cpf_nome:
            return Conversa.TipoContato.CLIENTE, push, _buscar_cliente_por_cpf(cpf_nome)
        return Conversa.TipoContato.PESSOAL, push, None

    return Conversa.TipoContato.DESCONHECIDO, "", None


def classificar_e_atualizar_conversa(conv: Conversa, push_name: str = ""):
    """Classifica o contato e atualiza nome_salvo, tipo_contato, cliente na
    conversa. Segura para chamar do webhook mesmo com o bot desligado — não
    dispara fluxo de IA, apenas preenche metadados de exibição.

    Também preenche ContatoSalvo.nome_salvo a partir do pushName do webhook
    quando o campo está vazio (backfill do bug da Evolution API)."""
    push = (push_name or "").strip()

    # Backfill: se o ContatoSalvo tem nome vazio e temos um pushName do webhook,
    # atualiza o cache para que futuras consultas já tenham o nome.
    if push:
        cs = ContatoSalvo.objects.filter(remote_jid=conv.remote_jid, nome_salvo="").first()
        if cs:
            cs.nome_salvo = push[:255]
            cs.save(update_fields=["nome_salvo", "atualizado_em"])

    tipo_contato, nome_salvo, cliente = _classificar_contato(conv, push_name)
    update_fields = ["ultima_interacao"]
    if conv.nome_salvo != nome_salvo:
        conv.nome_salvo = nome_salvo
        update_fields.append("nome_salvo")
    if conv.tipo_contato != tipo_contato:
        conv.tipo_contato = tipo_contato
        update_fields.append("tipo_contato")
    if cliente and conv.cliente_id != cliente.cpf:
        conv.cliente = cliente
        update_fields.append("cliente")
    if (
        cliente
        and tipo_contato == Conversa.TipoContato.CLIENTE
        and conv.identificacao != Conversa.MetodoIdentificacao.TELEFONE
    ):
        conv.identificacao = Conversa.MetodoIdentificacao.TELEFONE
        update_fields.append("identificacao")
    conv.save(update_fields=update_fields)


def _contratos_ativos_values(cliente):
    """Contratos ativos do cliente com SOMENTE os campos permitidos, prontos
    para a IA/renderer. Exclui liquidados. Esta é a garantia dura de que a
    IA nunca vê dados pessoais, contratos de terceiros ou contratos
    liquidados; o renderer de templates (respostas_contrato.py) usa os
    mesmos dicts para os valores financeiros exibidos ao cliente."""
    qs = cliente.contratos_penhor.exclude(
        situacao_codigo__in=SITUACOES_LIQUIDADAS_COD
    ).exclude(situacao__icontains="Liquidado")
    return list(
        qs.values(
            "contrato",
            "data_vencimento",
            "vlr_emprestimo",
            "vlr_liquido",
            "vlr_renovacao_30",
            "vlr_renovacao_60",
            "vlr_renovacao_90",
            "vlr_renovacao_120",
            "vlr_renovacao_150",
            "vlr_renovacao_180",
            "parcelado",
            "vlr_parcela",
        )
    )


def _montar_pergunta_pagamento_incompleto(cliente, msgs) -> str:
    """Pergunta de slot determinística quando PAGAMENTO ainda não tem dados
    suficientes (contrato/prazo) -- nunca texto da IA."""
    if not cliente:
        return msgs.msg_sem_contratos_ativos
    ativos = _contratos_ativos_values(cliente)
    if not ativos:
        return msgs.msg_sem_contratos_ativos
    linhas = [
        render_template(
            msgs.tpl_contrato_resumo,
            contrato=c["contrato"],
            vencimento=formatar_data(c["data_vencimento"]),
            valor_emprestimo=formatar_moeda(c.get("vlr_emprestimo")),
        )
        for c in ativos
    ]
    corpo = "\n".join(linhas)
    pergunta = (
        "Me confirma qual contrato (e o prazo, se for renovação: "
        "30/60/90/120/150/180 dias) você quer?"
    )
    return f"{corpo}\n\n{pergunta}"


def _criar_solicitacoes(conv, cliente, drafts):
    """Cria uma Solicitação por draft (ação distinta). contratos vazio = todos
    os ativos. Retorna a lista de criadas."""
    ativos_contratos = list(
        cliente.contratos_penhor.exclude(
            situacao_codigo__in=SITUACOES_LIQUIDADAS_COD
        ).exclude(situacao__icontains="Liquidado").values_list("contrato", flat=True)
    )
    criadas = []
    for d in drafts:
        if d.contratos:
            contratos_qs = ContratoPenhor.objects.filter(cliente=cliente, contrato__in=d.contratos)
            escopo = Solicitacao.Escopo.ESPECIFICOS
        else:
            contratos_qs = ContratoPenhor.objects.filter(cliente=cliente, contrato__in=ativos_contratos)
            escopo = Solicitacao.Escopo.TODOS
        sol = Solicitacao.objects.create(
            cliente=cliente,
            conversa=conv,
            tipo=TIPO_PAGAMENTO_TO_SOLICITACAO[d.tipo],
            escopo=escopo,
            prazo_dias=d.prazo_dias if d.tipo == TipoPagamento.RENOVAR else None,
        )
        sol.contratos.set(contratos_qs)
        criadas.append(sol)
    return criadas


def _handle_segunda_via(conv, cliente, msgs, responder):
    """Boleto de dia anterior: clona a última solicitação com boleto e pede
    confirmação dos dados antes de disponibilizar para o operador."""
    sol = (
        Solicitacao.objects.filter(cliente=cliente, boletos__isnull=False)
        .order_by("-criado_em").first()
    )
    if not sol:
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        responder(msgs.msg_neutra_padrao)
        return

    ultimo_boleto = sol.boletos.order_by("-enviado_em").first()
    if not ultimo_boleto or not ultimo_boleto.enviado_em:
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        responder(msgs.msg_neutra_padrao)
        return

    if ultimo_boleto.enviado_em.date() >= timezone.localdate():
        # De hoje: não recria; apenas sinaliza.
        responder(
            "Acho que te mandei o boleto hoje, será que não chegou? Deixa comigo "
            "que vou verificar e te reenvio assim que possível."
        )
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        return

    # Dia anterior: clona a solicitação (pendente) e pede confirmação.
    nova = Solicitacao.objects.create(
        cliente=cliente,
        conversa=conv,
        tipo=sol.tipo,
        escopo=sol.escopo,
        prazo_dias=sol.prazo_dias,
    )
    nova.contratos.set(list(sol.contratos.all()))
    contratos_txt = ", ".join(sol.contratos.values_list("contrato", flat=True)) or "todos"
    responder(
        render_template(msgs.msg_segunda_via_confirma, contratos=contratos_txt, tipo=sol.get_tipo_display())
    )
    conv.estado = Conversa.Estado.AGUARDANDO_BOLETO
    conv.save(update_fields=["estado", "ultima_interacao"])


def _reagendar(mensagem_id: int, atraso: timedelta = REAGENDAR_ATRASO):
    """Outra task já está processando esta conversa (mutex ocupado há menos
    de LOCK_TIMEOUT). Re-enfileira este processamento com um pequeno atraso
    via django-q `schedule` (execução única), em vez de martelar a fila com
    `async_task` imediato."""
    from django_q.models import Schedule
    from django_q.tasks import schedule

    schedule(
        "whatsapp.tasks.process_mensagem",
        mensagem_id,
        schedule_type=Schedule.ONCE,
        next_run=timezone.now() + atraso,
        repeats=1,
    )
    logger.info("process_mensagem: conversa ocupada, mensagem %s reagendada (+%ss)", mensagem_id, atraso.seconds)


def _log_auditoria(conv, resultado, acao: str):
    logger.info(
        "process_mensagem conversa=%s intencao_ia=%s precisa_humano=%s -> %s",
        conv.id, resultado.tipo_intencao.value, resultado.precisa_humano, acao,
    )


def process_mensagem(mensagem_id: int):
    """Task principal: processa uma mensagem recebida pelo webhook."""
    try:
        mensagem = Mensagem.objects.select_related("conversa", "conversa__cliente").get(pk=mensagem_id)
    except Mensagem.DoesNotExist:
        logger.warning("process_mensagem: Mensagem %s não encontrada", mensagem_id)
        return

    bot = BotConfig.get_solo()
    if not bot.ativo:
        conv = mensagem.conversa
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        logger.info("Bot desativado: mensagem %s armazenada sem resposta", mensagem_id)
        return

    conv_id = mensagem.conversa_id

    # Lock leve por conversa (MELHORIAS #1): adquire o mutex numa janela
    # curta de transação -- NÃO segura o lock durante a chamada à IA/Evolution.
    with transaction.atomic():
        conv = Conversa.objects.select_for_update().get(pk=conv_id)
        agora = timezone.now()
        if conv.processando_desde and (agora - conv.processando_desde) < LOCK_TIMEOUT:
            _reagendar(mensagem_id)
            return
        conv.processando_desde = agora
        conv.save(update_fields=["processando_desde"])

    try:
        _processar_mensagem_com_lock(mensagem, conv, bot)
    finally:
        Conversa.objects.filter(pk=conv_id).update(processando_desde=None)


def _processar_mensagem_com_lock(mensagem: Mensagem, conv: Conversa, bot: BotConfig):
    # Coalescência: se já chegou uma mensagem IN mais nova nesta conversa, a
    # task dela responde por todas -- esta aborta sem responder.
    mais_nova_existe = conv.mensagens.filter(
        direcao=Mensagem.Direcao.IN, criado_em__gt=mensagem.criado_em
    ).exists()
    if mais_nova_existe:
        logger.info(
            "process_mensagem: mensagem %s superada por outra mais recente na conversa %s (coalescência)",
            mensagem.id, conv.id,
        )
        return

    client = get_client()
    numero_destino = _remote_jid_para_numero(conv.remote_jid)
    msgs = MensagensConfig.get_solo()

    # mark_as_read é best-effort e já nunca levanta (evolution_client
    # devolve False em qualquer erro de rede); protegido aqui por segurança
    # extra para não deixar um erro cosmético derrubar o turno.
    try:
        client.mark_as_read(conv.remote_jid, mensagem.wa_message_id)
    except Exception:  # noqa: BLE001 - cosmético, nunca deve afetar o turno
        logger.debug("mark_as_read: falha inesperada (ignorada)", exc_info=True)

    def responder(texto: str):
        ok = False
        if numero_destino:
            ok = client.send_text(numero_destino, texto)
        else:
            logger.warning("Não foi possível normalizar número para responder conversa %s", conv.id)
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto=texto, enviado_ok=ok)
        if not ok:
            conv.precisa_revisao_humana = True
            conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])

    def responder_arquivo(caminho_completo: str, nome_arquivo: str, legenda: str = ""):
        texto_msg = legenda or f"Enviou arquivo: {nome_arquivo}"
        ok = False
        if numero_destino:
            ok = client.send_file(numero_destino, caminho_completo, nome_arquivo, caption=legenda)
        else:
            logger.warning("Não foi possível normalizar número para enviar arquivo na conversa %s", conv.id)
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto=texto_msg, enviado_ok=ok)
        if not ok:
            conv.precisa_revisao_humana = True
            conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])

    # 1) Classificar contato
    tipo_contato, nome_salvo, cliente = _classificar_contato(conv, mensagem.push_name or "")
    conv.tipo_contato = tipo_contato
    if nome_salvo:
        conv.nome_salvo = nome_salvo
    if cliente and conv.cliente_id is None:
        conv.cliente = cliente
    if cliente and tipo_contato == Conversa.TipoContato.CLIENTE:
        # Identificação por telefone cadastrado/agenda sincronizada -- nunca expira.
        conv.identificacao = Conversa.MetodoIdentificacao.TELEFONE
    conv.save(update_fields=["tipo_contato", "nome_salvo", "cliente", "identificacao", "ultima_interacao"])
    cliente = conv.cliente  # refreshed

    tem_out_anterior = conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).exists()

    # 2) Contato pessoal -> ignora
    if tipo_contato == Conversa.TipoContato.PESSOAL:
        logger.info("Contato pessoal %s: mensagem %s armazenada sem resposta", conv.remote_jid, mensagem.id)
        return

    # 3) Cliente bloqueado
    if cliente and cliente.bloqueado_ia:
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        logger.info("Cliente %s bloqueado p/ IA: mensagem %s sem resposta", cliente.cpf, mensagem.id)
        return

    # 4) Desconhecido sem resposta prévia -> saúda e encerra este turno
    if tipo_contato == Conversa.TipoContato.DESCONHECIDO and not tem_out_anterior:
        if bot.responder_desconhecidos:
            responder(render_template(msgs.msg_saudacao, saudacao=_saudacao()))
        else:
            conv.precisa_revisao_humana = True
            conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        return

    # 4.5) Cliente identificado por telefone, primeira interação -> saudação
    # nominal (decisão do dono: telefone cadastrado = identificado, sem CPF).
    if (
        tipo_contato == Conversa.TipoContato.CLIENTE
        and conv.identificacao == Conversa.MetodoIdentificacao.TELEFONE
        and not tem_out_anterior
    ):
        primeiro_nome = (cliente.nome or "").split()[0] if cliente and cliente.nome else ""
        responder(render_template(msgs.tpl_saudacao_cliente, saudacao=_saudacao(), nome=primeiro_nome))
        return

    # 5) Mídia sem texto (áudio/vídeo/imagem sem legenda) -> não chama a IA
    if mensagem.tipo_midia and not (mensagem.texto or "").strip():
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        responder(msgs.msg_midia_nao_suportada)
        return

    # 6) CPF digitado nesta mensagem -> valida em Python
    permitir_cru = conv.estado == Conversa.Estado.AGUARDANDO_VERIFICACAO
    cpf_digitado = _extrair_cpf_texto(mensagem.texto, permitir_cru=permitir_cru)
    if cpf_digitado:
        if not validar_cpf(cpf_digitado):
            responder(msgs.msg_cpf_invalido)
            return
        if cliente and normalizar_cpf(cliente.cpf) and normalizar_cpf(cliente.cpf) != cpf_digitado:
            responder(msgs.msg_cpf_nao_bate)
            return
        # válido (e confere, se houver cliente conhecido)
        conv.cpf_verificado = cpf_digitado
        conv.verified_at = timezone.now()
        conv.identificacao = Conversa.MetodoIdentificacao.CPF
        conv.estado = Conversa.Estado.VERIFICADA
        if not cliente:
            cliente = _buscar_cliente_por_cpf(cpf_digitado)
            if cliente:
                conv.cliente = cliente
        conv.save(update_fields=["cpf_verificado", "verified_at", "identificacao", "estado", "cliente", "ultima_interacao"])
        cliente = conv.cliente

    # verificação por CPF expirada? (telefone cadastrado NUNCA expira)
    if (
        conv.identificacao == Conversa.MetodoIdentificacao.CPF
        and conv.verified_at
        and (timezone.now() - conv.verified_at) > VERIFICACAO_VALIDADE
    ):
        conv.cpf_verificado = ""
        conv.verified_at = None
        conv.identificacao = Conversa.MetodoIdentificacao.NENHUM
        conv.estado = Conversa.Estado.AGUARDANDO_VERIFICACAO
        conv.save(update_fields=["cpf_verificado", "verified_at", "identificacao", "estado", "ultima_interacao"])

    identificado = conv.identificacao != Conversa.MetodoIdentificacao.NENHUM
    db_atualizada = bot.database_atualizada()

    # 7) Garantia dura: contratos só chegam à IA se identificado E db fresca.
    contratos_para_ia = []
    if cliente and identificado and db_atualizada:
        contratos_para_ia = _contratos_ativos_values(cliente)

    faqs = list(FAQ.objects.filter(ativo=True).values("id", "pergunta"))
    historico = list(
        conv.mensagens.order_by("-criado_em").values("direcao", "texto")[:HISTORICO_TAMANHO]
    )[::-1]

    resultado = extrair_intencao(
        mensagem.texto,
        historico,
        contratos_para_ia,
        faqs,
        identificado=identificado,
        db_atualizada=db_atualizada,
        contato_tipo=tipo_contato,
    )

    # 8) Gates pós-IA (hard rules em Python; a IA nunca decide acesso)
    exige_identificacao = resultado.tipo_intencao in (
        TipoIntencaoV2.INFO_CONTRATO, TipoIntencaoV2.PAGAMENTO, TipoIntencaoV2.SEGUNDA_VIA
    )
    if exige_identificacao and not identificado:
        if tipo_contato == Conversa.TipoContato.DESCONHECIDO:
            responder(msgs.msg_cadastro_nao_localizado)
        else:
            conv.estado = Conversa.Estado.AGUARDANDO_VERIFICACAO
            conv.save(update_fields=["estado", "ultima_interacao"])
            responder(msgs.msg_pedir_cpf)
        _log_auditoria(conv, resultado, "gate:identificacao_ausente -> pediu identificação")
        return

    exige_db = resultado.tipo_intencao in (TipoIntencaoV2.INFO_CONTRATO, TipoIntencaoV2.PAGAMENTO)
    if exige_db and not db_atualizada:
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        responder(msgs.msg_db_desatualizada)
        _log_auditoria(conv, resultado, "gate:db_desatualizada -> avisou database desatualizada")
        return

    # Desconhecidos identificados só por CPF (nunca por telefone cadastrado)
    # só recebem boleto -- nenhum dado de contrato fora dele.
    if (
        resultado.tipo_intencao == TipoIntencaoV2.INFO_CONTRATO
        and conv.identificacao == Conversa.MetodoIdentificacao.CPF
        and tipo_contato == Conversa.TipoContato.DESCONHECIDO
    ):
        responder(msgs.msg_info_negada_desconhecido)
        _log_auditoria(conv, resultado, "gate:info_negada_desconhecido -> negou dado a desconhecido")
        return

    if resultado.precisa_humano:
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])

    # 9) Pagamento: cria solicitações quando pronto, senão pergunta de slot
    if resultado.tipo_intencao == TipoIntencaoV2.PAGAMENTO:
        if resultado.pronto_para_criar_solicitacao and resultado.solicitacoes and cliente:
            _criar_solicitacoes(conv, cliente, resultado.solicitacoes)
            conv.estado = Conversa.Estado.AGUARDANDO_BOLETO
            conv.save(update_fields=["estado", "ultima_interacao"])
            responder(msgs.msg_solicitacao_criada)
            _log_auditoria(conv, resultado, "acao:pagamento_pronto -> criou solicitação(ões)")
        else:
            responder(_montar_pergunta_pagamento_incompleto(cliente, msgs))
            _log_auditoria(conv, resultado, "acao:pagamento_incompleto -> pediu slot faltante")
        return

    # 10) Segunda via
    if resultado.tipo_intencao == TipoIntencaoV2.SEGUNDA_VIA and cliente:
        _handle_segunda_via(conv, cliente, msgs, responder)
        _log_auditoria(conv, resultado, "acao:segunda_via -> clonou solicitação/pediu confirmação")
        return

    # 11) Info de contrato -> renderer determinístico (nunca texto da IA)
    if resultado.tipo_intencao == TipoIntencaoV2.INFO_CONTRATO and resultado.infos_contrato:
        responder(renderizar_infos_contrato(cliente, resultado.infos_contrato, msgs))
        _log_auditoria(conv, resultado, "acao:info_contrato -> renderizou template de contrato")
        return

    # 12) Resposta via FAQ (com suporte a múltiplas mensagens e arquivos)
    if resultado.faq_id:
        try:
            faq = FAQ.objects.get(id=resultado.faq_id, ativo=True)
            respostas = faq.respostas.all().order_by("ordem")
            for resp in respostas:
                if resp.arquivo:
                    caminho_completo = resp.arquivo.path
                    nome_arquivo = os.path.basename(resp.arquivo.name)
                    responder_arquivo(caminho_completo, nome_arquivo, resp.texto)
                elif resp.texto:
                    responder(resp.texto)
            _log_auditoria(conv, resultado, f"acao:faq -> respondeu FAQ {faq.id}")
            return
        except FAQ.DoesNotExist:
            logger.warning("FAQ %s classificada pela IA não existe ou está inativa.", resultado.faq_id)

    # 13) Saudação
    if resultado.tipo_intencao == TipoIntencaoV2.SAUDACAO:
        if identificado and cliente:
            primeiro_nome = (cliente.nome or "").split()[0] if cliente.nome else ""
            responder(render_template(msgs.tpl_saudacao_cliente, saudacao=_saudacao(), nome=primeiro_nome))
        else:
            responder(render_template(msgs.msg_saudacao, saudacao=_saudacao()))
        _log_auditoria(conv, resultado, "acao:saudacao -> respondeu saudação")
        return

    # 14) Fallback: dúvida geral sem FAQ, "outro", ou qualquer coisa que não
    # casou em nenhuma ação acima. Registra sugestão de FAQ + marca revisão.
    FAQSugerida.registrar(
        resultado.pergunta_sugerida_faq or mensagem.texto,
        conversa=conv,
        pergunta_original=mensagem.texto,
    )
    conv.precisa_revisao_humana = True
    conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
    responder(msgs.msg_fallback_sem_resposta)
    _log_auditoria(conv, resultado, "acao:fallback -> sugeriu FAQ + marcou revisão")


def processar_nao_lidas():
    """Ao ativar o bot: reprocessa a última mensagem IN não atendida (sem OUT
    posterior) de cada conversa recente. As mensagens chegaram via webhook
    enquanto o bot estava desligado e ficaram armazenadas; aqui as devolvemos
    ao fluxo normal."""
    bot = BotConfig.get_solo()
    if not bot.ativo:
        return
    from django_q.tasks import async_task

    limite = timezone.now() - JANELA_NAO_LIDAS
    convs = Conversa.objects.filter(ultima_interacao__gte=limite).exclude(
        estado=Conversa.Estado.ENCERRADA
    )
    enfileiradas = 0
    for conv in convs:
        last_in = (
            conv.mensagens.filter(direcao=Mensagem.Direcao.IN, criado_em__gte=limite)
            .order_by("-criado_em").first()
        )
        if not last_in:
            continue
        tem_out_depois = conv.mensagens.filter(
            direcao=Mensagem.Direcao.OUT, criado_em__gt=last_in.criado_em
        ).exists()
        if tem_out_depois:
            continue
        async_task("whatsapp.tasks.process_mensagem", last_in.id)
        enfileiradas += 1
    logger.info("processar_nao_lidas: %s conversa(s) reprocessada(s)", enfileiradas)


def sincronizar_contatos():
    """Baixa a agenda do aparelho conectado (Evolution) e popula o cache de
    ContatoSalvo, classificando PHN_CPF_NOME (cliente) vs. demais (pessoal).

    Proteção contra bug da Evolution API v2: quando a API retorna pushName
    vazio para um contato que já tem nome salvo no cache, preserva o nome
    existente em vez de sobrescrevê-lo com string vazia."""
    client = get_client()
    contatos = client.fetch_contacts()
    if not contatos:
        logger.info("sincronizar_contatos: nenhum contato retornado (sync pulada)")
        return
    atualizados = 0
    for c in contatos:
        jid = c.get("remote_jid") or ""
        nome = c.get("nome") or ""
        if not jid:
            continue
        cpf, _ = parse_nome_salvo(nome)
        tipo = ContatoSalvo.Tipo.CLIENTE if cpf else ContatoSalvo.Tipo.PESSOAL

        # Se a API retornou nome vazio (bug da Evolution v2), não apaga
        # um nome que já estava salvo no cache.
        if not nome:
            existing = ContatoSalvo.objects.filter(remote_jid=jid).first()
            if existing and existing.nome_salvo:
                # Preserva o nome existente; atualiza só tipo/cpf se necessário.
                changed = False
                if existing.tipo != tipo:
                    existing.tipo = tipo
                    changed = True
                if existing.cpf != (cpf or ""):
                    existing.cpf = cpf or ""
                    changed = True
                if changed:
                    existing.save(update_fields=["tipo", "cpf", "atualizado_em"])
                atualizados += 1
                continue

        ContatoSalvo.objects.update_or_create(
            remote_jid=jid,
            defaults={"nome_salvo": nome[:255], "tipo": tipo, "cpf": cpf or ""},
        )
        atualizados += 1
    logger.info("sincronizar_contatos: %s contato(s) cacheado(s)", atualizados)


def verificar_encerramento():
    """Agendada (django-q2 cron): desliga o bot ao chegar o horário de
    encerramento, uma vez por dia (permite reativação manual depois)."""
    bot = BotConfig.get_solo()
    if not bot.ativo or not bot.horario_encerramento:
        return
    hoje = timezone.localdate()
    if bot.ultimo_encerramento_auto == hoje:
        return  # já desligou hoje
    agora = timezone.localtime().time()
    if agora >= bot.horario_encerramento:
        bot.ativo = False
        bot.ultimo_encerramento_auto = hoje
        bot.save(update_fields=["ativo", "ultimo_encerramento_auto", "atualizado_em"])
        logger.info("Bot desativado automaticamente (encerramento %s)", bot.horario_encerramento)
