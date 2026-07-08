import logging
from datetime import timedelta

from django.utils import timezone

from core.models import Boleto, Mensagem, MensagensConfig, Solicitacao
from whatsapp.evolution_client import get_client

logger = logging.getLogger(__name__)


def enviar_boletos(solicitacao_id: int):
    """django-q2 task: envia cada Boleto não-enviado da Solicitação ao
    WhatsApp do cliente (PDF + linha digitável) e, ao final, dispara a
    mensagem de acompanhamento conforme o tipo (quitação -> resgate de
    garantias; renovação -> pagar hoje + próximo vencimento)."""
    try:
        solicitacao = Solicitacao.objects.select_related("cliente", "conversa").get(pk=solicitacao_id)
    except Solicitacao.DoesNotExist:
        logger.warning("enviar_boletos: Solicitacao %s não encontrada", solicitacao_id)
        return

    if not solicitacao.cliente:
        logger.warning("enviar_boletos: Solicitacao %s sem cliente associado", solicitacao_id)
        return

    telefone = solicitacao.cliente.telefones.first()
    if not telefone:
        logger.warning("enviar_boletos: cliente %s sem telefone cadastrado", solicitacao.cliente_id)
        return

    client = get_client()
    pendentes = list(Boleto.objects.filter(solicitacao=solicitacao, enviado_em__isnull=True))
    msgs = MensagensConfig.get_solo()

    def _enviar_texto(texto: str):
        Mensagem.objects.create(
            conversa=solicitacao.conversa, direcao=Mensagem.Direcao.OUT, texto=texto
        )
        if not client.send_text(telefone.numero, texto):
            logger.error("Falha ao enviar texto p/ %s", telefone.numero)

    # Intro uma vez só, antes do primeiro PDF.
    if pendentes:
        _enviar_texto(msgs.msg_boleto_intro)

    algum_enviado = False
    for boleto in pendentes:
        filename = boleto.arquivo.name.rsplit("/", 1)[-1]
        ok = client.send_media_pdf(telefone.numero, boleto.arquivo.path, filename)
        if ok:
            boleto.enviado_em = timezone.now()
            boleto.save(update_fields=["enviado_em"])
            algum_enviado = True
            if boleto.linha_digitavel:
                _enviar_texto(boleto.linha_digitavel)
        else:
            logger.error("Falha ao enviar boleto %s para %s", boleto.id, telefone.numero)

    if algum_enviado:
        solicitacao.status = Solicitacao.Status.BOLETO_ENVIADO
        solicitacao.save(update_fields=["status", "atualizado_em"])
        _enviar_acompanhamento(solicitacao, msgs, _enviar_texto)


def _enviar_acompanhamento(solicitacao: Solicitacao, msgs, enviar_texto):
    """Mensagem final conforme o tipo da solicitação."""
    hoje = timezone.localdate()
    if solicitacao.tipo == Solicitacao.Tipo.QUITAR:
        from core.models import BotConfig
        dias = max(1, BotConfig.get_solo().dias_resgate_garantia)
        data_resgate = (hoje + timedelta(days=dias)).strftime("%d/%m/%Y")
        enviar_texto(msgs.msg_quitacao_garantia.format(data_resgate=data_resgate))
    elif solicitacao.tipo == Solicitacao.Tipo.RENOVAR and solicitacao.prazo_dias:
        proximo = (hoje + timedelta(days=solicitacao.prazo_dias)).strftime("%d/%m/%Y")
        enviar_texto(msgs.msg_renovacao_proximo_vencimento.format(proximo_vencimento=proximo))
