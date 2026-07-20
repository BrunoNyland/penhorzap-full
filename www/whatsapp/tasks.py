"""Motor de conversa do bot penhorzap (executado pelo django-q2).

Fluxo por mensagem (process_mensagem, split em Fase 3/debounce):
  0. Lock leve por conversa (`Conversa.processando_desde`): evita que duas
     tasks concorrentes (ex.: replay + webhook) processem a mesma conversa
     ao mesmo tempo. Coalescência: se já existe uma mensagem IN mais nova na
     mesma conversa, esta task aborta sem responder (a mais nova cobre).
  1. Classifica o contato (cliente PHN_/telefone cadastrado / pessoal /
     desconhecido) via Telefone + ContatoSalvo (sync da agenda) + pushName.
     Cliente reconhecido por telefone -> `identificacao="telefone"`, nunca
     expira; primeira interação -> saudação nominal e encerra o turno.
  2. Contato pessoal -> ignora (o dono responde); marca todo o lote pendente
     como respondido (nunca vai virar chamada de IA).
  3. Cliente bloqueado -> armazena, marca humana, sem responder (não marca
     a mensagem -- cada nova mensagem do bloqueado só re-sinaliza revisão).
  4. Mídia sem texto (áudio/vídeo/etc.): se há outra mensagem com texto
     ainda pendente no lote, só marca a mídia e segue para o passo 6 (não
     interrompe o lote); se é a única pendente, responde "não suportado" +
     revisão humana, sem chamar a IA.
  5. Se o cliente digitou um CPF nesta mensagem: valida em Python; se
     inválido pede de novo, se não bate com o cadastro pede o correto (e
     marca a mensagem nos dois casos); se válido, marca `identificacao="cpf"`
     (expira em 24h) e NÃO marca a mensagem -- ela segue no lote como
     contexto (o prompt já instrui a IA a ignorar CPF isolado).
  6. Debounce: silêncio do cliente (`BotConfig.debounce_segundos`, 0 =
     imediato/kill-switch) desde a última IN >= debounce -> processa o LOTE
     agora (`_processar_lote`, síncrono); senão agenda `process_lote_conversa`
     para quando o silêncio se completar (`_agendar_debounce`).
  7. `_processar_lote`: monta o lote de IN não respondidas (até 24h/50
     mensagens), chama a IA (classificador puro, NUNCA redige texto) com
     ESTADO (identificado, database_atualizada, contato_tipo) e os
     CONTRATOS ATIVOS -- só passados se identificado E database fresca
     (garantia dura: a IA nunca vê dados desatualizados/de terceiro) --,
     aplica os gates pós-IA (identificação/database/desconhecido-por-CPF) e
     despacha sequencialmente TODAS as ações classificadas (saudação -> FAQs
     -> info_contrato -> pagamento -> segunda_via -> dúvidas/fallback), ao
     final marcando TODAS as mensagens do lote como respondidas.
  8. `process_lote_conversa`: acordada pelo Schedule agendado no passo 6;
     recheca o silêncio dentro do próprio lock (corrida webhook x scheduler)
     antes de chamar `_processar_lote`.
"""

import logging
import os
import re
import time
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.models import (
    FAQ,
    SITUACOES_LIQUIDADAS_COD,
    BotConfig,
    Cliente,
    ContatoSalvo,
    ContratoPenhor,
    Conversa,
    FAQSugerida,
    Mensagem,
    MensagensConfig,
    Solicitacao,
    Telefone,
)
from core.utils import normalizar_cpf, normalize_phone_br, parse_nome_salvo, validar_cpf
from ia.schemas import TipoPagamento
from ia.services import extrair_intencao

from .evolution_client import get_client
from .respostas_contrato import (
    formatar_data,
    formatar_moeda,
    render_template,
    renderizar_infos_contrato,
)

logger = logging.getLogger(__name__)

HISTORICO_TAMANHO = 10
VERIFICACAO_VALIDADE = timedelta(hours=24)
JANELA_NAO_LIDAS = timedelta(hours=24)
LOCK_TIMEOUT = timedelta(seconds=60)
REAGENDAR_ATRASO = timedelta(seconds=5)
PRAZOS_RENOVACAO = (30, 60, 90, 120, 150, 180)

# Fan-out de mensagens (WS-A v3): pausa entre mensagens de uma mesma
# resposta (imita cadência humana) e teto de mensagens por turno (protege
# contra o timeout do worker do qcluster e contra inundar o cliente).
PAUSA_FANOUT = 1.2
MAX_MENSAGENS_TURNO = 12

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
    qs = cliente.contratos_penhor.exclude(situacao_codigo__in=SITUACOES_LIQUIDADAS_COD).exclude(
        situacao__icontains="Liquidado"
    )
    return list(
        qs.values(
            "contrato",
            "data_vencimento",
            "vlr_emprestimo",
            # valor de quitação do ERP (texto já formatado). NÃO usar
            # vlr_liquido: aquele é o valor líquido RECEBIDO pelo cliente na
            # contratação (descontados IOF/juros/tarifas), não o de quitação.
            "liquidacao",
            "vlr_renovacao_30",
            "vlr_renovacao_60",
            "vlr_renovacao_90",
            "vlr_renovacao_120",
            "vlr_renovacao_150",
            "vlr_renovacao_180",
            "parcelado",
            "vlr_parcela",
            "laudo",
            "peso",
            "vlr_avaliacao",
        )
    )


def _montar_pergunta_pagamento_incompleto(
    cliente, msgs, drafts=None, conversa=None, fila=None
) -> str:
    """Pergunta de slot determinística quando PAGAMENTO ainda não tem dados
    suficientes (contrato/prazo) -- nunca texto da IA.

    Se os `drafts` já identificam um contrato específico (não "todos"/
    ambíguo), a pergunta é só sobre o que falta de verdade (prazo pra
    renovação, ou confirmação pro tipo indefinido) -- NÃO reenvia a lista de
    contratos, que o cliente já viu ao escolher aquele contrato. A lista só
    volta a aparecer quando o contrato ainda é ambíguo."""
    if not cliente:
        return msgs.msg_sem_contratos_ativos
    ativos = _contratos_ativos_values(cliente)
    if not ativos:
        return msgs.msg_sem_contratos_ativos
    ativos_map = {c["contrato"]: c for c in ativos}

    tipo_indefinido = False
    tipos_pendentes = set()
    contratos_citados: list[str] = []
    if drafts:
        algum_ambiguo = False
        for d in drafts:
            if d.tipo == TipoPagamento.INDEFINIDO:
                tipo_indefinido = True
            else:
                tipos_pendentes.add(d.tipo)
            if not d.contratos:
                algum_ambiguo = True
            else:
                for num in d.contratos:
                    if num in ativos_map and num not in contratos_citados:
                        contratos_citados.append(num)
        if algum_ambiguo:
            contratos_citados = []

    if contratos_citados:
        alvo = ", ".join(contratos_citados)
        if tipo_indefinido:
            return f"O boleto do contrato {alvo} seria de renovação ou quitação?"
        if TipoPagamento.RENOVAR in tipos_pendentes:
            return f"Para quantos dias você quer renovar o contrato {alvo} (30/60/90/120/150/180 dias)?"
        if TipoPagamento.QUITAR in tipos_pendentes:
            return f"Você confirma que quer o boleto de quitação do contrato {alvo}?"
        if TipoPagamento.PARCELA in tipos_pendentes:
            return f"Você confirma que quer o boleto da parcela do contrato {alvo}?"

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

    if tipo_indefinido:
        pergunta = "O boleto seria de renovação? ou quitação?"
    else:
        pergunta = (
            "Me confirma qual contrato (e o prazo, se for renovação: "
            "30/60/90/120/150/180 dias) você quer?"
        )

    # Evita reenviar a lista de contratos se ela já foi apresentada recentemente
    ja_apresentado = False

    # 1. Checa se os contratos já estão na fila de envio deste turno
    if fila:
        all_in_fila = True
        for c in ativos:
            contract_found = False
            for item in fila:
                if isinstance(item, str) and c["contrato"] in item:
                    contract_found = True
                    break
            if not contract_found:
                all_in_fila = False
                break
        if all_in_fila:
            ja_apresentado = True

    # 2. Checa se foram enviados nas últimas mensagens do histórico recente (últimos 10 min)
    if conversa and not ja_apresentado:
        limite = timezone.now() - timedelta(minutes=10)
        recent_outgoing = conversa.mensagens.filter(
            direcao=Mensagem.Direcao.OUT, criado_em__gte=limite
        ).order_by("-criado_em")[:5]

        all_in_history = True
        for c in ativos:
            contract_found = False
            for msg in recent_outgoing:
                if c["contrato"] in msg.texto:
                    contract_found = True
                    break
            if not contract_found:
                all_in_history = False
                break
        if all_in_history:
            ja_apresentado = True

    if ja_apresentado:
        return pergunta
    return f"{corpo}\n\n{pergunta}"


def _criar_solicitacoes(conv, cliente, drafts):
    """Cria uma Solicitação por draft (ação distinta). contratos vazio = todos
    os ativos. Retorna a lista de criadas."""
    ativos_contratos = list(
        cliente.contratos_penhor.exclude(situacao_codigo__in=SITUACOES_LIQUIDADAS_COD)
        .exclude(situacao__icontains="Liquidado")
        .values_list("contrato", flat=True)
    )
    criadas = []
    for d in drafts:
        if d.contratos:
            contratos_qs = ContratoPenhor.objects.filter(cliente=cliente, contrato__in=d.contratos)
            escopo = Solicitacao.Escopo.ESPECIFICOS
        else:
            contratos_qs = ContratoPenhor.objects.filter(
                cliente=cliente, contrato__in=ativos_contratos
            )
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


def _handle_segunda_via(conv, cliente, msgs) -> list:
    """Boleto de dia anterior: clona a última solicitação com boleto e pede
    confirmação dos dados antes de disponibilizar para o operador.

    Retorna a lista de mensagens a enviar (o chamador despacha via
    `_enviar_fila`); os efeitos de estado (criação de `Solicitacao`,
    mudança de `conv.estado`/`precisa_revisao_humana`) continuam
    acontecendo aqui, síncronos com a decisão tomada."""
    sol = (
        Solicitacao.objects.filter(cliente=cliente, boletos__isnull=False)
        .order_by("-criado_em")
        .first()
    )
    if not sol:
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        return [msgs.msg_neutra_padrao]

    ultimo_boleto = sol.boletos.order_by("-enviado_em").first()
    if not ultimo_boleto or not ultimo_boleto.enviado_em:
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        return [msgs.msg_neutra_padrao]

    if ultimo_boleto.enviado_em.date() >= timezone.localdate():
        # De hoje: não recria; apenas sinaliza.
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        return [
            "Acho que te mandei o boleto hoje, será que não chegou? Deixa comigo "
            "que vou verificar e te reenvio assim que possível."
        ]

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
    conv.estado = Conversa.Estado.AGUARDANDO_BOLETO
    conv.save(update_fields=["estado", "ultima_interacao"])
    return [
        render_template(
            msgs.msg_segunda_via_confirma, contratos=contratos_txt, tipo=sol.get_tipo_display()
        )
    ]


def _colapsar_fila(fila: list) -> list:
    """Se `fila` exceder `MAX_MENSAGENS_TURNO`, colapsa o excedente do MEIO
    numa única mensagem unida por `"\\n"`, preservando sempre o primeiro
    item (a intro, nos blocos de `renderizar_infos_contrato`) e o último
    (o totalizador) intactos -- é aí que mora o resumo que o cliente precisa
    ver de qualquer forma.

    Implementado aqui (em vez de em `respostas_contrato.py`) porque o teto
    é por TURNO de envio (`_enviar_fila`), não por bloco de
    `InfoContratoPedido`: nesta fase o dispatch ainda é uma cadeia de ifs
    com um único tipo de ação por turno, então a fila de um dado envio é
    sempre homogênea (só linhas de contrato, ou só respostas de FAQ) --
    colapsar de forma genérica aqui cobre os dois casos sem duplicar lógica.
    Itens de arquivo (tuplas `(caminho, nome, legenda)`) nunca são
    colapsáveis; se algum aparecer na fila, ela é enviada inteira sem
    colapso (mensagens de arquivo não têm como ser unidas por texto)."""
    if len(fila) <= MAX_MENSAGENS_TURNO:
        return fila
    if len(fila) < 3 or any(not isinstance(item, str) for item in fila):
        return fila

    primeiro, *meio, ultimo = fila
    # saída final = primeiro + mantidos + 1 mensagem colapsada + último
    # -> "vagas" (itens do meio mantidos separados) = teto - 3.
    vagas = max(MAX_MENSAGENS_TURNO - 3, 0)
    mantidos = meio[:vagas]
    colapsado = "\n".join(meio[vagas:])
    return [primeiro, *mantidos, colapsado, ultimo]


def _enviar_fila(fila: list, responder, responder_arquivo, conv: Conversa) -> None:
    """Envia uma fila de itens (texto -> `responder`; tupla
    `(caminho, nome, legenda)` -> `responder_arquivo`) como mensagens
    WhatsApp separadas, com `PAUSA_FANOUT` segundos entre cada uma (n-1
    pausas para n itens) -- imita a cadência de alguém digitando várias
    mensagens em vez de um bloco de texto único.

    A cada envio, "toca" `Conversa.processando_desde` para agora: um
    fan-out longo (várias mensagens + pausas) não pode parecer, para outra
    task concorrente, um lock expirado (`LOCK_TIMEOUT`)."""
    fila = _colapsar_fila(list(fila))
    total = len(fila)
    for i, item in enumerate(fila):
        if isinstance(item, tuple):
            responder_arquivo(*item)
        else:
            responder(item)
        Conversa.objects.filter(pk=conv.pk).update(processando_desde=timezone.now())
        if i < total - 1:
            time.sleep(PAUSA_FANOUT)


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
        repeats=-1,
    )
    logger.info(
        "process_mensagem: conversa ocupada, mensagem %s reagendada (+%ss)",
        mensagem_id,
        atraso.seconds,
    )


def _reagendar_lote(conversa_id: int, atraso: timedelta = REAGENDAR_ATRASO):
    """Mesma ideia de `_reagendar`, mas para `process_lote_conversa`: mutex
    ocupado (outra task processando a conversa) -- reagenda usando o MESMO
    `name` determinístico (`pz-debounce-<id>`), atualizando o Schedule via
    `update_or_create` em vez de duplicá-lo."""
    from django_q.models import Schedule

    Schedule.objects.update_or_create(
        name=f"pz-debounce-{conversa_id}",
        defaults=dict(
            func="whatsapp.tasks.process_lote_conversa",
            args=str(conversa_id),
            schedule_type=Schedule.ONCE,
            next_run=timezone.now() + atraso,
            repeats=-1,
        ),
    )
    logger.info(
        "process_lote_conversa: conversa %s ocupada, lote reagendado (+%ss)",
        conversa_id,
        atraso.seconds,
    )


def _agendar_debounce(conv: Conversa, bot: BotConfig):
    """Agenda `process_lote_conversa` para quando o cliente completar
    `bot.debounce_segundos` de silêncio, contados a partir da última IN da
    conversa. `update_or_create` por `name=f"pz-debounce-{conv.id}"` faz de
    1 Schedule por conversa a chave lógica: uma 2ª mensagem do cliente
    durante a espera só empurra `next_run` para frente (mesmo Schedule,
    "reinicia o cronômetro" do silêncio) em vez de duplicar. `repeats=-1`
    auto-deleta o Schedule assim que dispara -- não deixa lixo na tabela."""
    from django_q.models import Schedule

    ultima_in = conv.mensagens.filter(direcao=Mensagem.Direcao.IN).order_by("-criado_em").first()
    referencia = ultima_in.criado_em if ultima_in else timezone.now()
    next_run = max(
        referencia + timedelta(seconds=bot.debounce_segundos),
        timezone.now() + timedelta(seconds=1),
    )
    Schedule.objects.update_or_create(
        name=f"pz-debounce-{conv.id}",
        defaults=dict(
            func="whatsapp.tasks.process_lote_conversa",
            args=str(conv.id),
            schedule_type=Schedule.ONCE,
            next_run=next_run,
            repeats=-1,
        ),
    )
    logger.info("process_mensagem: debounce agendado conversa=%s next_run=%s", conv.id, next_run)


def _mensagens_pendentes(conv: Conversa):
    """Lote de mensagens IN ainda não cobertas por uma resposta do bot
    (`respondida_em` nulo). Usado tanto para decidir se uma mídia sem texto
    tem outra mensagem com texto pendente ao lado, quanto para montar o
    lote que vai para a IA (`_processar_lote`) e para o "marca tudo" de
    contato pessoal. Janela de 24h e teto de 50 protegem contra reprocessar
    histórico antigo (ex.: bot ficou muito tempo desligado)."""
    limite = timezone.now() - timedelta(hours=24)
    return conv.mensagens.filter(
        direcao=Mensagem.Direcao.IN, respondida_em__isnull=True, criado_em__gte=limite
    ).order_by("criado_em")[:50]


def _marcar_mensagens_respondidas(mensagens) -> None:
    """Bulk update de `respondida_em=now()` para as mensagens dadas (aceita
    lista de instâncias ou queryset -- só precisa dar pra iterar e ler
    `.pk`). Chamado tanto pelos passos determinísticos (marcam só a
    mensagem que cobriram) quanto por `_processar_lote` (marca todas as do
    lote ao final do dispatch, mesmo no fallback)."""
    ids = [m.pk for m in mensagens]
    if ids:
        Mensagem.objects.filter(pk__in=ids).update(respondida_em=timezone.now())


def _criar_responders(conv: Conversa):
    """Fábrica dos closures `responder`/`responder_arquivo` (e do client
    Evolution) usados tanto por `_processar_mensagem_com_lock` quanto por
    `_processar_lote_com_lock` (acordado pelo Schedule) -- evita duplicar a
    lógica de envio + persistência de `Mensagem` OUT + marcação de
    `precisa_revisao_humana` em caso de falha de envio."""
    client = get_client()
    numero_destino = _remote_jid_para_numero(conv.remote_jid)

    def responder(texto: str):
        ok = False
        if numero_destino:
            ok = client.send_text(numero_destino, texto)
        else:
            logger.warning("Não foi possível normalizar número para responder conversa %s", conv.id)
        Mensagem.objects.create(
            conversa=conv, direcao=Mensagem.Direcao.OUT, texto=texto, enviado_ok=ok
        )
        if not ok:
            conv.precisa_revisao_humana = True
            conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])

    def responder_arquivo(caminho_completo: str, nome_arquivo: str, legenda: str = ""):
        texto_msg = legenda or f"Enviou arquivo: {nome_arquivo}"
        ok = False
        if numero_destino:
            ok = client.send_file(numero_destino, caminho_completo, nome_arquivo, caption=legenda)
        else:
            logger.warning(
                "Não foi possível normalizar número para enviar arquivo na conversa %s", conv.id
            )
        Mensagem.objects.create(
            conversa=conv, direcao=Mensagem.Direcao.OUT, texto=texto_msg, enviado_ok=ok
        )
        if not ok:
            conv.precisa_revisao_humana = True
            conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])

    return client, numero_destino, responder, responder_arquivo


def _log_auditoria(conv, resultado, acoes: str):
    logger.info(
        "process_mensagem conversa=%s precisa_humano=%s -> %s",
        conv.id,
        resultado.precisa_humano,
        acoes,
    )


def process_mensagem(mensagem_id: int):
    """Task principal: processa uma mensagem recebida pelo webhook."""
    try:
        mensagem = Mensagem.objects.select_related("conversa", "conversa__cliente").get(
            pk=mensagem_id
        )
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
    # task dela cobre esta -- aborta sem responder (mesmo com debounce
    # ativo: a mais nova vai encontrar esta mensagem ainda pendente e
    # incluí-la no próprio lote).
    mais_nova_existe = conv.mensagens.filter(
        direcao=Mensagem.Direcao.IN, criado_em__gt=mensagem.criado_em
    ).exists()
    if mais_nova_existe:
        logger.info(
            "process_mensagem: mensagem %s superada por outra mais recente na conversa %s (coalescência)",
            mensagem.id,
            conv.id,
        )
        return

    client, numero_destino, responder, responder_arquivo = _criar_responders(conv)
    msgs = MensagensConfig.get_solo()

    # mark_as_read é best-effort e já nunca levanta (evolution_client
    # devolve False em qualquer erro de rede); protegido aqui por segurança
    # extra para não deixar um erro cosmético derrubar o turno.
    try:
        client.mark_as_read(conv.remote_jid, mensagem.wa_message_id)
    except Exception:  # noqa: BLE001 - cosmético, nunca deve afetar o turno
        logger.debug("mark_as_read: falha inesperada (ignorada)", exc_info=True)

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
    conv.save(
        update_fields=["tipo_contato", "nome_salvo", "cliente", "identificacao", "ultima_interacao"]
    )
    cliente = conv.cliente  # refreshed

    tem_out_anterior = conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).exists()

    # 2) Contato pessoal -> ignora; marca TODO o lote pendente como
    # respondido (contato pessoal nunca vai gerar uma chamada de IA).
    if tipo_contato == Conversa.TipoContato.PESSOAL:
        _marcar_mensagens_respondidas(_mensagens_pendentes(conv))
        logger.info(
            "Contato pessoal %s: mensagem %s armazenada sem resposta", conv.remote_jid, mensagem.id
        )
        return

    # 3) Cliente bloqueado -- não marca a mensagem: cada nova mensagem do
    # bloqueado passa por aqui de novo e apenas re-sinaliza revisão.
    if cliente and cliente.bloqueado_ia:
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        logger.info(
            "Cliente %s bloqueado p/ IA: mensagem %s sem resposta", cliente.cpf, mensagem.id
        )
        return

    # 4) Desconhecido sem resposta prévia -> saúda, marca só esta mensagem e
    # encerra este turno (sem IA).
    if tipo_contato == Conversa.TipoContato.DESCONHECIDO and not tem_out_anterior:
        if bot.responder_desconhecidos:
            responder(render_template(msgs.msg_saudacao, saudacao=_saudacao()))
        else:
            conv.precisa_revisao_humana = True
            conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        _marcar_mensagens_respondidas([mensagem])
        return

    # 4.5) Cliente identificado por telefone, primeira interação -> saudação
    # nominal (decisão do dono: telefone cadastrado = identificado, sem
    # CPF), sem IA; marca só esta mensagem.
    if (
        tipo_contato == Conversa.TipoContato.CLIENTE
        and conv.identificacao == Conversa.MetodoIdentificacao.TELEFONE
        and not tem_out_anterior
    ):
        primeiro_nome = (cliente.nome or "").split()[0] if cliente and cliente.nome else ""
        responder(
            render_template(msgs.tpl_saudacao_cliente, saudacao=_saudacao(), nome=primeiro_nome)
        )
        _marcar_mensagens_respondidas([mensagem])
        return

    # 5) Mídia sem texto (áudio/vídeo/imagem sem legenda) -> nunca chama a
    # IA. Se há outra IN com texto ainda pendente no lote, só marca a mídia
    # e SEGUE (não responde msg_midia_nao_suportada no meio do lote); se é
    # a única pendente, responde a recusa e encerra o turno.
    if mensagem.tipo_midia and not (mensagem.texto or "").strip():
        outras_com_texto = any(
            (m.texto or "").strip() for m in _mensagens_pendentes(conv) if m.pk != mensagem.pk
        )
        if outras_com_texto:
            _marcar_mensagens_respondidas([mensagem])
        else:
            conv.precisa_revisao_humana = True
            conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
            responder(msgs.msg_midia_nao_suportada)
            _marcar_mensagens_respondidas([mensagem])
            return

    # 6) CPF digitado nesta mensagem -> valida em Python
    permitir_cru = conv.estado == Conversa.Estado.AGUARDANDO_VERIFICACAO
    cpf_digitado = _extrair_cpf_texto(mensagem.texto, permitir_cru=permitir_cru)
    if cpf_digitado:
        if not validar_cpf(cpf_digitado):
            responder(msgs.msg_cpf_invalido)
            _marcar_mensagens_respondidas([mensagem])
            return
        if cliente and normalizar_cpf(cliente.cpf) and normalizar_cpf(cliente.cpf) != cpf_digitado:
            responder(msgs.msg_cpf_nao_bate)
            _marcar_mensagens_respondidas([mensagem])
            return
        # válido (e confere, se houver cliente conhecido) -- NÃO marca:
        # fica no lote como contexto (o prompt já instrui a IA a ignorar um
        # CPF isolado como solicitação).
        conv.cpf_verificado = cpf_digitado
        conv.verified_at = timezone.now()
        conv.identificacao = Conversa.MetodoIdentificacao.CPF
        conv.estado = Conversa.Estado.VERIFICADA
        if not cliente:
            cliente = _buscar_cliente_por_cpf(cpf_digitado)
            if cliente:
                conv.cliente = cliente
        conv.save(
            update_fields=[
                "cpf_verificado",
                "verified_at",
                "identificacao",
                "estado",
                "cliente",
                "ultima_interacao",
            ]
        )
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
        conv.save(
            update_fields=[
                "cpf_verificado",
                "verified_at",
                "identificacao",
                "estado",
                "ultima_interacao",
            ]
        )

    # 7) Ponto de decisão do debounce (WS-A v3/Fase 3): silêncio do cliente
    # desde a última IN >= debounce_segundos (ou kill-switch debounce=0) ->
    # processa o lote agora, síncrono; senão agenda para quando o silêncio
    # se completar.
    debounce = bot.debounce_segundos
    ultima_in = conv.mensagens.filter(direcao=Mensagem.Direcao.IN).order_by("-criado_em").first()
    silencio = timezone.now() - ultima_in.criado_em if ultima_in else timedelta(0)
    if debounce == 0 or silencio >= timedelta(seconds=debounce):
        _processar_lote(conv, bot, msgs, client, numero_destino, responder, responder_arquivo)
    else:
        _agendar_debounce(conv, bot)


def _processar_lote(
    conv: Conversa, bot: BotConfig, msgs, client, numero_destino, responder, responder_arquivo
):
    """Chama a IA com o LOTE de mensagens IN não respondidas e despacha
    sequencialmente TODAS as ações classificadas. Extraído do antigo passo
    6-8 de `process_mensagem` (Fase 2) para ser reutilizável tanto no
    caminho síncrono (debounce=0 ou silêncio já cumprido, chamado por
    `_processar_mensagem_com_lock`) quanto acordado pelo Schedule
    (`process_lote_conversa` -> `_processar_lote_com_lock`).

    Histórico x lote: para não duplicar contexto, o histórico enviado à IA
    inclui só mensagens ANTERIORES à primeira do lote (`criado_em` menor);
    as próprias mensagens do lote entram apenas como `mensagens_lote`.
    """
    lote = list(_mensagens_pendentes(conv))
    if not lote:
        return

    lote_texto = [m.texto for m in lote if (m.texto or "").strip()]
    if not lote_texto:
        # Lote só tem mídia/mensagens vazias (já teriam sido marcadas pelos
        # passos determinísticos, mas cobre qualquer sobra) -- não há o que
        # classificar; marca e sai sem chamar a IA.
        _marcar_mensagens_respondidas(lote)
        return

    cliente = conv.cliente
    tipo_contato = conv.tipo_contato
    identificado = conv.identificacao != Conversa.MetodoIdentificacao.NENHUM
    db_atualizada = bot.database_atualizada()

    # Garantia dura: contratos só chegam à IA se identificado E db fresca.
    contratos_para_ia = []
    if cliente and identificado and db_atualizada:
        contratos_para_ia = _contratos_ativos_values(cliente)

    faqs = []
    enviar_respostas = getattr(bot, "enviar_respostas_faq_ia", False)
    for faq in FAQ.objects.filter(ativo=True):
        faq_dict = {"id": faq.id, "pergunta": faq.pergunta}
        if enviar_respostas:
            faq_dict["respostas"] = [resp.texto for resp in faq.respostas.all() if resp.texto]
        faqs.append(faq_dict)
    primeira_do_lote = lote[0]
    historico = list(
        conv.mensagens.filter(criado_em__lt=primeira_do_lote.criado_em)
        .order_by("-criado_em")
        .values("direcao", "texto")[:HISTORICO_TAMANHO]
    )[::-1]

    resultado = extrair_intencao(
        lote_texto,
        historico,
        contratos_para_ia,
        faqs,
        identificado=identificado,
        db_atualizada=db_atualizada,
        contato_tipo=tipo_contato,
    )

    # Dispatch sequencial multi-ação (WS-A v3/Fase 2): a IA identifica TODAS
    # as solicitações do lote de uma vez (schema ClassificacaoLote) -- em
    # vez de responder-e-retornar na primeira ação que casar, acumulamos
    # tudo numa única `fila` e enviamos ao final via `_enviar_fila`, na
    # ordem: saudação -> FAQs -> infos_contrato -> pagamento -> segunda_via
    # -> dúvidas/fallback. Os gates de identificação/database (hard rules em
    # Python; a IA nunca decide acesso) suprimem só as ações a que se
    # aplicam -- saudação e FAQ sempre saem.
    fila: list = []
    acoes_log: list[str] = []

    marcar_revisao = False

    def _marcar_revisao():
        nonlocal marcar_revisao
        marcar_revisao = True

    # 1) Saudação -- se a mesma leva já traz um pedido, não pergunta "como
    # posso ajudar" à toa (a resposta ao pedido já vem em seguida na fila).
    if resultado.saudacao:
        tem_pedido_junto = bool(
            resultado.faq_ids
            or resultado.infos_contrato
            or resultado.solicitacoes
            or resultado.segunda_via
            or resultado.duvidas_sem_faq
        )
        if identificado and cliente:
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
        acoes_log.append("saudacao")

    # 2) FAQs -- todas as classificadas, cada FAQResposta vira 1 item da fila
    for faq_id in resultado.faq_ids:
        try:
            faq = FAQ.objects.get(id=faq_id, ativo=True)
        except FAQ.DoesNotExist:
            logger.warning("FAQ %s classificada pela IA não existe ou está inativa.", faq_id)
            continue
        for resp in faq.respostas.all().order_by("ordem"):
            if resp.arquivo:
                caminho_completo = resp.arquivo.path
                nome_arquivo = os.path.basename(resp.arquivo.name)
                fila.append((caminho_completo, nome_arquivo, resp.texto))
            elif resp.texto:
                fila.append(resp.texto)
        acoes_log.append(f"faq:{faq.id}")

    # 3) Gates POR AÇÃO (identificação/database/desconhecido-por-CPF):
    # calculados uma vez, suprimem só infos_contrato/pagamento/segunda_via.
    tem_infos = bool(resultado.infos_contrato)
    tem_pagamento = bool(resultado.solicitacoes)
    tem_segunda_via = resultado.segunda_via

    info_suprimido = False
    pagamento_suprimido = False
    segunda_via_suprimida = False
    gate_motivo = None  # "identificacao" | "db"

    if (tem_infos or tem_pagamento or tem_segunda_via) and not identificado:
        info_suprimido = tem_infos
        pagamento_suprimido = tem_pagamento
        segunda_via_suprimida = tem_segunda_via
        gate_motivo = "identificacao"
    elif (tem_infos or tem_pagamento) and not db_atualizada:
        info_suprimido = tem_infos
        pagamento_suprimido = tem_pagamento
        gate_motivo = "db"
    elif (
        tem_infos
        and conv.identificacao == Conversa.MetodoIdentificacao.CPF
        and tipo_contato == Conversa.TipoContato.DESCONHECIDO
    ):
        # Desconhecido identificado só por CPF (nunca por telefone
        # cadastrado) pedindo dado de contrato -> só o boleto tem os dados;
        # pagamento/segunda via continuam permitidos fora deste bloco.
        info_suprimido = True
        fila.append(msgs.msg_info_negada_desconhecido)
        acoes_log.append("info_negada_desconhecido")

    # 4) Info de contrato -> renderer determinístico (nunca texto da IA);
    # fan-out: intro + 1 mensagem por contrato + totalizador (2+ contratos).
    # Pedido com filtro de valor (acima/abaixo de X) sem campo definido
    # (empréstimo vs avaliação) é ambíguo -- pergunta 1x em vez de adivinhar.
    if tem_infos and not info_suprimido:
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
        acoes_log.append(f"info_contrato:{len(resultado.infos_contrato)}")

    # 5) Pagamento: cria solicitações quando pronto, senão pergunta de slot
    if tem_pagamento and not pagamento_suprimido:
        tem_indefinido = any(d.tipo == TipoPagamento.INDEFINIDO for d in resultado.solicitacoes)
        if resultado.pronto_para_criar_solicitacao and cliente and not tem_indefinido:
            _criar_solicitacoes(conv, cliente, resultado.solicitacoes)
            conv.estado = Conversa.Estado.AGUARDANDO_BOLETO
            conv.save(update_fields=["estado", "ultima_interacao"])
            fila.append(msgs.msg_solicitacao_criada)
            acoes_log.append("pagamento_pronto")
        else:
            fila.append(
                _montar_pergunta_pagamento_incompleto(
                    cliente, msgs, resultado.solicitacoes, conversa=conv, fila=fila
                )
            )
            acoes_log.append("pagamento_incompleto")

    # 6) Segunda via
    if tem_segunda_via and not segunda_via_suprimida and cliente:
        fila.extend(_handle_segunda_via(conv, cliente, msgs))
        acoes_log.append("segunda_via")

    # 7) Mensagem agregada do gate de identificação/database, UMA vez.
    if gate_motivo == "identificacao":
        if tipo_contato == Conversa.TipoContato.DESCONHECIDO:
            fila.append(msgs.msg_cadastro_nao_localizado)
        else:
            conv.estado = Conversa.Estado.AGUARDANDO_VERIFICACAO
            conv.save(update_fields=["estado", "ultima_interacao"])
            fila.append(msgs.msg_pedir_cpf)
        acoes_log.append("gate:identificacao_ausente")
    elif gate_motivo == "db":
        _marcar_revisao()
        fila.append(msgs.msg_db_desatualizada)
        acoes_log.append("gate:db_desatualizada")

    # 8) Dúvidas sem FAQ correspondente: registra sugestão de FAQ por
    # dúvida + marca revisão; com outras ações na fila, anexa
    # msg_duvida_anotada; sozinhas, cai no fallback padrão. `pergunta_original`
    # usa o lote inteiro (não há mais 1 "mensagem" única no contexto do lote).
    lote_texto_join = "\n".join(lote_texto)
    if resultado.duvidas_sem_faq:
        for duvida in resultado.duvidas_sem_faq:
            FAQSugerida.registrar(duvida, conversa=conv, pergunta_original=lote_texto_join)
        _marcar_revisao()
        if fila:
            duvidas_txt = "; ".join(resultado.duvidas_sem_faq)
            fila.append(render_template(msgs.msg_duvida_anotada, duvidas=duvidas_txt))
        else:
            fila.append(msgs.msg_fallback_sem_resposta)
        acoes_log.append(f"duvida_sem_faq:{len(resultado.duvidas_sem_faq)}")

    # 9) Nenhuma ação classificada no lote inteiro -> fallback padrão.
    # Fila vazia apesar de haver ação (ex.: FAQ inativa) -> mensagem neutra.
    if resultado.nenhuma_acao():
        FAQSugerida.registrar(lote_texto_join, conversa=conv, pergunta_original=lote_texto_join)
        _marcar_revisao()
        fila.append(msgs.msg_fallback_sem_resposta)
        acoes_log.append("nenhuma_acao")
    elif not fila:
        _marcar_revisao()
        fila.append(msgs.msg_neutra_padrao)
        acoes_log.append("fila_vazia_apos_acao")

    if resultado.precisa_humano:
        _marcar_revisao()
        acoes_log.append("precisa_humano")

    if marcar_revisao:
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])

    _enviar_fila(fila, responder, responder_arquivo, conv)
    _marcar_mensagens_respondidas(lote)
    _log_auditoria(conv, resultado, "acoes=" + (",".join(acoes_log) if acoes_log else "nenhuma"))


def process_lote_conversa(conversa_id: int):
    """Task acordada pelo Schedule agendado em `_agendar_debounce`: processa
    o lote de mensagens não respondidas da conversa após o cliente
    completar `debounce_segundos` de silêncio. Usa o MESMO mutex leve
    (`Conversa.processando_desde`) de `process_mensagem` -- se ocupado,
    reagenda via `_reagendar_lote` em vez de duplicar o Schedule."""
    try:
        conv = Conversa.objects.select_related("cliente").get(pk=conversa_id)
    except Conversa.DoesNotExist:
        logger.warning("process_lote_conversa: conversa %s não encontrada", conversa_id)
        return

    bot = BotConfig.get_solo()
    if not bot.ativo:
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        logger.info("Bot desativado: lote da conversa %s armazenado sem resposta", conversa_id)
        return

    with transaction.atomic():
        conv = Conversa.objects.select_for_update().get(pk=conversa_id)
        agora = timezone.now()
        if conv.processando_desde and (agora - conv.processando_desde) < LOCK_TIMEOUT:
            _reagendar_lote(conversa_id)
            return
        conv.processando_desde = agora
        conv.save(update_fields=["processando_desde"])

    try:
        _processar_lote_com_lock(conv, bot)
    finally:
        Conversa.objects.filter(pk=conversa_id).update(processando_desde=None)


def _processar_lote_com_lock(conv: Conversa, bot: BotConfig):
    # Recheck de silêncio dentro do lock: corrida webhook x scheduler -- uma
    # nova IN pode ter chegado entre o agendamento e a execução deste
    # Schedule (`_agendar_debounce` já teria reagendado o `next_run` para a
    # frente, mas a task antiga já pode estar em voo).
    ultima_in = conv.mensagens.filter(direcao=Mensagem.Direcao.IN).order_by("-criado_em").first()
    if ultima_in and bot.debounce_segundos > 0:
        silencio = timezone.now() - ultima_in.criado_em
        if silencio < timedelta(seconds=bot.debounce_segundos):
            _agendar_debounce(conv, bot)
            return

    msgs = MensagensConfig.get_solo()
    client, numero_destino, responder, responder_arquivo = _criar_responders(conv)
    _processar_lote(conv, bot, msgs, client, numero_destino, responder, responder_arquivo)


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
            .order_by("-criado_em")
            .first()
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
