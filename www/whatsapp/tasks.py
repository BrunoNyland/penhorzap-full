"""Motor de conversa do bot penhorzap (executado pelo django-q2).

Fluxo por mensagem (process_mensagem):
  1. Bot desligado? armazena e marca humana, sem responder.
  2. Classifica o contato (cliente PHN_ / pessoal / desconhecido) via
     ContatoSalvo (sync da agenda) + Telefone + pushName.
  3. Contato pessoal -> ignora (o dono responde). Desconhecido sem resposta
     prévia -> saúda conforme o horário.
  4. Cliente bloqueado -> armazena, marca humana, sem responder.
  5. Se o cliente digitou um CPF nesta mensagem: valida em Python; se inválido
     pede de novo, se não bate com o cadastro pede o correto, senão marca
     cpf_verificado e segue (a IA retoma o atendimento pendente pelo histórico).
  6. Chama a IA com ESTADO (cpf_verificado, database_atualizada, contato_tipo)
     e os CONTRATOS ATIVOS — que só são passados se cpf verificado E database
     fresca (garantia dura: a IA nunca vê dados desatualizados/de terceiro).
  7. Gates pós-IA em Python: exige CPF p/ info específica/pagamento/segunda
     via; exige database fresca p/ info específica/pagamento.
  8. Cria Solicitação(ões) quando pronto (uma por ação/distinta/prazo).
  9. segunda_via: clona a última solicitação com boleto do dia anterior e
     pede confirmação.
"""
import logging
import os
import re
from datetime import timedelta

from django.utils import timezone

from core.models import (
    BotConfig,
    Cliente,
    ContratoPenhor,
    Conversa,
    ContatoSalvo,
    FAQ,
    FAQResposta,
    Mensagem,
    MensagensConfig,
    Solicitacao,
    Telefone,
)
from core.utils import normalizar_cpf, normalize_phone_br, parse_nome_salvo, validar_cpf
from ia.schemas import TipoIntencao, TipoPagamento
from ia.services import extrair_intencao

from .evolution_client import get_client

logger = logging.getLogger(__name__)

HISTORICO_TAMANHO = 10
VERIFICACAO_VALIDADE = timedelta(hours=24)
JANELA_NAO_LIDAS = timedelta(hours=24)
PRAZOS_RENOVACAO = (30, 60, 90, 120, 150, 180)

# Situações (código) que representam contrato liquidado -> não ativo.
SITUACOES_LIQUIDADAS_COD = {"LQ", "LQVL", "LQDE", "SJLQ", "LQSD"}

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


def _extrair_cpf_texto(texto: str) -> str:
    """Extrai um token de 11 dígitos (CPF formatado ou cru) da mensagem.

    Retorna os 11 dígitos se encontrar um padrão de CPF, ou '' caso contrário.
    Não valida o checksum — só detecta que parece um CPF. A validação fica a
    cargo do gate em Python (validar_cpf).
    """
    if not texto:
        return ""
    m = re.search(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}", texto)
    if m:
        digits = re.sub(r"\D", "", m.group(0))
        if len(digits) == 11:
            return digits
    # fallback: mensagem que é só 11 dígitos
    only_digits = re.sub(r"\D", "", texto)
    if len(only_digits) == 11:
        return only_digits
    return ""


def _buscar_cliente_por_cpf(cpf_digits: str):
    """Tenta achar um Cliente pelo CPF, tolerando formatação diferente no PK."""
    c = Cliente.objects.filter(cpf=cpf_digits).first()
    if c:
        return c
    tail = cpf_digits[-8:]
    for cand in Cliente.objects.filter(cpf__icontains=tail)[:50]:
        if normalizar_cpf(cand.cpf) == cpf_digits:
            return cand
    return None


def _classificar_contato(conv: Conversa, mensagem: Mensagem):
    """Retorna (tipo_contato, nome_salvo, cliente)."""
    numero = _remote_jid_para_numero(conv.remote_jid)
    tel = Telefone.objects.select_related("cliente").filter(numero=numero).first() if numero else None
    cliente = tel.cliente if tel else None

    cs = ContatoSalvo.objects.filter(remote_jid=conv.remote_jid).first()
    if cs:
        nome_salvo = cs.nome_salvo
        if cs.tipo == ContatoSalvo.Tipo.PESSOAL:
            return Conversa.TipoContato.PESSOAL, nome_salvo, cliente
        # CLIENTE
        if not cliente and cs.cpf:
            cliente = _buscar_cliente_por_cpf(cs.cpf) or cliente
        return Conversa.TipoContato.CLIENTE, nome_salvo, cliente

    # fallback: pushName do webhook (nome de perfil / salvo informado no payload)
    push = (mensagem.push_name or "").strip()
    cpf_nome, _ = parse_nome_salvo(push)
    if push:
        if cpf_nome:
            return Conversa.TipoContato.CLIENTE, push, (_buscar_cliente_por_cpf(cpf_nome) or cliente)
        return Conversa.TipoContato.PESSOAL, push, cliente

    if cliente:
        return Conversa.TipoContato.CLIENTE, "", cliente
    return Conversa.TipoContato.DESCONHECIDO, "", None


def _contratos_ativos_values(cliente):
    """Contratos ativos do cliente com SOMENTE os campos permitidos, prontos
    para a IA. Exclui liquidados. Esta é a garantia dura de que a IA nunca vê
    dados pessoais, contratos de terceiros ou contratos liquidados."""
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
        msgs.msg_segunda_via_confirma.format(contratos=contratos_txt, tipo=sol.get_tipo_display())
    )
    conv.estado = Conversa.Estado.AGUARDANDO_BOLETO
    conv.save(update_fields=["estado", "ultima_interacao"])


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

    conv = mensagem.conversa
    client = get_client()
    numero_destino = _remote_jid_para_numero(conv.remote_jid)
    msgs = MensagensConfig.get_solo()

    def responder(texto: str):
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto=texto)
        if numero_destino:
            client.send_text(numero_destino, texto)
        else:
            logger.warning("Não foi possível normalizar número para responder conversa %s", conv.id)

    def responder_arquivo(caminho_completo: str, nome_arquivo: str, legenda: str = ""):
        texto_msg = legenda or f"Enviou arquivo: {nome_arquivo}"
        Mensagem.objects.create(conversa=conv, direcao=Mensagem.Direcao.OUT, texto=texto_msg)
        if numero_destino:
            client.send_file(numero_destino, caminho_completo, nome_arquivo, caption=legenda)
        else:
            logger.warning("Não foi possível normalizar número para enviar arquivo na conversa %s", conv.id)

    # 1) Classificar contato
    tipo_contato, nome_salvo, cliente = _classificar_contato(conv, mensagem)
    conv.tipo_contato = tipo_contato
    if nome_salvo:
        conv.nome_salvo = nome_salvo
    if cliente and conv.cliente_id is None:
        conv.cliente = cliente
    conv.save(update_fields=["tipo_contato", "nome_salvo", "cliente", "ultima_interacao"])
    cliente = conv.cliente  # refreshed

    # 2) Contato pessoal -> ignora
    if tipo_contato == Conversa.TipoContato.PESSOAL:
        logger.info("Contato pessoal %s: mensagem %s armazenada sem resposta", conv.remote_jid, mensagem_id)
        return

    # 3) Cliente bloqueado
    if cliente and cliente.bloqueado_ia:
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        logger.info("Cliente %s bloqueado p/ IA: mensagem %s sem resposta", cliente.cpf, mensagem_id)
        return

    # 4) Desconhecido sem resposta prévia -> saúda e encerra este turno
    tem_out_anterior = conv.mensagens.filter(direcao=Mensagem.Direcao.OUT).exists()
    if tipo_contato == Conversa.TipoContato.DESCONHECIDO and not tem_out_anterior:
        if bot.responder_desconhecidos:
            responder(msgs.msg_saudacao.format(saudacao=_saudacao()))
        else:
            conv.precisa_revisao_humana = True
            conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        return

    # 5) CPF digitado nesta mensagem -> valida em Python
    cpf_digitado = _extrair_cpf_texto(mensagem.texto)
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
        conv.estado = Conversa.Estado.VERIFICADA
        if not cliente:
            cliente = _buscar_cliente_por_cpf(cpf_digitado)
            if cliente:
                conv.cliente = cliente
        conv.save(update_fields=["cpf_verificado", "verified_at", "estado", "cliente", "ultima_interacao"])
        cliente = conv.cliente

    # verificação expirada?
    if conv.verified_at and (timezone.now() - conv.verified_at) > VERIFICACAO_VALIDADE:
        conv.cpf_verificado = ""
        conv.verified_at = None
        conv.estado = Conversa.Estado.AGUARDANDO_VERIFICACAO
        conv.save(update_fields=["cpf_verificado", "verified_at", "estado", "ultima_interacao"])

    cpf_verificado = bool(conv.cpf_verificado)
    db_atualizada = bot.database_atualizada()

    # 6) Garantia dura: contratos só chegam à IA se cpf verificado E db fresca.
    contratos_para_ia = []
    if cliente and cpf_verificado and db_atualizada:
        contratos_para_ia = _contratos_ativos_values(cliente)

    # última solicitação do cliente (contexto p/ segunda via / continuidade)
    ultima_sol = None
    if cliente:
        sol = cliente.solicitacoes.order_by("-criado_em").first()
        if sol:
            ultima_sol = {
                "tipo": sol.tipo,
                "prazo_dias": sol.prazo_dias,
                "contratos": list(sol.contratos.values_list("contrato", flat=True)),
                "status": sol.status,
            }

    faqs = list(FAQ.objects.filter(ativo=True).values("id", "pergunta"))
    historico = list(
        conv.mensagens.order_by("-criado_em").values("direcao", "texto")[:HISTORICO_TAMANHO]
    )[::-1]

    resultado = extrair_intencao(
        mensagem.texto,
        historico,
        contratos_para_ia,
        faqs,
        cpf_verificado=cpf_verificado,
        db_atualizada=db_atualizada,
        contato_tipo=tipo_contato,
        cliente_cpf=normalizar_cpf(cliente.cpf) if cliente else "",
        cliente_nome=cliente.nome if cliente else "",
        ultima_solicitacao=ultima_sol,
    )

    # 7) Gates pós-IA (hard rules em Python)
    exige_cpf = resultado.tipo_intencao in (
        TipoIntencao.DUVIDA_ESPECIFICA, TipoIntencao.PAGAMENTO, TipoIntencao.SEGUNDA_VIA
    )
    if exige_cpf and not cpf_verificado:
        if tipo_contato == Conversa.TipoContato.DESCONHECIDO:
            responder(msgs.msg_cadastro_nao_localizado)
        else:
            conv.estado = Conversa.Estado.AGUARDANDO_VERIFICACAO
            conv.save(update_fields=["estado", "ultima_interacao"])
            responder(msgs.msg_pedir_cpf)
        return

    exige_db = resultado.tipo_intencao in (TipoIntencao.DUVIDA_ESPECIFICA, TipoIntencao.PAGAMENTO)
    if exige_db and not db_atualizada:
        conv.precisa_revisao_humana = True
        conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
        responder(msgs.msg_db_desatualizada)
        return

    # 8) Pagamento: cria solicitações quando pronto
    if (
        resultado.tipo_intencao == TipoIntencao.PAGAMENTO
        and resultado.pronto_para_criar_solicitacao
        and resultado.solicitacoes
        and cpf_verificado
        and db_atualizada
        and cliente
    ):
        _criar_solicitacoes(conv, cliente, resultado.solicitacoes)
        conv.estado = Conversa.Estado.AGUARDANDO_BOLETO
        conv.save(update_fields=["estado", "ultima_interacao"])
        responder(resultado.resposta_sugerida or msgs.msg_solicitacao_criada)
        return

    # 9) Segunda via
    if resultado.tipo_intencao == TipoIntencao.SEGUNDA_VIA and cliente:
        _handle_segunda_via(conv, cliente, msgs, responder)
        return

    # 9.5) Resposta via FAQ (com suporte a múltiplas mensagens e arquivos)
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

            if resultado.precisa_humano:
                conv.precisa_revisao_humana = True
            conv.save(update_fields=["precisa_revisao_humana", "ultima_interacao"])
            return
        except FAQ.DoesNotExist:
            logger.warning("FAQ %s classificada pelo IA não existe ou está inativa.", resultado.faq_id)

    # 10) Resposta padrão
    if resultado.precisa_humano:
        conv.precisa_revisao_humana = True
    if resultado.tipo_intencao in (
        TipoIntencao.PAGAMENTO, TipoIntencao.DUVIDA_ESPECIFICA
    ) and resultado.tipo_intencao != TipoIntencao.DUVIDA_GERAL:
        conv.estado = Conversa.Estado.INTENCAO_CAPTURADA
    conv.save(update_fields=["precisa_revisao_humana", "estado", "ultima_interacao"])
    responder(resultado.resposta_sugerida or msgs.msg_neutra_padrao)


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
    ContatoSalvo, classificando PHN_CPF_NOME (cliente) vs. demais (pessoal)."""
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
